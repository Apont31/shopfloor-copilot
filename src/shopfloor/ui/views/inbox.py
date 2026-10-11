"""Page « Boîte de réception » : analyse des nouvelles fiches, file de validation, fiches en erreur.

Fluidité : chaque carte de la file est un fragment (clé carte_<nc_id>). Approuver, Modifier, Envoyer, Annuler et
Rejeter ne réexécutent que la carte, plus les compteurs et le titre de la file après une décision (st.rerun ciblé
par clé de fragment, depuis le callback) : pas de rechargement de la page. Les filtres ne réexécutent que la file.
Les données sont gardées dans la session (deps.memo) et relues seulement après « Analyser », une décision,
« Relancer », ou un changement du journal fait ailleurs (empreinte du journal).
"""

import functools
import logging

import streamlit as st

from shopfloor.erp.client import ErpError
from shopfloor.journal import Run
from shopfloor.service import PendingItem, ServiceError, inbox_files
from shopfloor.ui import deps, format, style
from shopfloor.ui.format import texte_brut as brut  # tout texte non fiable (LLM, documents, fiches) passe par ici

service = deps.get_service()
inbox_dir = deps.get_inbox_dir()
log = logging.getLogger(__name__)

COMPTEURS_S = 5  # rafraîchissement autonome des compteurs (une requête de comptage sur le journal)
DECISIONS = "_decisions"  # nc_id -> Run des fiches décidées depuis la dernière lecture de la file
AFFICHEES = "_affichees"  # (nc_id affichés, nombre de fiches en attente) au dernier rendu de la file


def _cle_carte(nc_id: str) -> str:
    return f"carte_{nc_id}"


# --- Données (cache de la session) ----------------------------------------------------------------


def _lire_file() -> list[PendingItem]:
    st.session_state[DECISIONS] = {}  # file relue : les fiches décidées n'y sont plus
    return service.list_pending()


def _file() -> list[PendingItem]:
    return deps.memo("_file", _lire_file, cle=service.journal.fingerprint())


def _erreurs() -> list[Run]:
    return deps.memo("_erreurs", lambda: service.journal.list_runs(statut="erreur"),
                     cle=service.journal.fingerprint())


# --- Actions (callbacks : exécutés avant le rendu suivant) ----------------------------------------


def _flash(niveau: str, message: str, detail: str | None = None) -> None:
    """Message affiché en haut de la page au prochain rendu complet (analyse, relance)."""
    st.session_state.setdefault("flash", []).append((niveau, message, detail))


def _flash_inattendue(e: Exception, action: str = format.ACTION_ERREUR) -> None:
    """Exception imprévue : message clair et détail technique ; la trace complète va dans le terminal."""
    log.error("Erreur inattendue dans la boîte de réception", exc_info=e)
    _flash("error", *format.erreur_inattendue(e, action))


def _signaler(nc_id: str, message: str, detail: str | None = None) -> None:
    """Erreur affichée dans la carte de la fiche, au prochain rendu de la carte."""
    st.session_state[f"message_{nc_id}"] = (message, detail)


def _decider(nc_id: str, decision: str) -> None:
    valideur = (st.session_state.get("valideur") or "").strip()
    commentaire = (st.session_state.get(f"commentaire_{nc_id}") or "").strip() or None
    action = st.session_state.get(f"action_{nc_id}") if decision == "edit" else None
    try:
        run = service.decide(nc_id, decision, valideur, action=action, commentaire=commentaire)
    except ErpError as e:  # vérifié avant la reprise du graphe : rien n'est enregistré
        _signaler(nc_id, f"{nc_id} : {e}. La fiche reste en attente de validation.")
    except ServiceError as e:
        _signaler(nc_id, f"{nc_id} : {e}")
    except Exception as e:
        log.error("Erreur inattendue lors de la décision sur %s", nc_id, exc_info=e)
        _signaler(nc_id, *format.erreur_inattendue(e))
    else:
        st.session_state.setdefault(DECISIONS, {})[nc_id] = run
        st.session_state[f"toast_{nc_id}"] = format.decision_message(run)[1]
        st.session_state.pop(f"edition_{nc_id}", None)
        deps.invalider()
        st.rerun([_cle_carte(nc_id), "compteurs", "titre_file"])  # la carte devient une ligne compacte
    st.rerun(_cle_carte(nc_id))  # la fiche reste en attente : seule la carte affiche le message


