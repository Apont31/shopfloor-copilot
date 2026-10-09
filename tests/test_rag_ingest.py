from pathlib import Path

import pytest
from chromadb.api.types import DefaultEmbeddingFunction
from pydantic import ValidationError

from shopfloor import cli
from shopfloor.corpus import read_document
from shopfloor.errors import OllamaUnavailableError
from shopfloor.rag.embeddings import FakeEmbedder
from shopfloor.rag.ingest import COLLECTION, chunk_document, get_client, ingest, split_sections
from shopfloor.rag.retriever import RetrievedChunk, make_retriever, retrieve_similar

ROOT = Path(__file__).resolve().parents[1]
DOCS = ROOT / "data" / "docs"
DOC_IDS = {read_document(p)[0]["doc_id"] for p in DOCS.glob("*.md")}
META_KEYS = {"doc_id", "type", "domaine", "part_ref", "section"}


@pytest.fixture(autouse=True)
def no_default_embedding_function(monkeypatch):
    """Si Chroma tentait d'utiliser son modèle par défaut (téléchargement ONNX), le test échoue."""

    def boom(self, input):
        raise AssertionError("embedding_function par défaut de Chroma utilisée")

    monkeypatch.setattr(DefaultEmbeddingFunction, "__call__", boom)


@pytest.fixture
def chroma_dir(tmp_path):
    return tmp_path / "chroma"


@pytest.fixture
def indexed(chroma_dir):
    n = ingest(FakeEmbedder(), DOCS, chroma_dir)
    return n, get_client(chroma_dir).get_collection(COLLECTION, embedding_function=None)


def search(chroma_dir, query, **kwargs):
    return retrieve_similar(query, embedder=FakeEmbedder(), chroma_dir=chroma_dir, **kwargs)


# --- Découpage -----------------------------------------------------------------


def test_split_sections_preambule_et_sections():
    title, sections = split_sections("# DOC-1 — Titre\n\n| a |\n\n## Objet\nTexte.\n\n## Vide\n\n## Fin\nOK\n")
    assert title == "DOC-1 — Titre"
    assert sections == [("Présentation", "| a |"), ("Objet", "Texte."), ("Fin", "OK")]


def test_chunk_prefixe_par_doc_id_titre_et_section():
    chunks = chunk_document(DOCS / "NC-2025-014.md")
    assert [c.metadata["section"] for c in chunks] == [
        "Description", "Cause racine", "Action corrective", "Décision", "Statut",
    ]
    assert chunks[0].text.startswith(
        "[NC-2025-014] Porosité excessive sur panneau carbone CP-210 — Description\n"
    )


def test_gamme_garde_son_tableau_dans_la_section_presentation():
    chunks = chunk_document(DOCS / "GAMME-SE450.md")
    assert chunks[0].metadata["section"] == "Présentation"
    assert "| 40 | Presse-plieuse |" in chunks[0].text


def test_document_transverse_part_ref_vide():
    chunks = chunk_document(DOCS / "PROC-QUA-01.md")
    assert {c.metadata["part_ref"] for c in chunks} == {""}


# --- Ingestion -----------------------------------------------------------------


def test_dix_doc_ids_indexes_metadonnees_completes(indexed):
    n, col = indexed
    got = col.get(include=["metadatas", "documents"])
    assert len(got["ids"]) == n
    assert len(DOC_IDS) == 10
    assert {m["doc_id"] for m in got["metadatas"]} == DOC_IDS
    for meta, doc in zip(got["metadatas"], got["documents"]):
        assert set(meta) == META_KEYS
        assert all(isinstance(v, str) for v in meta.values())
        assert all(meta[k] for k in META_KEYS - {"part_ref"}), meta
        assert doc.startswith(f"[{meta['doc_id']}] ")
        assert f" — {meta['section']}\n" in doc.split("\n", 1)[0] + "\n"


def test_deux_ingestions_meme_nombre_de_chunks(chroma_dir):
    n1 = ingest(FakeEmbedder(), DOCS, chroma_dir)
    n2 = ingest(FakeEmbedder(), DOCS, chroma_dir)
    col = get_client(chroma_dir).get_collection(COLLECTION, embedding_function=None)
    assert n1 == n2 == col.count()


def test_collection_cosinus_sans_embedding_function(indexed):
    _, col = indexed
    assert col.configuration["hnsw"]["space"] == "cosine"
    assert col.configuration["embedding_function"] is None
    assert col._embedding_function is None


def test_collection_refuse_les_textes_sans_embeddings(indexed):
    # Preuve qu'aucun modèle n'est branché : une requête texte brute est refusée.
    _, col = indexed
    with pytest.raises(ValueError, match="embedding function"):
        col.query(query_texts=["porosité"])


def test_dossier_vide_refuse(tmp_path):
    with pytest.raises(ValueError, match="aucun document"):
        ingest(FakeEmbedder(), tmp_path, tmp_path / "chroma")


# --- Retrieval (FakeEmbedder) ----------------------------------------------------


