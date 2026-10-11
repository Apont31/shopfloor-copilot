"""Couche service : traitement automatique de la boîte de réception, file de validation persistante, journal.

Seule cette couche écrit le journal ; les nœuds du graphe l'ignorent. L'état de chaque fiche en attente
est gardé par le checkpointer SQLite : une validation reprend après un redémarrage du processus.
"""

import threading
from collections.abc import Callable
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Literal

from pydantic import ValidationError

from shopfloor.agent.graph import (
    Deps,
    build_graph,
    get_state,
    nc_id_of,
    resume,
    sqlite_checkpointer,
    start,
    thread_config,
)
from shopfloor.agent.state import AgentState, HumanDecision
from shopfloor.erp.client import ErpUnavailableError
from shopfloor.errors import ERP_INDISPONIBLE, TICKET_EXISTANT
from shopfloor.journal import Journal, JournalError, Run
from shopfloor.llm.chrono import ChronoLLM
from shopfloor.rag.retriever import RetrievedChunk

# Progression de process_inbox : (rang à partir de 1, nombre de fiches à traiter, nc_id), avant chaque fiche.
Progress = Callable[[int, int, str], None]
_STATUT_DECISION = {"approve": "approuve", "edit": "modifie", "reject": "rejete"}


class ServiceError(Exception):
    """Demande impossible : fiche inconnue ou déjà décidée, décision invalide, état de validation perdu."""


@dataclass(frozen=True)
class RunSummary:
    nc_id: str
    fichier: str
    verdict: str | None
    statut: str
    origine: str
    llm_ms: int | None
    erreur: str | None


@dataclass(frozen=True)
class PendingItem:
    """Fiche en attente : ligne du journal + ce que voit le valideur, lu dans le checkpointer.

    proposition vaut None si l'état n'est plus dans la base d'état (fichier supprimé ou remplacé).
    similaires : meilleur passage de chaque document retenu par la recherche ; passages : tous les passages
    retrouvés de ces documents. Listes vides sans recherche (CONFORME, INDETERMINE).
    """

    run: Run
    verdict: str | None
    mesures: list[dict]
    proposition: dict | None
    sources: list[str]
    alerte_garde_fou: list[str] | None
    similaires: list[RetrievedChunk] = field(default_factory=list)
    passages: list[RetrievedChunk] = field(default_factory=list)


def inbox_files(inbox_dir: str | Path) -> list[Path]:
    return sorted(Path(inbox_dir).glob("*.md"))


def _summary(run: Run) -> RunSummary:
    return RunSummary(
        nc_id=run.nc_id, fichier=run.fichier, verdict=run.verdict, statut=run.statut,
        origine=run.origine, llm_ms=run.llm_ms, erreur=run.erreur,
    )


