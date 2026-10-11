# Image unique ShopFloor Copilot : serveur ERP (uvicorn) ou interface (streamlit) selon la commande.
# Ollama reste sur l'hôte : l'image ne contient ni modèle ni GPU.
FROM python:3.12-slim

LABEL org.opencontainers.image.title="shopfloor-copilot" \
      org.opencontainers.image.description="Copilote IA 100 % local pour atelier industriel (données fictives)" \
      org.opencontainers.image.source="https://github.com/Apont31/shopfloor-copilot" \
      org.opencontainers.image.licenses="MIT"

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# Dépendances figées d'abord : cette couche reste en cache tant que requirements.lock ne change pas.
COPY requirements.lock .
RUN pip install -r requirements.lock

# Installation éditable : le code calcule ses chemins (config/, data/) depuis src/, il doit rester dans /app.
COPY pyproject.toml LICENSE ./
COPY src ./src
COPY config ./config
COPY data ./data
COPY .streamlit ./.streamlit
RUN pip install --no-deps -e .

# Utilisateur non root. Les dossiers des bases et de l'index lui appartiennent :
# un volume nommé vide reprend ces droits au premier montage.
RUN useradd --create-home --uid 1000 shopfloor \
    && mkdir -p /var/lib/shopfloor/erp /var/lib/shopfloor/bases /var/lib/shopfloor/chroma \
    && chown -R shopfloor:shopfloor /var/lib/shopfloor
USER shopfloor

ENV ERP_DB=/var/lib/shopfloor/erp/erp.db \
    JOURNAL_DB=/var/lib/shopfloor/bases/shopfloor_journal.db \
    STATE_DB=/var/lib/shopfloor/bases/shopfloor_state.db \
    CHROMA_DIR=/var/lib/shopfloor/chroma

EXPOSE 8000 8501

# Par défaut : le serveur ERP. L'interface : streamlit run src/shopfloor/ui/app.py (voir docker-compose.yml).
CMD ["uvicorn", "shopfloor.erp.api:app", "--host", "0.0.0.0", "--port", "8000"]
