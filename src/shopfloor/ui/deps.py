"""Dépendances de l'interface : réglages, client ERP, service, boîte de réception, voyants, cache des données.

Une seule instance par processus Streamlit (st.cache_resource), partagée par toutes les sessions.
Les tests les remplacent par override(service=..., erp=..., settings=..., inbox_dir=...) avant AppTest.run().
"""

import time
from collections.abc import Callable, Hashable
from pathlib import Path
from typing import TypeVar

import streamlit as st

from shopfloor import health
from shopfloor.agent.graph import Deps
from shopfloor.cli import INBOX_DIR, TOLERANCES_PATH
from shopfloor.config import Settings
from shopfloor.erp.client import ErpClient
from shopfloor.llm.ollama_client import OllamaLLM
from shopfloor.oracle.loader import load_tolerances
from shopfloor.rag.embeddings import OllamaEmbedder
from shopfloor.rag.retriever import make_retriever
from shopfloor.service import Service

VOYANTS_TTL_S = 30.0  # les sondes ne sont pas rejouées à chaque clic ; « Revérifier » vide ce cache
VERSION = "_version_donnees"
_overrides: dict[str, object] = {}
T = TypeVar("T")


def override(**deps) -> None:
    """Remplace service, erp, settings ou inbox_dir (tests)."""
    inconnues = set(deps) - {"service", "erp", "settings", "inbox_dir"}
    if inconnues:
        raise ValueError(f"dépendance(s) inconnue(s) : {', '.join(sorted(inconnues))}")
    _overrides.update(deps)


def reset_overrides() -> None:
    _overrides.clear()


def get_settings() -> Settings:
    return _overrides.get("settings") or Settings()


def get_inbox_dir() -> Path:
    return Path(_overrides.get("inbox_dir") or INBOX_DIR)


@st.cache_resource(show_spinner=False)
def _erp_client(url: str) -> ErpClient:
    return ErpClient(url)


def get_erp_client() -> ErpClient:
    return _overrides.get("erp") or _erp_client(get_settings().erp_url)


@st.cache_resource(show_spinner=False)
def _service() -> Service:
    settings = Settings()
    deps = Deps(
        tolerances=load_tolerances(TOLERANCES_PATH),
        retriever=make_retriever(settings.chroma_dir, OllamaEmbedder(settings)),
        llm=OllamaLLM(settings),
        erp=_erp_client(settings.erp_url),
    )
    return Service(deps, state_db=settings.state_db, journal_db=settings.journal_db)


def get_service() -> Service:
    return _overrides.get("service") or _service()


def get_voyants(force: bool = False) -> list[health.Voyant]:
    """Voyants Ollama, ERP, index RAG ; gardés VOYANTS_TTL_S secondes dans la session (force : sondes rejouées)."""
    return memo("_voyants", lambda: health.check_all(get_settings(), get_erp_client()), ttl=VOYANTS_TTL_S,
                force=force, versionne=False)


# --- Cache des données de la session --------------------------------------------------------------


def version() -> int:
    return st.session_state.get(VERSION, 0)


def invalider() -> None:
    """Après « Analyser », une décision ou « Relancer » : les données en cache seront relues au prochain rendu."""
    st.session_state[VERSION] = version() + 1


def memo(
    nom: str,
    calcul: Callable[[], T],
    *,
    cle: Hashable = None,
    ttl: float | None = None,
    force: bool = False,
    versionne: bool = True,
) -> T:
    """Valeur gardée dans la session sous nom, recalculée si force, si la version des données a changé
    (versionne), si cle a changé, ou après ttl secondes.

    cle : empreinte bon marché de la source (par exemple Journal.fingerprint()), pour voir aussi les changements
    faits par une autre session ou un autre processus.
    """
    cle = (version() if versionne else None, cle)
    cache = st.session_state.get(nom)
    if force or cache is None or cache[0] != cle or (ttl is not None and time.monotonic() - cache[1] > ttl):
        cache = (cle, time.monotonic(), calcul())
        st.session_state[nom] = cache
    return cache[2]
