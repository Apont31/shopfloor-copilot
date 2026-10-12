"""Page « Assistant procédures » : questions-réponses sur les procédures, gammes et anciennes NC, avec sources.

Tolérances lues dans le référentiel (sans LLM) ; autres questions : réponse du LLM fondée sur les passages retrouvés
et vérifiée par le garde-fou de l'assistant (shopfloor.assistant). Historique gardé dans la session.
Tout texte (question, réponse, sources, passages) est affiché via texte_brut.
"""

import streamlit as st

from shopfloor.assistant import Answer, AssistantError, answer
from shopfloor.ui import deps, format, style
from shopfloor.ui.format import texte_brut as brut

HISTORIQUE = "assistant_historique"
A_POSER = "assistant_exemple"
EXEMPLES = (
    "Quelle est la porosité maximale du CP-210 ?",
    "Que faut-il vérifier avant de lancer une cuisson autoclave ?",
    "Que faire au changement de lot matière sur la presse-plieuse ?",
)


def _poser(question: str) -> None:
    st.session_state[A_POSER] = question


def _effacer() -> None:
    st.session_state[HISTORIQUE] = []


def _reponse(rep: Answer) -> None:
    st.badge(f"Origine : {format.LIBELLES_ORIGINE_ASSISTANT[rep.origine]}",
             color=style.BADGE_ORIGINE_ASSISTANT[rep.origine])
    if rep.refus:
        st.info(brut(rep.texte), icon=":material/search_off:")
    elif rep.origine == "passages":
        st.warning(brut(rep.texte), icon=":material/shield:")
    else:
        st.markdown(brut(rep.texte))
    if rep.origine == "referentiel":
        st.caption("Lu dans le référentiel de tolérances, sans LLM.")
    if rep.motifs:
        st.caption(brut("Réponse du LLM écartée : " + " ; ".join(rep.motifs)))
    if rep.sources:
        st.markdown("**Sources**\n\n" + "\n".join(f"- {brut(s.doc_id)} · {brut(s.section)}" for s in rep.sources))
    if rep.passages:
        with st.expander(f"Passages ({len(rep.passages)})"):
            for c in rep.passages:
                st.markdown(f"**{brut(c.doc_id)}** · {brut(c.section)} · score {c.score:.2f}")
                st.markdown(brut(c.text))


st.title("Assistant procédures")
st.caption("Questions sur les procédures, gammes et anciennes NC. Les tolérances sont lues dans le référentiel ; "
           "les autres réponses sont rédigées par le LLM à partir des documents, toujours avec leurs sources.")

historique: list[dict] = st.session_state.setdefault(HISTORIQUE, [])

colonnes = st.columns(len(EXEMPLES) + 1)
for i, (col, exemple) in enumerate(zip(colonnes, EXEMPLES)):
    col.button(exemple, key=f"exemple_{i}", type="tertiary", on_click=_poser, args=(exemple,))
colonnes[-1].button("Effacer", key="effacer_assistant", icon=":material/delete_sweep:", disabled=not historique,
                    on_click=_effacer)

for entree in historique:
    with st.chat_message("user"):
        st.markdown(brut(entree["question"]))
    with st.chat_message("assistant"):
        _reponse(entree["reponse"])

saisie = st.chat_input("Votre question sur les procédures, gammes ou anciennes NC", key="question_assistant")
question = (saisie or st.session_state.pop(A_POSER, None) or "").strip()
if question:
    with st.chat_message("user"):
        st.markdown(brut(question))
    with st.chat_message("assistant"):
        try:
            with st.spinner("Recherche dans les documents…"):
                rep = answer(question, deps.get_assistant())
        except AssistantError as e:
            style.erreur(str(e))
        else:
            historique.append({"question": question, "reponse": rep})
            st.rerun()  # réponse affichée depuis l'historique, bouton « Effacer » actif
