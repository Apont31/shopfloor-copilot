"""Page « Boîte de réception » : analyse des nouvelles fiches, file de validation, fiches en erreur."""

import streamlit as st

from shopfloor.erp.client import ErpError
from shopfloor.service import PendingItem, ServiceError, inbox_files
from shopfloor.ui import deps, format, style
from shopfloor.ui.format import texte_brut as brut  # tout texte non fiable (LLM, documents, fiches) passe par ici

service = deps.get_service()
inbox_dir = deps.get_inbox_dir()


# --- Actions (callbacks : exécutés avant le rendu suivant, la file affichée est donc à jour) -------


def _flash(niveau: str, message: str) -> None:
    st.session_state.setdefault("flash", []).append((niveau, message))


def _decider(nc_id: str, decision: str) -> None:
    valideur = (st.session_state.get("valideur") or "").strip()
    commentaire = (st.session_state.get(f"commentaire_{nc_id}") or "").strip() or None
    action = st.session_state.get(f"action_{nc_id}") if decision == "edit" else None
    try:
        run = service.decide(nc_id, decision, valideur, action=action, commentaire=commentaire)
    except ErpError as e:  # vérifié avant la reprise du graphe : rien n'est enregistré
        _flash("error", f"{nc_id} : {e}. La fiche reste en attente de validation.")
        return
    except ServiceError as e:
        _flash("error", f"{nc_id} : {e}")
        return
    st.session_state.pop(f"edition_{nc_id}", None)
    _flash(*format.decision_message(run))


def _relancer(nc_id: str) -> None:
    try:
        service.retry(nc_id)
    except ServiceError as e:
        _flash("error", str(e))
        return
    _flash("info", f"{nc_id} sera analysée de nouveau au prochain clic sur « Analyser les nouvelles fiches ».")


def _basculer_edition(nc_id: str) -> None:
    st.session_state[f"edition_{nc_id}"] = not st.session_state.get(f"edition_{nc_id}", False)


# --- Rendu ----------------------------------------------------------------------------------------


def _messages() -> None:
    for niveau, message in st.session_state.pop("flash", []):
        message = brut(message)  # peut citer une erreur contenant le texte d'une fiche
        if niveau == "success":
            st.toast(message, icon=":material/check_circle:")
            st.success(message, icon=":material/confirmation_number:")
        elif niveau == "error":
            st.error(message, icon=":material/error:")
        else:
            st.info(message, icon=":material/info:")


def _analyser() -> None:
    barre = st.progress(0.0, text="Préparation de l'analyse…")

    def progression(i: int, total: int, nc_id: str) -> None:
        barre.progress((i - 1) / total, text=f"Analyse de {nc_id} ({i}/{total})")

    st.session_state["recap"] = service.process_inbox(inbox_dir, progress=progression)
    barre.progress(1.0, text="Analyse terminée")


def _proposition(item: PendingItem, valideur: str) -> None:
    nc_id, p = item.run.nc_id, item.proposition
    libelle, couleur = style.BADGE_ORIGINE[p["origine"]]
    st.markdown(style.label_html("Proposition"), unsafe_allow_html=True)
    st.badge(f"Origine : {libelle}", color=couleur)
    if item.alerte_garde_fou:
        motifs = "\n".join(f"- {brut(m)}" for m in item.alerte_garde_fou)
        st.warning(f"**Le garde-fou a rejeté la sortie du LLM** : proposition déterministe affichée.\n\n{motifs}",
                   icon=":material/shield:")
    st.markdown(
        f"**Résumé** : {brut(p['resume'])}  \n"
        f"**Cause probable** : {brut(p['cause_probable'])}  \n"
        f"**Action corrective** : {brut(p['action_corrective'])}  \n"
        f"**Décision suggérée** : {format.LIBELLES_DECISION[p['decision_suggeree']]}  \n"
        f"**Sources** : {brut(', '.join(item.sources)) or 'aucune'}"
    )

    st.text_input("Commentaire (facultatif)", key=f"commentaire_{nc_id}")
    bloque = not valideur
    c1, c2, c3 = st.columns(3)
    c1.button("Approuver", key=f"approuver_{nc_id}", type="primary", icon=":material/check:", disabled=bloque,
              width="stretch", on_click=_decider, args=(nc_id, "approve"))
    c2.button("Modifier", key=f"modifier_{nc_id}", icon=":material/edit:", disabled=bloque,
              width="stretch", on_click=_basculer_edition, args=(nc_id,))
    c3.button("Rejeter", key=f"rejeter_{nc_id}", icon=":material/close:", disabled=bloque,
              width="stretch", on_click=_decider, args=(nc_id, "reject"))
    if bloque:
        st.caption("Saisissez votre nom dans « Valideur » (barre latérale) pour décider.")
    elif st.session_state.get(f"edition_{nc_id}"):
        st.text_area("Action corrective modifiée", value=p["action_corrective"], key=f"action_{nc_id}", height=110)
        st.button("Valider la modification", key=f"valider_edition_{nc_id}", type="primary",
                  icon=":material/task_alt:", on_click=_decider, args=(nc_id, "edit"))


