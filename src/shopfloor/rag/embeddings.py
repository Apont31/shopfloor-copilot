"""Fonctions d'embedding injectables : Ollama en production, faux embedder déterministe en test."""

import hashlib
import math
import re
from typing import Protocol

import ollama

from shopfloor.config import Settings


class Embedder(Protocol):
    def embed_documents(self, texts: list[str]) -> list[list[float]]: ...

    def embed_query(self, text: str) -> list[float]: ...


class OllamaEmbedder:
    """nomic-embed-text via Ollama, avec les préfixes de tâche imposés par le modèle."""

    DOC_PREFIX = "search_document: "
    QUERY_PREFIX = "search_query: "

    def __init__(self, settings: Settings | None = None):
        settings = settings or Settings()
        self.model = settings.embed_model
        self.client = ollama.Client(host=settings.ollama_host)

    def _embed(self, texts: list[str]) -> list[list[float]]:
        return [list(e) for e in self.client.embed(model=self.model, input=texts)["embeddings"]]

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return self._embed([self.DOC_PREFIX + t for t in texts])

    def embed_query(self, text: str) -> list[float]:
        return self._embed([self.QUERY_PREFIX + text])[0]


class FakeEmbedder:
    """Réservé aux tests : sac de mots haché (sha256), normalisé. Déterministe, sans réseau."""

    def __init__(self, dim: int = 256):
        self.dim = dim

    def _vector(self, text: str) -> list[float]:
        v = [0.0] * self.dim
        for token in re.findall(r"\w+", text.lower()):
            h = int.from_bytes(hashlib.sha256(token.encode("utf-8")).digest()[:8], "big")
            v[h % self.dim] += 1.0
        norm = math.sqrt(sum(x * x for x in v)) or 1.0
        return [x / norm for x in v] if any(v) else [1.0 / math.sqrt(self.dim)] * self.dim

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [self._vector(t) for t in texts]

    def embed_query(self, text: str) -> list[float]:
        return self._vector(text)