def _ouvrir_edition(nc_id: str) -> None:
    st.session_state[f"edition_{nc_id}"] = True
    st.rerun(_cle_carte(nc_id))


def _fermer_edition(nc_id: str) -> None:
    st.session_state[f"edition_{nc_id}"] = False
    st.session_state.pop(f"action_{nc_id}", None)  # rouverte, la zone repart de la proposition
    st.rerun(_cle_carte(nc_id))


def _relancer(nc_id: str) -> None:
    try:
        service.retry(nc_id)
    except ServiceError as e:
        _flash("error", str(e))
        return
    except Exception as e:
        _flash_inattendue(e)
        return
    deps.invalider()
    _flash("info", f"{nc_id} sera analysée de nouveau au prochain clic sur « Analyser les nouvelles fiches ».")


def _demander_analyse() -> None:
    st.session_state["analyse_en_cours"] = True  # bouton désactivé jusqu'à la fin de l'analyse


# --- Rendu ----------------------------------------------------------------------------------------


def _sans_trace(rendu):
    """Fragment protégé : une exception imprévue s'affiche dans le fragment, en message lisible. Le filet de app.py
    ne couvre pas les réexécutions d'un fragment seul (la page n'est pas réexécutée)."""

    @functools.wraps(rendu)
    def protege(*args):
        try:
            rendu(*args)
        except Exception as e:
            log.error("Erreur inattendue dans la boîte de réception", exc_info=e)
            style.erreur(*format.erreur_inattendue(e))

    return protege


def _messages() -> None:
    for niveau, message, detail in st.session_state.pop("flash", []):
        message = brut(message)  # peut citer une erreur contenant le texte d'une fiche
        if niveau == "success":
            st.toast(message, icon=":material/check_circle:")
            st.success(message, icon=":material/confirmation_number:")
        elif niveau == "error":
            style.erreur(message, detail)
        else:
            st.info(message, icon=":material/info:")


@st.fragment(key="compteurs", run_every=COMPTEURS_S)
@_sans_trace
def _compteurs() -> None:
    """Compteurs du haut : se rafraîchissent seuls, et aussitôt après une décision. Une requête de comptage."""
    statuts = service.journal.count_by_statut()
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Fiches dans la boîte", len(inbox_files(inbox_dir)))
    c2.metric("À valider", statuts.get("en_attente", 0))
    c3.metric("En erreur", statuts.get("erreur", 0))
    c4.metric("Déjà analysées", sum(statuts.values()))


def _analyser() -> None:
    barre = st.progress(0.0, text="Préparation de l'analyse…")

    def progression(i: int, total: int, nc_id: str) -> None:
        barre.progress((i - 1) / total, text=f"Analyse de {nc_id} ({i}/{total})")

    st.session_state["recap"] = service.process_inbox(inbox_dir, progress=progression)
    barre.progress(1.0, text="Analyse terminée")


def _ligne_decision(run: Run) -> None:
    """Ligne compacte qui remplace la carte décidée, sur place."""
    niveau, ligne = format.ligne_decision(run)
    if niveau == "success":
        st.success(brut(ligne), icon=":material/confirmation_number:")
    elif niveau == "error":
        style.erreur(brut(ligne))
    else:
        st.info(brut(ligne), icon=":material/close:")


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

    message = st.session_state.pop(f"message_{nc_id}", None)
    if message is not None:  # décision refusée (ERP indisponible...) : la fiche reste en attente
        style.erreur(brut(message[0]), message[1])

    bloque = not valideur
    if st.session_state.get(f"edition_{nc_id}"):  # zone d'édition dans la carte, à la place des boutons
        st.text_area("Action corrective modifiée", value=p["action_corrective"], key=f"action_{nc_id}", height=110)
        st.text_input("Commentaire (facultatif)", key=f"commentaire_{nc_id}")
        c1, c2 = st.columns(2)
        c1.button("Envoyer", key=f"valider_edition_{nc_id}", type="primary", icon=":material/task_alt:",
                  disabled=bloque, width="stretch", on_click=_decider, args=(nc_id, "edit"))
        c2.button("Annuler", key=f"annuler_{nc_id}", icon=":material/undo:", width="stretch",
                  on_click=_fermer_edition, args=(nc_id,))
    else:
        st.text_input("Commentaire (facultatif)", key=f"commentaire_{nc_id}")
        c1, c2, c3 = st.columns(3)
        c1.button("Approuver", key=f"approuver_{nc_id}", type="primary", icon=":material/check:", disabled=bloque,
                  width="stretch", on_click=_decider, args=(nc_id, "approve"))
        c2.button("Modifier", key=f"modifier_{nc_id}", icon=":material/edit:", disabled=bloque,
                  width="stretch", on_click=_ouvrir_edition, args=(nc_id,))
        c3.button("Rejeter", key=f"rejeter_{nc_id}", icon=":material/close:", disabled=bloque,
                  width="stretch", on_click=_decider, args=(nc_id, "reject"))
    if bloque:
        st.caption("Saisissez votre nom dans « Valideur » (barre latérale) pour décider.")