class Service:
    """Graphe sur checkpointer SQLite + journal SQLite. Deux instances sur les mêmes fichiers partagent la file."""

    def __init__(self, deps: Deps, *, state_db: str | Path, journal_db: str | Path):
        self.chrono = ChronoLLM(deps.llm) if deps.llm is not None else None
        self.erp = deps.erp
        self._traitement = threading.Lock()  # une fiche de la boîte traitée à la fois (process_inbox)
        self._saver = sqlite_checkpointer(state_db)
        try:
            self.graph = build_graph(replace(deps, llm=self.chrono) if self.chrono else deps, self._saver)
            self.journal = Journal(journal_db)
        except Exception:
            self._saver.conn.close()
            raise

    def close(self) -> None:
        self.journal.close()
        self._saver.conn.close()

    def __enter__(self) -> "Service":
        return self

    def __exit__(self, *exc_info) -> None:
        self.close()

    # --- Traitement automatique -------------------------------------------------------------------

    def process_inbox(self, inbox_dir: str | Path, progress: Progress | None = None) -> list[RunSummary]:
        """Traite chaque fiche dont le nc_id n'est pas encore journalisé, jusqu'à la validation humaine.

        Une fiche déjà journalisée, quel que soit son statut, est ignorée (relance d'une erreur : retry).
        progress, s'il est fourni, est appelé avant chaque fiche à traiter.

        Appels concurrents (deux sessions de l'interface sur le Service partagé, ou un autre processus) : une fiche
        journalisée entre le listage et son traitement est ignorée, sans exception ni appel LLM en double. Les
        fiches ignorées n'apparaissent pas dans le résultat.
        """
        todo = []
        for path in inbox_files(inbox_dir):
            nc_id = nc_id_of(path)
            if self.journal.get_run(nc_id) is None:
                todo.append((path, nc_id))
        results = []
        for i, (path, nc_id) in enumerate(todo, 1):
            if progress is not None:
                progress(i, len(todo), nc_id)
            run = self._process_once(path, nc_id)
            if run is not None:
                results.append(_summary(run))
        return results

    def _process_once(self, path: Path, nc_id: str) -> Run | None:
        """Traite la fiche si elle n'est toujours pas journalisée ; None si elle l'est déjà (ignorée).

        Une fiche à la fois par Service : la vérification et le traitement ne se chevauchent pas entre sessions,
        et les durées LLM de deux fiches ne se mêlent pas. Un autre processus peut encore journaliser la fiche
        pendant le traitement : l'insertion refusée (JournalError) vaut « déjà journalisée ».
        """
        with self._traitement:
            if self.journal.get_run(nc_id) is not None:
                return None
            try:
                return self._process(path, nc_id)
            except JournalError:
                return None

    def _process(self, path: Path, nc_id: str) -> Run:
        n0 = len(self.chrono.durations) if self.chrono else 0
        try:
            state = get_state(self.graph, start(self.graph, path))
        except Exception as e:  # erreur imprévue : journalisée, le reste de la boîte est traité
            return self.journal.record_error(
                nc_id=nc_id, fichier=path.name, erreur=f"erreur inattendue : {type(e).__name__} : {e}"
            )

        nc = state.nc
        fiche = {"site": nc.site, "procede": nc.procede, "part_ref": nc.part_ref} if nc else {}
        verdict = state.oracle.verdict.value if state.oracle else None
        if state.error is not None:
            doublon = state.error.startswith(TICKET_EXISTANT)
            return self.journal.record_error(
                nc_id=nc_id, fichier=path.name, erreur=state.error, verdict=verdict, **fiche,
                statut="doublon" if doublon else "erreur",
                ticket_id=state.error.rsplit(" : ", 1)[-1] if doublon else None,
            )

        durations = self.chrono.durations[n0:] if self.chrono else []
        return self.journal.record_pending(
            nc_id=nc_id, fichier=path.name, verdict=verdict, **fiche,
            origine=state.proposal.origine,
            guard_ok=state.guard.ok if state.guard is not None else None,
            llm_ms=round(sum(durations) * 1000) if durations else None,
        )

    # --- File de validation -----------------------------------------------------------------------

    def list_pending(self) -> list[PendingItem]:
        items = []
        for run in self.journal.list_runs(statut="en_attente"):
            snapshot = self.graph.get_state(thread_config(run.nc_id))
            review = snapshot.interrupts[0].value if snapshot.interrupts else {}
            state = AgentState.model_validate(snapshot.values) if snapshot.values else None
            items.append(PendingItem(
                run=run,
                verdict=review.get("verdict", run.verdict),
                mesures=review.get("mesures", []),
                proposition=review.get("proposition"),
                sources=review.get("sources", []),
                alerte_garde_fou=review.get("alerte_garde_fou"),
                similaires=list(state.similar) if state else [],
                passages=list(state.passages) if state else [],
            ))
        return items

    def decide(
        self,
        nc_id: str,
        decision: Literal["approve", "reject", "edit"],
        valide_par: str,
        action: str | None = None,
        commentaire: str | None = None,
    ) -> Run:
        """Reprend le graphe avec la décision humaine et met à jour le journal.

        approve ou edit avec l'ERP injoignable : ErpUnavailableError levée avant la reprise du graphe ; la fiche
        reste en attente et son checkpoint est intact. Ticket non créé malgré tout (ERP tombé entre la vérification
        et la création, conflit) : statut erreur, avec le motif.
        """
        run = self.journal.get_run(nc_id)
        if run is None:
            raise ServiceError(f"{nc_id} : fiche absente du journal")
        if run.statut != "en_attente":
            raise ServiceError(f"{nc_id} n'est pas en attente de validation (statut : {run.statut})")
        if action is not None and decision != "edit":
            raise ServiceError("une action modifiée n'est acceptée qu'avec la décision edit")
        try:
            human = HumanDecision(
                decision=decision, action_corrective=action, valide_par=valide_par, commentaire=commentaire
            )
        except ValidationError as e:
            raise ServiceError("décision invalide : " + "; ".join(err["msg"] for err in e.errors())) from e

        config = thread_config(nc_id)
        if not self.graph.get_state(config).interrupts:
            raise ServiceError(f"{nc_id} : état de validation introuvable dans la base d'état")
        if decision in ("approve", "edit"):  # un rejet ne crée pas de ticket : l'ERP n'est pas nécessaire
            try:
                self.erp.health()
            except ErpUnavailableError as e:
                raise ErpUnavailableError(ERP_INDISPONIBLE) from e
        resume(self.graph, config, human)
        state = get_state(self.graph, config)

        statut = _STATUT_DECISION[decision]
        if state.error is not None:
            return self.journal.record_decision(
                nc_id, statut="erreur", decided_by=human.valide_par,
                erreur=f"décision {statut}, ticket non créé : {state.error}",
            )
        return self.journal.record_decision(
            nc_id, statut=statut, decided_by=human.valide_par,
            ticket_id=state.ticket.id if state.ticket is not None else None,
        )

    # --- Relance ----------------------------------------------------------------------------------

    def retry(self, nc_id: str) -> None:
        """Fiche en erreur : efface sa ligne du journal et son thread du checkpoint.

        Elle sera traitée de nouveau, depuis le début, au prochain process_inbox.
        """
        run = self.journal.get_run(nc_id)
        if run is None:
            raise ServiceError(f"{nc_id} : fiche absente du journal")
        if run.statut != "erreur":
            raise ServiceError(f"{nc_id} n'est pas en erreur (statut : {run.statut})")
        self._saver.delete_thread(nc_id)
        self.journal.delete_error(nc_id)
