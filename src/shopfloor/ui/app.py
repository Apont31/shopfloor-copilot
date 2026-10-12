"""Interface ShopFloor Copilot (Streamlit, 100 % local).

Lancement depuis la racine du dépôt : python -m streamlit run src/shopfloor/ui/app.py
L'interface ne décide de rien : elle appelle le Service (shopfloor.service) et des fonctions pures.
"""

import logging

import streamlit as st

from shopfloor.ui import deps, format, style

st.set_page_config(page_title="ShopFloor Copilot", page_icon=":material/precision_manufacturing:", layout="wide")
style.inject()

pages = [
    st.Page("views/inbox.py", title="Boîte de réception", icon=":material/inbox:", default=True),
    st.Page("views/pilotage.py", title="Pilotage", icon=":material/monitoring:"),
    st.Page("views/tickets.py", title="Tickets ERP", icon=":material/confirmation_number:"),
    st.Page("views/assistant.py", title="Assistant procédures", icon=":material/menu_book:"),
]
page = st.navigation(pages)

with st.sidebar:
    st.markdown("### ShopFloor Copilot")
    st.caption("Analyse des non-conformités : l'oracle tranche, le LLM rédige, vous validez.")
    st.text_input("Valideur", key="valideur", placeholder="Nom du valideur")

    st.markdown(style.label_html("État des services"), unsafe_allow_html=True)
    forcer = st.button("Revérifier", key="reverifier", icon=":material/refresh:", type="tertiary")
    for v in deps.get_voyants(force=forcer):
        st.markdown(style.voyant_html(v.nom, v.ok, v.message), unsafe_allow_html=True)

    st.divider()
    st.markdown(style.bandeau_html("Données fictives — 100 % local"), unsafe_allow_html=True)

try:
    page.run()
except Exception as e:  # filet de sécurité, jamais de trace à l'écran (st.stop et st.rerun ne sont pas des Exception)
    logging.getLogger(__name__).error("Erreur inattendue dans la page %s", page.title, exc_info=e)
    style.erreur(*format.erreur_inattendue(e))
