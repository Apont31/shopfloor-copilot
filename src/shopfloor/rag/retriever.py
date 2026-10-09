"""Recherche de passages similaires dans la collection ChromaDB."""

from collections.abc import Callable
from pathlib import Path

from pydantic import BaseModel, ConfigDict

from shopfloor.rag.embeddings import Embedder, OllamaEmbedder
from shopfloor.rag.ingest import COLLECTION, get_client


class RetrievedChunk(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    doc_id: str
    type: str
    domaine: str
    section: str
    text: str
    score: float  # similarité cosinus (1 - distance) : plus haut = plus proche


def retrieve_similar(
    query: str,
    k: int = 4,
    where: dict | None = None,
    *,
    embedder: Embedder | None = None,
    chroma_dir: str | Path | None = None,
) -> list[RetrievedChunk]:
    if k < 1:
        raise ValueError("k doit être >= 1")
    embedder = embedder or OllamaEmbedder()
    collection = get_client(chroma_dir).get_collection(COLLECTION, embedding_function=None)
    res = collection.query(
        query_embeddings=[embedder.embed_query(query)],
        n_results=k,
        where=where or None,
        include=["documents", "metadatas", "distances"],
    )
    return [
        RetrievedChunk(
            doc_id=meta["doc_id"],
            type=meta["type"],
            domaine=meta["domaine"],
            section=meta["section"],
            text=doc,
            score=1.0 - dist,
        )
        for doc, meta, dist in zip(res["documents"][0], res["metadatas"][0], res["distances"][0])
    ]


def make_retriever(
    chroma_dir: str | Path, embedder: Embedder, k: int = 8
) -> Callable[[str, dict | None], list[RetrievedChunk]]:
    """Retriever de production pour l'agent : (query, where) -> passages. Les erreurs remontent à l'appelant."""
    if k < 1:
        raise ValueError("k doit être >= 1")

    def retriever(query: str, where: dict | None) -> list[RetrievedChunk]:
        return retrieve_similar(query, k=k, where=where, embedder=embedder, chroma_dir=chroma_dir)

    return retriever