def _carte(item: PendingItem, valideur: str) -> None:
    run = item.run
    with st.container(border=True):
        gauche, droite = st.columns([4, 1], vertical_alignment="center")
        gauche.markdown(f"#### {brut(run.nc_id)}")
        gauche.caption(brut(f"{run.site} · {format.libelle_procede(run.procede)} · pièce {run.part_ref}"))
        with droite:  # verdict de l'oracle uniquement ; jamais déduit ni remplacé par l'interface
            if item.verdict is None:
                st.badge("Verdict inconnu", color="gray", icon=":material/help:")
            else:
                st.badge(format.libelle_verdict(item.verdict), color=style.BADGE_VERDICT[item.verdict],
                         icon=":material/gavel:")

        st.markdown(style.label_html("Mesures et verdict de l'oracle"), unsafe_allow_html=True)
        st.dataframe(format.mesure_rows(item.mesures), hide_index=True, width="stretch")

        if item.similaires:
            st.markdown(style.label_html("Documents similaires"), unsafe_allow_html=True)
            st.markdown("  \n".join(
                f"**{brut(c.doc_id)}** · {brut(c.section)} · score {c.score:.2f}" for c in item.similaires
            ))
            with st.expander(f"Passages retrouvés ({len(item.passages)})"):
                for c in item.passages:
                    st.markdown(f"**{brut(c.doc_id)}** · {brut(c.section)} · score {c.score:.2f}")
                    st.markdown(brut(c.text))

        if item.proposition is None:
            st.error("État de validation introuvable dans la base d'état : décision impossible.",
                     icon=":material/error:")
            return
        _proposition(item, valideur)


st.title("Boîte de réception")
_messages()

pending = service.list_pending()
erreurs = service.journal.list_runs(statut="erreur")
n_fichiers = len(inbox_files(inbox_dir))

c1, c2, c3, c4 = st.columns(4)
c1.metric("Fiches dans la boîte", n_fichiers)
c2.metric("À valider", len(pending))
c3.metric("En erreur", len(erreurs))
c4.metric("Déjà analysées", len(service.journal.list_runs()))

if st.button("Analyser les nouvelles fiches", key="analyser", type="primary", icon=":material/play_arrow:"):
    _analyser()
    st.rerun()  # compteurs, file et erreurs relus après l'analyse

recap = st.session_state.get("recap")
if recap is not None:
    with st.container(border=True):
        st.markdown(f"**Dernière analyse** : {format.recap_text(recap)}")
        if recap:
            st.dataframe(format.recap_rows(recap), hide_index=True, width="stretch")

titre = st.empty()
sites, verdicts = format.options_filtres(
    pending, st.session_state.get("filtre_sites", ()), st.session_state.get("filtre_verdicts", ())
)
f1, f2 = st.columns(2)
choix_sites = f1.multiselect("Site", sites, key="filtre_sites", placeholder="Tous les sites")
choix_verdicts = f2.multiselect("Verdict", verdicts, key="filtre_verdicts", placeholder="Tous les verdicts",
                                format_func=format.libelle_verdict)
affichees = format.filtrer_trier(pending, choix_sites, choix_verdicts)  # par gravité, puis par nc_id

compte = f"{len(affichees)} sur {len(pending)}" if len(affichees) != len(pending) else f"{len(pending)}"
titre.subheader(f"File de validation ({compte})")
valideur = (st.session_state.get("valideur") or "").strip()
if not pending:
    st.info("Aucune fiche en attente de validation.", icon=":material/inbox:")
elif not affichees:
    st.info("Aucune fiche ne correspond aux filtres.", icon=":material/filter_alt_off:")
for item in affichees:
    _carte(item, valideur)

st.subheader(f"En erreur ({len(erreurs)})")
if not erreurs:
    st.caption("Aucune fiche en erreur.")
for run in erreurs:
    with st.container(border=True):
        gauche, droite = st.columns([4, 1], vertical_alignment="center")
        gauche.markdown(f"**{brut(run.nc_id)}** · {brut(run.fichier)}")
        gauche.caption(brut(run.erreur or ""))
        droite.button("Relancer", key=f"relancer_{run.nc_id}", icon=":material/replay:",
                      width="stretch", on_click=_relancer, args=(run.nc_id,))
