"""Mise en forme pure pour l'interface et la CLI : libellés, lignes de tableaux, pourcentages, messages.
Aucun appel Streamlit.

Rien ici ne décide : les verdicts viennent de l'oracle, les statuts du journal, les tickets de l'ERP.
Les libellés ne servent qu'à l'affichage : le YAML, les modèles, l'oracle et les bases gardent les codes.
"""

import re
from collections import Counter
from collections.abc import Iterable

from shopfloor.erp.schemas import Ticket
from shopfloor.journal import Run
from shopfloor.service import PendingItem, RunSummary

UNITES_AFFICHEES = {"pct": "%", "um": "µm", "deg": "°", "degC": "°C"}
LIBELLES_CARACTERISTIQUE = {
    "porosite": "Porosité", "epaisseur": "Épaisseur", "temperature_cuisson": "Température de cuisson",
    "angle_pli": "Angle de pli", "longueur": "Longueur", "planeite": "Planéité",
    "epaisseur_film": "Épaisseur de film", "adherence": "Adhérence", "brillance": "Brillance",
    "rugosite": "Rugosité",
}
LIBELLES_PROCEDE = {"composite": "Composite", "tolerie": "Tôlerie", "peinture": "Peinture", "qualite": "Qualité"}
LIBELLES_VERDICT = {"NON_CONFORME": "Non conforme", "CONFORME": "Conforme", "INDETERMINE": "Indéterminé"}
LIBELLES_STATUT = {
    "en_attente": "en attente", "approuve": "approuvée", "modifie": "modifiée", "rejete": "rejetée",
    "erreur": "en erreur", "doublon": "doublon",
}
LIBELLES_ORIGINE = {"llm": "LLM", "deterministe": "Déterministe", "aucune": "-"}
LIBELLES_DECISION = {"rebut": "Rebut", "retouche": "Retouche", "derogation": "Dérogation", "escalade": "Escalade"}
HASH_COURT = 8
GRAVITE = ("NON_CONFORME", "INDETERMINE", "CONFORME")  # ordre de la file de validation


def _libelle(code: str | None, libelles: dict[str, str]) -> str:
    """Libellé connu, sinon le code lisible : « epaisseur_peau » -> « Epaisseur peau ». None -> « - »."""
    if code is None:
        return "-"
    if code in libelles:
        return libelles[code]
    texte = code.replace("_", " ")
    return texte[:1].upper() + texte[1:]


def libelle_caracteristique(code: str | None) -> str:
    return _libelle(code, LIBELLES_CARACTERISTIQUE)


def libelle_procede(code: str | None) -> str:
    return _libelle(code, LIBELLES_PROCEDE)


def libelle_verdict(code: str | None) -> str:
    """« NON_CONFORME » -> « Non conforme » ; None (pas de verdict) -> « - »."""
    return _libelle(code, LIBELLES_VERDICT)


def fmt_mesure(v, unite: str) -> str:
    """Valeur suivie de son unité lisible : 2.8 pct -> « 2.8 % », 91.2 deg -> « 91.2° ». None -> « - »."""
    if v is None:
        return "-"
    symbole = UNITES_AFFICHEES.get(unite, unite)
    return f"{v}{symbole}" if symbole == "°" else f"{v} {symbole}"

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
            "Caractéristique": libelle_caracteristique(m["caracteristique"]),
            "Valeur": fmt_mesure(m["valeur"], m["unite"]),
            "Min": fmt_mesure(m["min"], m["unite"]),
            "Max": fmt_mesure(m["max"], m["unite"]),
            "Écart": fmt_mesure(m["ecart"], m["unite"]),
            "Statut": libelle_verdict(m["statut"]),
        }
        for m in mesures
    ]


def recap_rows(results: list[RunSummary]) -> list[dict]:
    return [
        {
            "Fiche": r.nc_id,
            "Verdict": libelle_verdict(r.verdict),
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


# Largeurs minimales (px) des colonnes de ticket_rows ; le tableau les étire jusqu'à la largeur de la page.
# Total 840 px : sans défilement horizontal sur un écran de 1400 px, barre latérale ouverte (~940 px utiles).
LARGEURS_TICKETS = {
    "Ticket": 90, "Fiche": 110, "Verdict": 120, "Statut": 90, "Valideur": 180, "Date": 160, "Règles": 90,
}


def ticket_rows(tickets: list[Ticket]) -> list[dict]:
    return [
        {
            "Ticket": t.id,
            "Fiche": t.nc_id,
            "Verdict": libelle_verdict(t.verdict),
            "Statut": t.statut,
            "Valideur": t.valide_par,
            "Date": f"{t.created_at:%Y-%m-%d %H:%M} UTC",
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
