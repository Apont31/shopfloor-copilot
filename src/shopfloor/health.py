"""Sondes d'état des services locaux (voyants de l'interface) : Ollama, ERP, index RAG.

Chaque sonde renvoie un Voyant et ne lève jamais : un service absent donne un voyant rouge avec l'action à mener.
Aucune sonde ne crée de fichier : l'index RAG n'est ouvert que si son dossier existe.
"""

from dataclasses import dataclass
from pathlib import Path

import ollama

from shopfloor.config import Settings
from shopfloor.erp.client import ErpClient, ErpError
from shopfloor.errors import ERP_INDISPONIBLE, OLLAMA_INDISPONIBLE, RAG_INDISPONIBLE
from shopfloor.rag.ingest import COLLECTION, get_client

TIMEOUT_S = 2.0


@dataclass(frozen=True)
class Voyant:
    nom: str
    ok: bool
    message: str


def _ollama_list(host: str, timeout: float) -> None:
    ollama.Client(host=host, timeout=timeout).list()


def check_ollama(host: str, timeout: float = TIMEOUT_S) -> Voyant:
    try:
        _ollama_list(host, timeout)
    except Exception:
        return Voyant("Ollama", False, OLLAMA_INDISPONIBLE)
    return Voyant("Ollama", True, "Ollama répond")


def check_erp(erp: ErpClient) -> Voyant:
    try:
        erp.health()
    except ErpError:
        return Voyant("ERP", False, ERP_INDISPONIBLE)
    return Voyant("ERP", True, "ERP répond")


def check_rag(chroma_dir: str | Path) -> Voyant:
    absent = Voyant("Index RAG", False, RAG_INDISPONIBLE)
    if not Path(chroma_dir).is_dir():
        return absent
    try:
        n = get_client(chroma_dir).get_collection(COLLECTION, embedding_function=None).count()
    except Exception:
        return absent
    return Voyant("Index RAG", True, f"{n} passages indexés") if n else absent


def check_all(settings: Settings, erp: ErpClient) -> list[Voyant]:
    return [check_ollama(settings.ollama_host), check_erp(erp), check_rag(settings.chroma_dir)]
