"""Nœuds du graphe (décision D3). Chaque nœud reçoit l'état et les dépendances, et renvoie une mise à jour partielle.

Le verdict n'est écrit que par le nœud oracle ; create_ticket le lit dans state.oracle, jamais dans la proposition.
"""

import json
from dataclasses import dataclass
from typing import Protocol

from langgraph.types import interrupt
from pydantic import ValidationError

from shopfloor.agent.fallback import default_proposal
from shopfloor.agent.guard import GuardResult, check_proposal
from shopfloor.agent.state import AgentState, HumanDecision
from shopfloor.erp.client import ErpClient, ErpConflictError, ErpError, ErpUnavailableError
from shopfloor.erp.schemas import TicketCreate
from shopfloor.errors import OLLAMA_INDISPONIBLE, RAG_INDISPONIBLE, OllamaUnavailableError
from shopfloor.llm.client import LLMClient, LLMError
from shopfloor.llm.prompts import build_proposal_prompt, build_retry_user, proposal_json_schema
from shopfloor.models import ActionProposal, NCRecord, OracleResult, ToleranceTable, Verdict
from shopfloor.nc import NCParseError, parse_nc_file
from shopfloor.oracle.conformity import check_conformity
from shopfloor.rag.retriever import RetrievedChunk


class Retriever(Protocol):
    def __call__(self, query: str, where: dict | None, k: int) -> list[RetrievedChunk]: ...


RETRIEVE_K = 20  # passages demandés avant le regroupement par doc_id
SIMILAR_DOCS = 3
MAX_LLM_CALLS = 2  # D5 : un appel, une relance au maximum


@dataclass(frozen=True, kw_only=True)
class Deps:
    tolerances: ToleranceTable
    retriever: Retriever
    llm: LLMClient | None = None
    erp: ErpClient


def parse_nc(state: AgentState, deps: Deps) -> dict:
    try:
        return {"nc": parse_nc_file(state.nc_path)}
    except NCParseError as e:
        return {"error": f"fiche illisible : {e}"}


def oracle(state: AgentState, deps: Deps) -> dict:
    return {"oracle": check_conformity(state.nc, deps.tolerances)}


def build_query(nc: NCRecord, oracle_result: OracleResult) -> str:
    hors_tolerance = [
        f"{d.caracteristique} {d.valeur} {d.unite} {d.motif}"
        for d in oracle_result.details
        if d.statut == Verdict.NON_CONFORME
    ]
    return " ".join([nc.part_ref, *hors_tolerance, nc.description])


def retrieve_similar(state: AgentState, deps: Deps) -> dict:
    where = {"domaine": {"$in": [state.nc.procede, "qualite"]}}
    try:
        chunks = deps.retriever(build_query(state.nc, state.oracle), where, RETRIEVE_K)
    except OllamaUnavailableError:  # embedder injoignable
        return {"error": OLLAMA_INDISPONIBLE}
    except Exception:  # index absent ou Chroma indisponible : on arrête proprement
        return {"error": RAG_INDISPONIBLE}
    best: dict[str, RetrievedChunk] = {}
    for c in chunks:
        if c.doc_id not in best or c.score > best[c.doc_id].score:
            best[c.doc_id] = c
    top = sorted(best.values(), key=lambda c: c.score, reverse=True)[:SIMILAR_DOCS]
    # Tous les passages retrouvés des documents retenus, du plus proche au plus éloigné : contexte du prompt.
    rang = {c.doc_id: i for i, c in enumerate(top)}
    passages = sorted((c for c in chunks if c.doc_id in rang), key=lambda c: (rang[c.doc_id], -c.score))
    return {"similar": top, "passages": passages}


def _describe(e: ValueError) -> str:
    if isinstance(e, ValidationError):
        return "; ".join(f"{'.'.join(map(str, err['loc'])) or 'racine'} : {err['msg']}" for err in e.errors())
    return str(e)


