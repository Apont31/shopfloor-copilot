"""Messages d'erreur destinés à l'opérateur : chacun dit quoi faire."""

import httpx

OLLAMA_INDISPONIBLE = "Ollama indisponible : lancez l'application Ollama"
RAG_INDISPONIBLE = "Index RAG indisponible : lancez python -m shopfloor.cli ingest"


class OllamaUnavailableError(Exception):
    """Serveur Ollama injoignable (embedder ou LLM). Le message est OLLAMA_INDISPONIBLE."""

    def __init__(self, message: str = OLLAMA_INDISPONIBLE):
        super().__init__(message)


# Exceptions du client ollama quand le serveur ne répond pas (connexion refusée ou impossible).
OLLAMA_INJOIGNABLE = (ConnectionError, httpx.ConnectError, httpx.ConnectTimeout)
