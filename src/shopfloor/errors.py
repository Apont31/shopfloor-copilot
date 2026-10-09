"""Messages d'erreur destinés à l'opérateur : chacun dit quoi faire."""

import httpx

OLLAMA_INDISPONIBLE = "Ollama indisponible : lancez l'application Ollama"
RAG_INDISPONIBLE = "Index RAG indisponible : lancez python -m shopfloor.cli ingest"
ERP_INDISPONIBLE = "ERP indisponible : lancez le serveur ERP"
# Début du message d'une fiche déjà portée par un ticket : « Ticket déjà existant pour NC-2026-101 : TCK-0001 ».
# Écrit par le nœud check_existing, reconnu par la couche service (statut doublon).
TICKET_EXISTANT = "Ticket déjà existant pour"


class OllamaUnavailableError(Exception):
    """Serveur Ollama injoignable (embedder ou LLM). Le message est OLLAMA_INDISPONIBLE."""

    def __init__(self, message: str = OLLAMA_INDISPONIBLE):
        super().__init__(message)


# Exceptions du client ollama quand le serveur ne répond pas (connexion refusée ou impossible).
OLLAMA_INJOIGNABLE = (ConnectionError, httpx.ConnectError, httpx.ConnectTimeout)
