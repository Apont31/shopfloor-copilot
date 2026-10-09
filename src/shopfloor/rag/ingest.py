"""Ingestion du corpus data/docs/ dans ChromaDB : découpage par section ##, embeddings fournis par nous."""

import re
from dataclasses import dataclass
from pathlib import Path

import chromadb
from chromadb.config import Settings as ChromaSettings
from chromadb.errors import NotFoundError

from shopfloor.config import Settings
from shopfloor.corpus import read_document
from shopfloor.rag.embeddings import Embedder

COLLECTION = "shopfloor_docs"
DOCS_DIR = Path(__file__).resolve().parents[3] / "data" / "docs"
PREAMBLE_SECTION = "Présentation"


@dataclass(frozen=True)
class Chunk:
    id: str
    text: str
    metadata: dict[str, str]


def get_client(chroma_dir: str | Path | None = None) -> chromadb.ClientAPI:
    path = chroma_dir if chroma_dir is not None else Settings().chroma_dir
    return chromadb.PersistentClient(path=str(path), settings=ChromaSettings(anonymized_telemetry=False))


def split_sections(body: str) -> tuple[str, list[tuple[str, str]]]:
    """Renvoie (titre # du document, [(section ##, contenu)]).

    Le contenu placé entre le titre et la première section (ex. tableau d'une gamme) devient la
    section « Présentation ».
    """
    title = ""
    sections: list[tuple[str, list[str]]] = [(PREAMBLE_SECTION, [])]
    for line in body.replace("\r\n", "\n").split("\n"):
        if m := re.match(r"^#\s+(.+)$", line):
            title = m.group(1).strip()
        elif m := re.match(r"^##\s+(.+)$", line):
            sections.append((m.group(1).strip(), []))
        else:
            sections[-1][1].append(line)
    out = [(name, "\n".join(lines).strip()) for name, lines in sections]
    return title, [(name, content) for name, content in out if content]


def chunk_document(path: str | Path) -> list[Chunk]:
    meta, body = read_document(path)
    doc_id = meta["doc_id"]
    title, sections = split_sections(body)
    # Le titre contient déjà « doc_id — … » : on ne garde que la partie descriptive.
    label = title.split("—", 1)[1].strip() if "—" in title else title
    chunks = []
    for i, (section, content) in enumerate(sections):
        chunks.append(
            Chunk(
                id=f"{doc_id}#{i:02d}",
                text=f"[{doc_id}] {label} — {section}\n{content}",
                metadata={
                    "doc_id": doc_id,
                    "type": meta["type"],
                    "domaine": meta["domaine"],
                    # Chroma refuse None : document transverse sans pièce -> chaîne vide.
                    "part_ref": meta.get("part_ref") or "",
                    "section": section,
                },
            )
        )
    return chunks


def ingest(
    embedder: Embedder,
    docs_dir: str | Path = DOCS_DIR,
    chroma_dir: str | Path | None = None,
) -> int:
    """Recrée la collection et indexe tous les documents. Renvoie le nombre de chunks.

    Les embeddings sont calculés avant de toucher à la collection : si l'embedder échoue
    (Ollama indisponible…), l'exception remonte et l'index existant reste intact.
    """
    chunks = [c for p in sorted(Path(docs_dir).glob("*.md")) for c in chunk_document(p)]
    if not chunks:
        raise ValueError(f"aucun document dans {docs_dir}")
    embeddings = embedder.embed_documents([c.text for c in chunks])
    client = get_client(chroma_dir)
    try:
        client.delete_collection(COLLECTION)
    except NotFoundError:
        pass
    collection = client.create_collection(
        COLLECTION,
        embedding_function=None,
        configuration={"hnsw": {"space": "cosine"}},
    )
    collection.add(
        ids=[c.id for c in chunks],
        documents=[c.text for c in chunks],
        metadatas=[c.metadata for c in chunks],
        embeddings=embeddings,
    )
    return len(chunks)
