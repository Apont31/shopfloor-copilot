"""Sous-commande ask (assistant procédures) : run_ask avec FakeLLM et faux retriever, puis main avec FakeEmbedder."""

from pathlib import Path

import pytest
from fakes import FakeLLM, FakeRetriever
from test_assistant import reponse_json

from shopfloor import cli
from shopfloor.assistant import PAS_FIABLE, REFUS, AssistantDeps
from shopfloor.errors import RAG_INDISPONIBLE
from shopfloor.oracle.loader import load_tolerances
from shopfloor.rag.embeddings import FakeEmbedder
from shopfloor.rag.ingest import ingest

ROOT = Path(__file__).resolve().parents[1]
TOLERANCES = load_tolerances(ROOT / "config" / "tolerances.yaml")


def deps(llm=None, retriever=None) -> AssistantDeps:
    return AssistantDeps(tolerances=TOLERANCES, retriever=retriever or FakeRetriever(), llm=llm)


def test_ask_tolerance(capsys):
    assert cli.run_ask("Porosité max du CP-210 ?", deps(llm=FakeLLM())) == 0
    out = capsys.readouterr().out
    assert "Origine : Référentiel" in out
    assert "  Porosité de la pièce CP-210 : au plus 2.0 % (bornes incluses)." in out
    assert "Sources : PROC-COMP-01 (Tolérances)" in out
    assert "Appel LLM : aucun" in out


def test_ask_llm(capsys):
    assert cli.run_ask("Que s'est-il passé sur la bâche ?", deps(llm=FakeLLM(reponse_json()))) == 0
    out = capsys.readouterr().out
    assert "Origine : LLM" in out and "(refus)" not in out
    assert "  Fuite de bâche à vide" in out
    assert "Sources : NC-2025-014 (Cause racine)" in out
    assert "(1 appel(s))" in out
    assert "Extraits :" not in out


def test_ask_extraits_si_garde_fou(capsys):
    llm = FakeLLM(reponse_json(texte="Chute de vide relevée sur 15 minutes (NC-2025-014)."))
    assert cli.run_ask("Que s'est-il passé sur la bâche ?", deps(llm=llm)) == 0
    out = capsys.readouterr().out
    assert "Origine : Extraits" in out and PAS_FIABLE in out
    assert "Extraits :" in out and "NC-2025-014 (Cause racine) score=0.820" in out
    assert "  - nombre(s) absent(s) des passages : 15" in out


def test_ask_refus(capsys):
    llm = FakeLLM(reponse_json(trouve=False, texte="", sources=[]))
    assert cli.run_ask("Horaires de la cantine ?", deps(llm=llm)) == 0
    out = capsys.readouterr().out
    assert "Origine : LLM (refus)" in out and REFUS in out and "Sources : aucune" in out


def test_ask_index_absent(capsys):
    def en_panne(query, where, k):
        raise RuntimeError("collection absente")

    assert cli.run_ask("Que s'est-il passé sur la bâche ?", deps(llm=FakeLLM(), retriever=en_panne)) == 1
    assert capsys.readouterr().out == f"ERREUR : {RAG_INDISPONIBLE}\n"


@pytest.fixture
def chroma_env(tmp_path, monkeypatch):
    ingest(FakeEmbedder(), ROOT / "data" / "docs", tmp_path)
    monkeypatch.setenv("CHROMA_DIR", str(tmp_path))
    return tmp_path


def test_main_ask_tolerance_sans_llm(chroma_env, capsys, monkeypatch):
    monkeypatch.setattr(cli, "OllamaLLM", lambda settings: FakeLLM())  # un appel ferait échouer le test
    assert cli.main(["ask", "tolérance d'angle de pli SE-450"], embedder=FakeEmbedder()) == 0
    out = capsys.readouterr().out
    assert "Angle de pli de la pièce SE-450 : de 89.5 à 90.5°, nominal 90.0° (bornes incluses)." in out


def test_main_ask_rag(chroma_env, capsys, monkeypatch):
    """Index réel (FakeEmbedder) : le LLM cite un passage effectivement retrouvé."""
    from shopfloor.rag.retriever import retrieve_similar

    question = "test d'étanchéité de la bâche à vide avant cuisson"
    top = retrieve_similar(question, k=1, embedder=FakeEmbedder(), chroma_dir=chroma_env)[0]
    texte = "Le test d'étanchéité de la bâche est obligatoire avant cuisson."
    llm = FakeLLM(reponse_json(texte=texte, sources=[{"doc_id": top.doc_id, "section": top.section}]))
    monkeypatch.setattr(cli, "OllamaLLM", lambda settings: llm)
    assert cli.main(["ask", question], embedder=FakeEmbedder()) == 0
    out = capsys.readouterr().out
    assert "Origine : LLM" in out and f"Sources : {top.doc_id} ({top.section})" in out
    assert llm.n_calls == 1
