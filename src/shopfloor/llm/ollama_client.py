"""Client LLM réel : Ollama en local, sortie structurée par schéma JSON. Toute erreur devient LLMError."""

import ollama

from shopfloor.config import Settings
from shopfloor.errors import OLLAMA_INJOIGNABLE
from shopfloor.llm.client import LLMError, LLMUnavailableError

TIMEOUT_S = 120.0
# Réglages déterministes : même prompt -> même sortie autant que le modèle le permet.
OPTIONS = {"temperature": 0, "seed": 42, "num_ctx": 4096}


class OllamaLLM:
    """Implémente LLMClient. Le modèle et l'hôte viennent de Settings."""

    def __init__(self, settings: Settings | None = None, *, timeout: float = TIMEOUT_S, client=None):
        settings = settings or Settings()
        self.model = settings.llm_model
        self.client = client if client is not None else ollama.Client(host=settings.ollama_host, timeout=timeout)

    def complete_json(self, system: str, user: str, json_schema: dict) -> str:
        try:
            resp = self.client.chat(
                model=self.model,
                messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
                format=json_schema,
                options=OPTIONS,
            )
            content = resp["message"]["content"]
        except OLLAMA_INJOIGNABLE as e:
            raise LLMUnavailableError() from e
        except Exception as e:  # connexion, timeout, modèle absent, réponse malformée…
            raise LLMError(f"{type(e).__name__}: {e}") from e
        if not isinstance(content, str) or not content.strip():
            raise LLMError("réponse vide du LLM")
        return content
