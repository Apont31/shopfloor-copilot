"""Page « Tickets ERP » : tickets créés dans la fausse API ERP (GET /tickets).

Liste gardée TICKETS_TTL_S secondes dans la session, relue aussitôt après une décision prise dans la session.
"""

import streamlit as st

from shopfloor.erp.client import ErpError
from shopfloor.errors import ERP_INDISPONIBLE
from shopfloor.ui import deps
from shopfloor.ui.format import LARGEURS_TICKETS, ticket_rows

TICKETS_TTL_S = 10.0  # tickets créés par une autre session : visibles au plus tard après ce délai
erp = deps.get_erp_client()

st.title("Tickets ERP")
st.caption(f"Fausse API ERP : {erp.base_url}")

try:
    tickets = deps.memo("_tickets", erp.list_tickets, ttl=TICKETS_TTL_S)
except ErpError as e:
    st.error(f"{ERP_INDISPONIBLE}. Les tickets ne peuvent pas être lus.", icon=":material/cloud_off:")
    st.caption(f"Détail : {e}")
    st.stop()

st.metric("Tickets ouverts", sum(t.statut == "OUVERT" for t in tickets))
if not tickets:
    st.info("Aucun ticket : approuvez ou modifiez une fiche depuis la boîte de réception.",
            icon=":material/confirmation_number:")
else:
    colonnes = {nom: st.column_config.TextColumn(nom, width=px) for nom, px in LARGEURS_TICKETS.items()}
    st.dataframe(ticket_rows(tickets), hide_index=True, width="stretch", column_config=colonnes)
    st.caption("Règles : empreinte abrégée des tolérances appliquées par l'oracle (rules_hash).")
