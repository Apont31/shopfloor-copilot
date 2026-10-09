"""Évaluation du retrieval avec le vrai Ollama (nomic-embed-text). Lancé à la main : pytest -m llm."""

from pathlib import Path

import pytest
import yaml

from shopfloor.rag.embeddings import OllamaEmbedder
from shopfloor.rag.ingest import ingest
from shopfloor.rag.retriever import retrieve_similar

pytestmark = pytest.mark.llm

ROOT = Path(__file__).resolve().parents[1]
CASES = yaml.safe_load((ROOT / "data" / "eval" / "retrieval_cases.yaml").read_text(encoding="utf-8"))["cases"]


@pytest.fixture(scope="module")
def index(tmp_path_factory):
    chroma_dir = tmp_path_factory.mktemp("chroma")
    embedder = OllamaEmbedder()
    n = ingest(embedder, ROOT / "data" / "docs", chroma_dir)
    return embedder, chroma_dir, n


def top3(index, query):
    embedder, chroma_dir, _ = index
    return [r.doc_id for r in retrieve_similar(query, k=3, embedder=embedder, chroma_dir=chroma_dir)]


@pytest.mark.parametrize("case", CASES, ids=[c["expected_doc_id"] for c in CASES])
def test_doc_attendu_dans_le_top3(index, case):
    got = top3(index, case["query"])
    assert case["expected_doc_id"] in got, f"{case['query']!r} -> top 3 obtenu : {got}"


def test_rapport_hit_at_k(index, capsys):
    rows = [(c, top3(index, c["query"])) for c in CASES]
    hit1 = sum(got[0] == c["expected_doc_id"] for c, got in rows)
    hit3 = sum(c["expected_doc_id"] in got for c, got in rows)
    with capsys.disabled():
        print(f"\n--- Retrieval ({index[2]} chunks) ---")
        for c, got in rows:
            print(f"  {c['expected_doc_id']:<13} <- {c['query']!r} : top 3 = {got}")
        print(f"  hit@1 = {hit1}/{len(rows)}   hit@3 = {hit3}/{len(rows)}")
    assert hit3 == len(rows)
