"""Page « Tickets ERP » : tickets créés dans la fausse API ERP (GET /tickets)."""

import streamlit as st

from shopfloor.erp.client import ErpError
from shopfloor.errors import ERP_INDISPONIBLE
from shopfloor.ui import deps
from shopfloor.ui.format import ticket_rows

erp = deps.get_erp_client()

st.title("Tickets ERP")
st.caption(f"Fausse API ERP : {erp.base_url}")

try:
    tickets = erp.list_tickets()
except ErpError as e:
    st.error(f"{ERP_INDISPONIBLE}. Les tickets ne peuvent pas être lus.", icon=":material/cloud_off:")
    st.caption(f"Détail : {e}")
    st.stop()

st.metric("Tickets ouverts", sum(t.statut == "OUVERT" for t in tickets))
if not tickets:
    st.info("Aucun ticket : approuvez ou modifiez une fiche depuis la boîte de réception.",
            icon=":material/confirmation_number:")
else:
    st.dataframe(ticket_rows(tickets), hide_index=True, width="stretch")
    st.caption("Règles : empreinte abrégée des tolérances appliquées par l'oracle (rules_hash).")