def test_filtre_where_domaine(indexed, chroma_dir):
    res = search(chroma_dir, "contrôle épaisseur tolérance", k=20, where={"domaine": "composite"})
    assert res
    assert {r.domaine for r in res} == {"composite"}
    assert {r.doc_id for r in res} == {"GAMME-CP210", "NC-2025-014", "PROC-COMP-01"}


def test_filtre_where_type(indexed, chroma_dir):
    res = search(chroma_dir, "non-conformité", k=20, where={"type": "nc_historique"})
    assert {r.doc_id for r in res} == {"NC-2025-014", "NC-2025-031", "NC-2025-052"}


def test_k_et_tri_par_score(indexed, chroma_dir):
    res = search(chroma_dir, "porosité panneau carbone", k=3)
    assert len(res) == 3
    assert [r.score for r in res] == sorted((r.score for r in res), reverse=True)
    assert all(-1.0 <= r.score <= 1.0 + 1e-6 for r in res)


def test_k_invalide(indexed, chroma_dir):
    with pytest.raises(ValueError):
        search(chroma_dir, "x", k=0)


def test_retrieval_deterministe(indexed, chroma_dir):
    assert search(chroma_dir, "angle de pli") == search(chroma_dir, "angle de pli")


def test_retrieved_chunk_immuable(indexed, chroma_dir):
    r = search(chroma_dir, "peinture", k=1)[0]
    assert isinstance(r, RetrievedChunk)
    with pytest.raises(ValidationError):
        r.score = 0.0


# --- make_retriever -----------------------------------------------------------------


def test_make_retriever_filtre_in_et_k(indexed, chroma_dir):
    retriever = make_retriever(chroma_dir, FakeEmbedder())
    results = retriever("porosité vide bâche", {"domaine": {"$in": ["composite", "qualite"]}})
    assert len(results) == 8
    assert {r.domaine for r in results} <= {"composite", "qualite"}
    assert results == retriever("porosité vide bâche", {"domaine": {"$in": ["composite", "qualite"]}})
    assert len(make_retriever(chroma_dir, FakeEmbedder(), k=2)("porosité", None)) == 2


def test_make_retriever_k_invalide(chroma_dir):
    with pytest.raises(ValueError):
        make_retriever(chroma_dir, FakeEmbedder(), k=0)


def test_make_retriever_index_absent_leve(tmp_path):
    retriever = make_retriever(tmp_path / "vide", FakeEmbedder())
    with pytest.raises(Exception):
        retriever("porosité", None)


# --- FakeEmbedder ----------------------------------------------------------------


def test_fake_embedder_deterministe_et_normalise():
    e = FakeEmbedder()
    v1, v2 = e.embed_query("Porosité élevée"), e.embed_query("Porosité élevée")
    assert v1 == v2 and len(v1) == 256
    assert abs(sum(x * x for x in v1) - 1.0) < 1e-9
    assert e.embed_documents(["a", "b"]) == [e.embed_query("a"), e.embed_query("b")]
    assert len(e.embed_query("")) == 256


# --- CLI ---------------------------------------------------------------------


def test_cli_ingest_puis_search(chroma_dir, monkeypatch, capsys):
    monkeypatch.setenv("CHROMA_DIR", str(chroma_dir))
    assert cli.main(["ingest"], embedder=FakeEmbedder()) == 0
    assert "chunks indexés" in capsys.readouterr().out
    assert cli.main(["search", "porosité panneau", "--k", "2", "--domaine", "composite"], embedder=FakeEmbedder()) == 0
    lines = capsys.readouterr().out.strip().splitlines()
    assert len(lines) == 2
    assert all("score=" in line for line in lines)
    assert all(any(d in line for d in ("GAMME-CP210", "NC-2025-014", "PROC-COMP-01")) for line in lines)


def test_cli_domaine_invalide(capsys):
    with pytest.raises(SystemExit):
        cli.main(["search", "x", "--domaine", "bois"], embedder=FakeEmbedder())


# --- Étape 8a : ingest robuste ----------------------------------------------------------------------


class EmbedderEnPanne:
    """Embedder qui échoue comme un Ollama arrêté."""

    def embed_documents(self, texts):
        raise OllamaUnavailableError()

    def embed_query(self, text):
        raise OllamaUnavailableError()


def test_embedder_en_echec_index_precedent_intact(indexed, chroma_dir):
    n, _ = indexed
    avant = search(chroma_dir, "porosité vide bâche", k=3)
    with pytest.raises(OllamaUnavailableError):
        ingest(EmbedderEnPanne(), DOCS, chroma_dir)
    collection = get_client(chroma_dir).get_collection(COLLECTION, embedding_function=None)
    assert collection.count() == n
    assert search(chroma_dir, "porosité vide bâche", k=3) == avant


def test_cli_ingest_embedder_en_echec_message_et_index_intact(indexed, chroma_dir, monkeypatch, capsys):
    n, _ = indexed
    monkeypatch.setenv("CHROMA_DIR", str(chroma_dir))
    assert cli.main(["ingest"], embedder=EmbedderEnPanne()) == 1
    assert "ERREUR : Ollama indisponible : lancez l'application Ollama" in capsys.readouterr().out
    assert get_client(chroma_dir).get_collection(COLLECTION, embedding_function=None).count() == n
