"""Couche service : traitement automatique de la boîte de réception, file de validation persistante, journal.

Seule cette couche écrit le journal ; les nœuds du graphe l'ignorent. L'état de chaque fiche en attente
est gardé par le checkpointer SQLite : une validation reprend après un redémarrage du processus.
"""

from dataclasses import dataclass, replace
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
from shopfloor.agent.state import HumanDecision
from shopfloor.journal import Journal, Run
from shopfloor.llm.chrono import ChronoLLM

# Message écrit par le nœud check_existing quand un ticket porte déjà le nc_id : « ... : TCK-0001 ».
_DOUBLON = "Ticket déjà existant pour "
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
    """

    run: Run
    verdict: str | None
    mesures: list[dict]
    proposition: dict | None
    sources: list[str]
    alerte_garde_fou: list[str] | None


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

    def process_inbox(self, inbox_dir: str | Path) -> list[RunSummary]:
        """Traite chaque fiche dont le nc_id n'est pas encore journalisé, jusqu'à la validation humaine.

        Une fiche déjà journalisée, quel que soit son statut, est ignorée.
        """
        results = []
        for path in inbox_files(inbox_dir):
            nc_id = nc_id_of(path)
            if self.journal.get_run(nc_id) is None:
                results.append(_summary(self._process(path, nc_id)))
        return results

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
            doublon = state.error.startswith(_DOUBLON)
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
            interrupts = self.graph.get_state(thread_config(run.nc_id)).interrupts
            review = interrupts[0].value if interrupts else {}
            items.append(PendingItem(
                run=run,
                verdict=review.get("verdict", run.verdict),
                mesures=review.get("mesures", []),
                proposition=review.get("proposition"),
                sources=review.get("sources", []),
                alerte_garde_fou=review.get("alerte_garde_fou"),
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

        Ticket non créé après approve ou edit (ERP injoignable, conflit) : statut erreur, avec le motif.
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
