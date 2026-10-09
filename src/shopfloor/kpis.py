"""Indicateurs de pilotage calculés sur le journal des traitements. Fonctions pures : aucune base, aucun réseau.

Définitions :
- traitées : toutes les fiches journalisées, quel que soit leur statut ;
- analysées : fiches arrivées jusqu'à une proposition (origine llm ou déterministe), donc jusqu'au valideur ;
- décidées : fiches approuvées, modifiées ou rejetées par un valideur. Une décision dont le ticket n'a pas été
  créé (statut erreur) n'en fait pas partie ;
- taux d'acceptation : (approuvées + modifiées) / décidées, c'est-à-dire la part des décisions suivies d'un ticket.
Un taux sans dénominateur vaut None (rien à mesurer), jamais 0.
"""

from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass

from shopfloor.journal import Run

VERDICTS = ("NON_CONFORME", "CONFORME", "INDETERMINE")
_DECIDES = ("approuve", "modifie", "rejete")


@dataclass(frozen=True)
class Groupe:
    """Indicateurs d'un site ou d'un procédé."""

    nb: int
    decidees: int
    taux_acceptation: float | None


@dataclass(frozen=True)
class Kpis:
    traitees: int
    analysees: int
    en_attente: int
    decidees: int
    erreurs: int  # statut erreur (traitement ou création du ticket)
    doublons: int
    taux_approuvees: float | None  # telles quelles, sur les décidées
    taux_modifiees: float | None
    taux_rejetees: float | None
    nb_llm: int  # propositions du LLM acceptées par le garde-fou
    nb_deterministe: int
    part_llm: float | None  # sur les analysées
    part_deterministe: float | None
    duree_llm_moyenne_s: float | None  # sur les fiches avec au moins un appel au LLM
    verdicts: dict[str, int]  # NON_CONFORME, CONFORME, INDETERMINE (toujours les trois clés)
    par_site: dict[str, Groupe]
    par_procede: dict[str, Groupe]


def _taux(n: int, total: int) -> float | None:
    return n / total if total else None


def _groupe(runs: list[Run]) -> Groupe:
    statuts = Counter(r.statut for r in runs)
    decidees = sum(statuts[s] for s in _DECIDES)
    return Groupe(
        nb=len(runs),
        decidees=decidees,
        taux_acceptation=_taux(statuts["approuve"] + statuts["modifie"], decidees),
    )


def _par(runs: list[Run], attribut: str) -> dict[str, Groupe]:
    groupes: dict[str, list[Run]] = {}
    for r in runs:
        cle = getattr(r, attribut)
        if cle is not None:  # fiche illisible : ni site ni procédé
            groupes.setdefault(cle, []).append(r)
    return {cle: _groupe(groupes[cle]) for cle in sorted(groupes)}


def compute_kpis(runs: Iterable[Run]) -> Kpis:
    runs = list(runs)
    statuts = Counter(r.statut for r in runs)
    origines = Counter(r.origine for r in runs)
    decidees = sum(statuts[s] for s in _DECIDES)
    analysees = origines["llm"] + origines["deterministe"]
    durees = [r.llm_ms for r in runs if r.llm_ms is not None]
    verdicts = Counter(r.verdict for r in runs if r.verdict is not None)
    return Kpis(
        traitees=len(runs),
        analysees=analysees,
        en_attente=statuts["en_attente"],
        decidees=decidees,
        erreurs=statuts["erreur"],
        doublons=statuts["doublon"],
        taux_approuvees=_taux(statuts["approuve"], decidees),
        taux_modifiees=_taux(statuts["modifie"], decidees),
        taux_rejetees=_taux(statuts["rejete"], decidees),
        nb_llm=origines["llm"],
        nb_deterministe=origines["deterministe"],
        part_llm=_taux(origines["llm"], analysees),
        part_deterministe=_taux(origines["deterministe"], analysees),
        duree_llm_moyenne_s=sum(durees) / len(durees) / 1000 if durees else None,
        verdicts={v: verdicts[v] for v in VERDICTS},
        par_site=_par(runs, "site"),
        par_procede=_par(runs, "procede"),
    )


def estimate_time_saved(kpis: Kpis, minutes_manuel: float, minutes_copilote: float) -> float:
    """Heures gagnées sur les fiches analysées, si une NC prend minutes_manuel sans le copilote et
    minutes_copilote avec (relecture et validation comprises).

    HYPOTHÈSE paramétrable, pas une mesure : le journal ne mesure pas le temps passé par le valideur.
    Négatif si le copilote est supposé plus lent.
    """
    if minutes_manuel < 0 or minutes_copilote < 0:
        raise ValueError("les durées par NC doivent être positives ou nulles")
    return kpis.analysees * (minutes_manuel - minutes_copilote) / 60
