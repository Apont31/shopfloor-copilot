"""Mise en forme pure pour l'interface : lignes de tableaux, pourcentages, messages. Aucun appel Streamlit.

Rien ici ne décide : les verdicts viennent de l'oracle, les statuts du journal, les tickets de l'ERP.
"""

import re
from collections import Counter
from collections.abc import Iterable

from shopfloor.cli import fmt_mesure
from shopfloor.erp.schemas import Ticket
from shopfloor.journal import Run
from shopfloor.service import PendingItem, RunSummary

LIBELLES_STATUT = {
    "en_attente": "en attente", "approuve": "approuvée", "modifie": "modifiée", "rejete": "rejetée",
    "erreur": "en erreur", "doublon": "doublon",
}
LIBELLES_ORIGINE = {"llm": "LLM", "deterministe": "Déterministe", "aucune": "-"}
LIBELLES_DECISION = {"rebut": "Rebut", "retouche": "Retouche", "derogation": "Dérogation", "escalade": "Escalade"}
HASH_COURT = 12
GRAVITE = ("NON_CONFORME", "INDETERMINE", "CONFORME")  # ordre de la file de validation

# Ponctuation qui peut former du markdown (liens, images, HTML, titres, listes, code, LaTeX, liens automatiques
# GFM sur « http:// », « www. » ou une adresse e-mail, directives Streamlit « :red[...] »).
_MARKDOWN = re.compile(r"([\\`*_{}\[\]()#+\-.!|<>~$:=@&])")


def texte_brut(texte: str) -> str:
    """Texte non fiable (sortie du LLM, documents, fiches) à passer à st.markdown : affiché tel quel.

    Chaque caractère de ponctuation markdown est échappé par une barre oblique inverse, ce qui empêche
    images, liens, HTML et mise en forme ; les retours à la ligne sont conservés.
    """
    return _MARKDOWN.sub(r"\\\1", texte).replace("\n", "  \n")


def filtrer_trier(
    items: Iterable[PendingItem], sites: Iterable[str] = (), verdicts: Iterable[str] = ()
) -> list[PendingItem]:
    """File de validation filtrée (une sélection vide ne filtre pas), triée par gravité puis par nc_id.

    Gravité : NON_CONFORME, puis INDETERMINE, puis CONFORME ; une fiche sans verdict passe en dernier.
    """
    sites, verdicts = set(sites), set(verdicts)
    retenus = [
        it for it in items
        if (not sites or it.run.site in sites) and (not verdicts or it.verdict in verdicts)
    ]
    rang = {v: i for i, v in enumerate(GRAVITE)}
    return sorted(retenus, key=lambda it: (rang.get(it.verdict, len(GRAVITE)), it.run.nc_id))


def options_filtres(
    items: Iterable[PendingItem], sites_choisis: Iterable[str] = (), verdicts_choisis: Iterable[str] = ()
) -> tuple[list[str], list[str]]:
    """(sites, triés ; verdicts, par gravité) pour les filtres de la file : ceux des fiches en attente, plus ceux
    déjà choisis, pour qu'une sélection reste valide quand sa dernière fiche quitte la file."""
    items = list(items)
    sites = sorted({it.run.site for it in items if it.run.site} | set(sites_choisis))
    presents = {it.verdict for it in items} | set(verdicts_choisis)
    return sites, [v for v in GRAVITE if v in presents]


def pct(taux: float | None) -> str:
    """0.5 -> « 50 % » ; None (rien à mesurer) -> « - »."""
    return "-" if taux is None else f"{taux * 100:.0f} %"


def duree_s(secondes: float | None) -> str:
    return "-" if secondes is None else f"{secondes:.1f} s"


def mesure_rows(mesures: list[dict]) -> list[dict]:
    """Mesures du verdict de l'oracle (JSON du checkpoint), unités lisibles aussi sur min, max et écart."""
    return [
        {
            "Caractéristique": m["caracteristique"],
            "Valeur": fmt_mesure(m["valeur"], m["unite"]),
            "Min": fmt_mesure(m["min"], m["unite"]),
            "Max": fmt_mesure(m["max"], m["unite"]),
            "Écart": fmt_mesure(m["ecart"], m["unite"]),
            "Statut": m["statut"],
        }
        for m in mesures
    ]


def recap_rows(results: list[RunSummary]) -> list[dict]:
    return [
        {
            "Fiche": r.nc_id,
            "Verdict": r.verdict or "-",
            "Statut": LIBELLES_STATUT[r.statut],
            "Origine": LIBELLES_ORIGINE[r.origine],
            "LLM": duree_s(r.llm_ms / 1000) if r.llm_ms is not None else "-",
            "Détail": r.erreur or "",
        }
        for r in results
    ]


def recap_text(results: list[RunSummary]) -> str:
    """« 3 fiche(s) analysée(s) : 2 en attente, 1 en erreur »."""
    if not results:
        return "Aucune nouvelle fiche dans la boîte de réception."
    statuts = Counter(r.statut for r in results)
    detail = ", ".join(f"{n} {LIBELLES_STATUT[s]}" for s, n in statuts.items())
    return f"{len(results)} fiche(s) analysée(s) : {detail}"


def ticket_rows(tickets: list[Ticket]) -> list[dict]:
    return [
        {
            "Ticket": t.id,
            "Fiche": t.nc_id,
            "Verdict": t.verdict,
            "Statut": t.statut,
            "Valideur": t.valide_par,
            "Date (UTC)": f"{t.created_at:%Y-%m-%d %H:%M}",
            "Règles": t.rules_hash[:HASH_COURT],
        }
        for t in tickets
    ]


def decision_message(run: Run) -> tuple[str, str]:
    """(niveau, message) après une décision : success, info ou error."""
    if run.statut == "erreur":
        return "error", f"{run.nc_id} : {run.erreur}. La fiche passe dans « En erreur »."
    if run.ticket_id is not None:
        return "success", f"{run.nc_id} {LIBELLES_STATUT[run.statut]} : ticket {run.ticket_id} créé"
    return "info", f"{run.nc_id} rejetée : aucun ticket créé"
