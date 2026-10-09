"""Page « Pilotage » : indicateurs calculés sur le journal (shopfloor.kpis), graphiques, temps gagné estimé."""

import streamlit as st

from shopfloor.kpis import compute_kpis, estimate_time_saved
from shopfloor.ui import charts, deps, style
from shopfloor.ui.format import duree_s, pct

kpis = compute_kpis(deps.get_service().journal.list_runs())

st.title("Pilotage")
st.caption("Indicateurs calculés sur le journal des traitements.")

c1, c2, c3, c4 = st.columns(4)
c1.metric("Fiches traitées", kpis.traitees, border=True)
c2.metric("En attente", kpis.en_attente, border=True)
c3.metric("Décidées", kpis.decidees, border=True)
c4.metric("Durée LLM moyenne", duree_s(kpis.duree_llm_moyenne_s), border=True)
c1, c2, c3, c4 = st.columns(4)
c1.metric("Approuvées telles quelles", pct(kpis.taux_approuvees), border=True)
c2.metric("Modifiées", pct(kpis.taux_modifiees), border=True)
c3.metric("Rejetées", pct(kpis.taux_rejetees), border=True)
c4.metric("Erreurs et doublons", kpis.erreurs + kpis.doublons, border=True)

if kpis.traitees == 0:
    st.info("Aucune fiche traitée : lancez l'analyse depuis la boîte de réception.", icon=":material/inbox:")
    st.stop()


def _groupes(groupes: dict, nom: str) -> list[dict]:
    rows = []
    for cle, g in groupes.items():
        acceptation = pct(g.taux_acceptation)
        rows.append({
            nom: cle, "Fiches": g.nb, "Décidées": g.decidees, "Acceptation": acceptation,
            "Libellé": f"{g.nb}" + (f" · {acceptation} acceptées" if g.taux_acceptation is not None else ""),
        })
    return sorted(rows, key=lambda r: -r["Fiches"])


gauche, droite = st.columns(2, gap="large")
with gauche:
    st.subheader("Par site")
    st.altair_chart(charts.barres(_groupes(kpis.par_site, "Site"), "Site", "Fiches", texte="Libellé"))
with droite:
    st.subheader("Par procédé")
    st.altair_chart(charts.barres(_groupes(kpis.par_procede, "Procédé"), "Procédé", "Fiches", texte="Libellé"))
st.caption("Acceptation : part des décisions suivies d'un ticket (approuvées ou modifiées).")

gauche, droite = st.columns(2, gap="large")
with gauche:
    st.subheader("Verdicts de l'oracle")
    verdicts = [{"Verdict": style.LIBELLE_VERDICT[v], "Fiches": n} for v, n in kpis.verdicts.items()]
    couleurs = {style.LIBELLE_VERDICT[v]: c for v, c in style.COULEURS_VERDICT.items()}
    st.altair_chart(charts.barres(verdicts, "Verdict", "Fiches", couleurs=couleurs))
with droite:
    st.subheader("Origine des propositions")
    origines = [
        {"Origine": "LLM", "Fiches": kpis.nb_llm, "Part": pct(kpis.part_llm),
         "Libellé": f"{kpis.nb_llm} · {pct(kpis.part_llm)}"},
        {"Origine": "Déterministe", "Fiches": kpis.nb_deterministe, "Part": pct(kpis.part_deterministe),
         "Libellé": f"{kpis.nb_deterministe} · {pct(kpis.part_deterministe)}"},
    ]
    st.altair_chart(charts.barres(origines, "Origine", "Fiches", texte="Libellé", couleurs=style.COULEURS_ORIGINE))
    st.caption("Déterministe : fiches CONFORME ou INDÉTERMINÉ, ou repli après rejet du garde-fou.")

with st.container(border=True):
    st.subheader("Temps gagné estimé")
    st.caption("Hypothèse paramétrable, pas une mesure : le journal n'enregistre pas le temps passé par le valideur.")
    c1, c2, c3 = st.columns([2, 2, 1.4], vertical_alignment="center")
    sans = c1.slider("Minutes par NC sans le copilote", 5, 120, 45, step=5, key="minutes_sans")
    avec = c2.slider("Minutes par NC avec le copilote", 0, 60, 15, step=5, key="minutes_avec")
    heures = estimate_time_saved(kpis, sans, avec)
    c3.metric("Hypothèse", f"{heures:.1f} h")
    st.caption(f"{kpis.analysees} fiche(s) analysée(s) × ({sans} − {avec}) min.")
