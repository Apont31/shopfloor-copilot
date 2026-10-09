"""Ligne de commande.

python -m shopfloor.cli ingest
python -m shopfloor.cli search "requête" [--k 4] [--domaine composite]
python -m shopfloor.cli process <fiche> [--llm ollama|none] [--erp-url URL] [--valide-par NOM] [--decision approve|reject]
"""

import argparse
import sys
import time
from collections.abc import Callable
from dataclasses import replace
from pathlib import Path

from chromadb.errors import NotFoundError

from shopfloor.agent.graph import Deps, build_graph, get_state, resume, start
from shopfloor.agent.state import AgentState, HumanDecision
from shopfloor.config import Settings
from shopfloor.erp.client import ErpClient
from shopfloor.errors import RAG_INDISPONIBLE, OllamaUnavailableError
from shopfloor.llm.ollama_client import OllamaLLM
from shopfloor.oracle.loader import load_tolerances
from shopfloor.rag.embeddings import OllamaEmbedder
from shopfloor.rag.ingest import ingest
from shopfloor.rag.retriever import make_retriever, retrieve_similar

TOLERANCES_PATH = Path(__file__).resolve().parents[2] / "config" / "tolerances.yaml"

Decide = Callable[[dict], HumanDecision | dict]


# --- process : logique testable -------------------------------------------------------------------


class ChronoLLM:
    """Enveloppe un LLMClient pour mesurer la durée de chaque appel (affichage uniquement)."""

    def __init__(self, llm):
        self.llm = llm
        self.durations: list[float] = []

    def complete_json(self, system: str, user: str, json_schema: dict) -> str:
        t0 = time.perf_counter()
        try:
            return self.llm.complete_json(system, user, json_schema)
        finally:
            self.durations.append(time.perf_counter() - t0)


def _fmt(v) -> str:
    return "-" if v is None else str(v)


def _print_oracle(state: AgentState) -> None:
    oracle = state.oracle
    print(f"Fiche {oracle.nc_id} - pièce {state.nc.part_ref}, procédé {state.nc.procede}")
    print(f"Verdict de l'oracle : {oracle.verdict.value}")
    rows = [("Caractéristique", "Valeur", "Min", "Max", "Écart", "Statut")]
    rows += [
        (d.caracteristique, f"{d.valeur} {d.unite}", _fmt(d.min), _fmt(d.max), _fmt(d.ecart), d.statut.value)
        for d in oracle.details
    ]
    widths = [max(len(r[i]) for r in rows) for i in range(len(rows[0]))]
    for r in rows:
        print("  " + "  ".join(cell.ljust(w) for cell, w in zip(r, widths)).rstrip())


def _print_similar(state: AgentState) -> None:
    if not state.similar:
        print("\nDocuments similaires : aucun (pas de recherche pour ce verdict)")
        return
    print("\nDocuments similaires :")
    for c in state.similar:
        print(f"  {c.doc_id:<13} score={c.score:.3f}  ({c.section})")


def _print_proposal(state: AgentState, chrono: ChronoLLM | None) -> None:
    p = state.proposal
    print(f"\nProposition (origine : {p.origine})")
    print(f"  Résumé             : {p.resume}")
    print(f"  Cause probable     : {p.cause_probable}")
    print(f"  Action corrective  : {p.action_corrective}")
    print(f"  Décision suggérée  : {p.decision_suggeree}")
    print(f"  Sources            : {', '.join(p.sources) or 'aucune'}")
    if state.guard is not None and not state.guard.ok:
        print("\nALERTE garde-fou :")
        for m in state.guard.motifs:
            print(f"  - {m}")
    if chrono is None or not chrono.durations:
        print("\nAppel LLM : aucun")
    else:
        detail = " + ".join(f"{d:.1f} s" for d in chrono.durations)
        print(f"\nAppel LLM : {sum(chrono.durations):.1f} s ({len(chrono.durations)} appel(s) : {detail})")