@_sans_trace
def _carte(item: PendingItem) -> None:
    """Fragment d'une fiche (clé carte_<nc_id>) : réexécuté seul par ses boutons."""
    run = item.run
    decidee = st.session_state.get(DECISIONS, {}).get(run.nc_id)
    if decidee is not None:
        toast = st.session_state.pop(f"toast_{run.nc_id}", None)
        if toast is not None:
            st.toast(brut(toast), icon=":material/check_circle:")
        _ligne_decision(decidee)
        return

    valideur = (st.session_state.get("valideur") or "").strip()
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


@st.fragment(key="titre_file")
def _titre_file() -> None:
    """Titre de la file ; réexécuté avec la carte après une décision, sans relire la file."""
    affichees, total = st.session_state.get(AFFICHEES, ((), 0))
    decidees = st.session_state.get(DECISIONS, {})
    restantes = sum(nc_id not in decidees for nc_id in affichees)
    total -= len(decidees)
    st.subheader(f"File de validation ({restantes} sur {total})" if restantes != total
                 else f"File de validation ({total})")


@st.fragment(key="file")
@_sans_trace
def _file_de_validation() -> None:
    """Titre, filtres et cartes. Les filtres ne réexécutent que ce fragment et filtrent la file en cache."""
    pending = _file()
    choix_sites = st.session_state.get("filtre_sites") or ()
    choix_verdicts = st.session_state.get("filtre_verdicts") or ()
    affichees = format.filtrer_trier(pending, choix_sites, choix_verdicts)  # par gravité, puis par nc_id
    st.session_state[AFFICHEES] = ([it.run.nc_id for it in affichees], len(pending))
    _titre_file()

    sites, verdicts = format.options_filtres(pending, choix_sites, choix_verdicts)
    f1, f2 = st.columns(2)
    f1.multiselect("Site", sites, key="filtre_sites", placeholder="Tous les sites")
    f2.multiselect("Verdict", verdicts, key="filtre_verdicts", placeholder="Tous les verdicts",
                   format_func=format.libelle_verdict)
    if not pending:
        st.info("Aucune fiche en attente de validation.", icon=":material/inbox:")
    elif not affichees:
        st.info("Aucune fiche ne correspond aux filtres.", icon=":material/filter_alt_off:")
    for item in affichees:
        st.fragment(_carte, key=_cle_carte(item.run.nc_id))(item)


st.title("Boîte de réception")
with st.container():  # emplacement fixe : un message ne décale jamais les éléments suivants de la page
    _messages()
_compteurs()

# Drapeau posé par le clic et consommé ici : le bouton reste désactivé pendant toute l'analyse, puis se réactive
# au rendu suivant, même si l'analyse est interrompue (pas de remise à zéro qui pourrait être sautée).
en_cours = st.session_state.pop("analyse_en_cours", False)
st.button("Analyser les nouvelles fiches", key="analyser", type="primary", icon=":material/play_arrow:",
          disabled=en_cours, on_click=_demander_analyse)
if en_cours:
    try:
        _analyser()
    except Exception as e:
        _flash_inattendue(e, format.ACTION_ERREUR_ANALYSE)
    deps.invalider()
    st.rerun()  # une seule réexécution, à la fin de l'analyse : compteurs, file et erreurs relus

with st.container():  # emplacement fixe, rempli après la première analyse
    recap = st.session_state.get("recap")
    if recap is not None:
        with st.container(border=True):
            st.markdown(f"**Dernière analyse** : {format.recap_text(recap)}")
            if recap:
                st.dataframe(format.recap_rows(recap), hide_index=True, width="stretch")

_file_de_validation()

erreurs = _erreurs()
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