def parse_proposal(raw: str) -> ActionProposal:
    """JSON brut du LLM -> ActionProposal (origine « llm »). Lève ValueError si invalide."""
    data = json.loads(raw)
    if not isinstance(data, dict):
        raise ValueError("un objet JSON est attendu")
    if "origine" in data:
        raise ValueError("origine : champ réservé, fixé par le code")
    return ActionProposal.model_validate({**data, "origine": "llm"})


def _repli(oracle_result: OracleResult, llm_calls: int, motifs: tuple[str, ...]) -> dict:
    return {
        "proposal": default_proposal(oracle_result),
        "guard": GuardResult(ok=False, motifs=motifs),
        "llm_calls": llm_calls,
    }


def propose_action(state: AgentState, deps: Deps) -> dict:
    if deps.llm is None:
        return _repli(state.oracle, 0, ("aucun LLM configuré : proposition déterministe",))

    system, user = build_proposal_prompt(state.nc, state.oracle, state.passages or state.similar)
    schema = proposal_json_schema()
    prompt = user
    motifs: list[str] = []
    calls = 0
    while calls < MAX_LLM_CALLS:
        calls += 1
        try:
            raw = deps.llm.complete_json(system, prompt, schema)
        except LLMError as e:
            motifs.append(str(e) if isinstance(e, OllamaUnavailableError) else f"appel LLM en échec : {e}")
            break
        try:
            proposal = parse_proposal(raw)
        except ValueError as e:
            motifs.append(f"réponse LLM invalide (appel {calls}) : {_describe(e)}")
            prompt = build_retry_user(user, _describe(e))
            continue
        guard = check_proposal(proposal, state.oracle, [c.doc_id for c in state.similar])
        if not guard.ok:
            return _repli(state.oracle, calls, guard.motifs)
        return {"proposal": proposal, "guard": guard, "llm_calls": calls}
    return _repli(state.oracle, calls, tuple(motifs))


def propose_default(state: AgentState, deps: Deps) -> dict:
    return {"proposal": default_proposal(state.oracle)}


def review_payload(state: AgentState) -> dict:
    """Ce que voit le valideur humain à l'interruption (valeurs JSON uniquement)."""
    guard = state.guard
    return {
        "nc_id": state.oracle.nc_id,
        "verdict": state.oracle.verdict.value,
        "rules_hash": state.oracle.rules_hash,
        "mesures": [d.model_dump(mode="json") for d in state.oracle.details],
        "proposition": state.proposal.model_dump(mode="json"),
        "sources": list(state.proposal.sources),
        "alerte_garde_fou": list(guard.motifs) if guard is not None and not guard.ok else None,
    }


def human_gate(state: AgentState, deps: Deps) -> dict:
    # Le nœud est rejoué à la reprise : tout ce qui précède interrupt() doit rester sans effet de bord.
    human = interrupt(review_payload(state), response_schema=HumanDecision)
    return {"human": human}


def create_ticket(state: AgentState, deps: Deps) -> dict:
    nc, oracle_result, human = state.nc, state.oracle, state.human
    action = human.action_corrective if human.decision == "edit" else state.proposal.action_corrective
    payload = TicketCreate(
        nc_id=nc.nc_id,
        part_ref=nc.part_ref,
        procede=nc.procede,
        site=nc.site,
        verdict=oracle_result.verdict.value,
        rules_hash=oracle_result.rules_hash,
        action_proposee=action,
        sources=list(state.proposal.sources),
        valide_par=human.valide_par,
        commentaire=human.commentaire,
    )
    try:
        return {"ticket": deps.erp.create_ticket(payload)}
    except ErpUnavailableError:
        return {"error": "ERP indisponible"}
    except ErpConflictError as e:
        return {"error": f"ticket déjà existant pour {nc.nc_id} : {e.existing_id}"}
    except ErpError as e:
        return {"error": f"erreur ERP : {e}"}