def run_process(path: str | Path, deps: Deps, decide: Decide) -> int:
    """Traite une fiche de bout en bout. Renvoie le code de sortie : 0 succès, 1 erreur."""
    chrono = ChronoLLM(deps.llm) if deps.llm is not None else None
    graph = build_graph(replace(deps, llm=chrono) if chrono is not None else deps)
    config = start(graph, path)
    state = get_state(graph, config)

    if state.oracle is not None:
        _print_oracle(state)
    if state.error is None:
        _print_similar(state)
        _print_proposal(state, chrono)
        [pending] = graph.get_state(config).interrupts
        try:
            decision = decide(pending.value)
        except (EOFError, KeyboardInterrupt):
            print("\nERREUR : traitement interrompu sans décision, aucun ticket créé.")
            return 1
        resume(graph, config, decision)
        state = get_state(graph, config)

    if state.error is not None:
        message = state.error
        if message == "ERP indisponible":
            message += f" : serveur injoignable à {deps.erp.base_url} (lancez le serveur ERP)"
        print(f"\nERREUR : {message}")
        return 1
    if state.ticket is not None:
        print(f"\nTicket créé : {state.ticket.id}")
        return 0
    print("\nProposition rejetée : aucun ticket créé.")
    return 0


def ask_decision(payload: dict, valide_par: str | None = None, input_fn=input) -> HumanDecision:
    """Décision interactive : [a]pprouver / [m]odifier / [r]ejeter."""
    while not (valide_par and valide_par.strip()):
        valide_par = input_fn("Validé par : ")
    while True:
        choix = input_fn("[a]pprouver / [m]odifier / [r]ejeter ? ").strip().lower()
        if choix in ("a", "approuver"):
            return HumanDecision(decision="approve", valide_par=valide_par)
        if choix in ("m", "modifier"):
            action = input_fn("Nouvelle action corrective : ").strip()
            if action:
                return HumanDecision(decision="edit", action_corrective=action, valide_par=valide_par)
            print("Action vide : choix annulé.")
        elif choix in ("r", "rejeter"):
            commentaire = input_fn("Commentaire (facultatif) : ").strip() or None
            return HumanDecision(decision="reject", valide_par=valide_par, commentaire=commentaire)
        else:
            print("Choix invalide : tapez a, m ou r.")


# --- CLI : couche fine ----------------------------------------------------------------------------


def main(argv: list[str] | None = None, embedder=None) -> int:
    parser = argparse.ArgumentParser(prog="shopfloor", description="ShopFloor Copilot (100 % local)")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("ingest", help="indexe data/docs/ dans ChromaDB (collection recréée)")
    p_search = sub.add_parser("search", help="recherche des passages similaires")
    p_search.add_argument("query")
    p_search.add_argument("--k", type=int, default=4)
    p_search.add_argument("--domaine", choices=["composite", "tolerie", "peinture", "qualite"])
    p_process = sub.add_parser("process", help="traite une fiche NC de bout en bout")
    p_process.add_argument("fiche")
    p_process.add_argument("--llm", choices=["ollama", "none"], default="ollama")
    p_process.add_argument("--erp-url", help="URL de l'API ERP (défaut : ERP_URL)")
    p_process.add_argument("--valide-par", help="nom du valideur (demandé si absent en mode interactif)")
    p_process.add_argument("--decision", choices=["approve", "reject"], help="sans cette option, la décision est demandée")
    args = parser.parse_args(argv)
    if args.command == "process" and args.decision and not args.valide_par:
        parser.error("--decision exige --valide-par")

    settings = Settings()
    embedder = embedder or OllamaEmbedder(settings)
    if args.command == "ingest":
        try:
            n = ingest(embedder)
        except OllamaUnavailableError as e:
            print(f"ERREUR : {e}")
            return 1
        print(f"{n} chunks indexés dans la collection shopfloor_docs")
        return 0

    if args.command == "process":
        if args.decision:
            decision = HumanDecision(decision=args.decision, valide_par=args.valide_par)

            def decide(payload: dict) -> HumanDecision:
                return decision
        else:

            def decide(payload: dict) -> HumanDecision:
                return ask_decision(payload, args.valide_par)

        with ErpClient(args.erp_url or settings.erp_url) as erp:
            deps = Deps(
                tolerances=load_tolerances(TOLERANCES_PATH),
                retriever=make_retriever(settings.chroma_dir, embedder),
                llm=OllamaLLM(settings) if args.llm == "ollama" else None,
                erp=erp,
            )
            return run_process(args.fiche, deps, decide)

    where = {"domaine": args.domaine} if args.domaine else None
    try:
        results = retrieve_similar(args.query, k=args.k, where=where, embedder=embedder)
    except OllamaUnavailableError as e:
        print(f"ERREUR : {e}")
        return 1
    except NotFoundError:
        print(f"ERREUR : {RAG_INDISPONIBLE}")
        return 1
    if not results:
        print("aucun résultat")
    for i, r in enumerate(results, 1):
        print(f"{i}. {r.doc_id:<13} {r.section:<20} score={r.score:.3f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
