"""Sous-commande process : run_process avec FakeLLM, FakeEmbedder (index dans tmp_path) et ERP TestClient."""

from dataclasses import replace
from decimal import Decimal
from pathlib import Path

import pytest
from fakes import FakeLLM, proposal_json
from fastapi.testclient import TestClient

from shopfloor import cli
from shopfloor.agent.graph import Deps
from shopfloor.agent.state import HumanDecision
from shopfloor.config import Settings
from shopfloor.erp.api import create_app
from shopfloor.erp.client import ErpClient
from shopfloor.llm.client import LLMError
from shopfloor.llm.ollama_client import OllamaLLM
from shopfloor.oracle.loader import load_tolerances
from shopfloor.rag.embeddings import FakeEmbedder, OllamaEmbedder
from shopfloor.rag.ingest import ingest
from shopfloor.rag.retriever import make_retriever

ROOT = Path(__file__).resolve().parents[1]
INBOX = ROOT / "data" / "nc_inbox"
NC_101, NC_102 = INBOX / "NC-2026-101.md", INBOX / "NC-2026-102.md"
TOLERANCES = load_tolerances(ROOT / "config" / "tolerances.yaml")
APPROVE = HumanDecision(decision="approve", valide_par="Chef d'atelier fictif")
REJECT = HumanDecision(decision="reject", valide_par="Chef d'atelier fictif")


@pytest.fixture(scope="module")
def chroma_dir(tmp_path_factory):
    path = tmp_path_factory.mktemp("chroma")
    ingest(FakeEmbedder(), ROOT / "data" / "docs", path)
    return path


@pytest.fixture
def erp_http(tmp_path):
    return TestClient(create_app(tmp_path / "erp.db"))


def deps(chroma_dir, erp_client, llm=None) -> Deps:
    return Deps(
        tolerances=TOLERANCES,
        retriever=make_retriever(chroma_dir, FakeEmbedder()),
        llm=llm,
        erp=erp_client,
    )


def llm_ok() -> FakeLLM:
    """Proposition valide sans source : le top 3 du FakeEmbedder n'est pas fixé par ces tests."""
    return FakeLLM(proposal_json(sources=[]))


def test_approve_ticket_cree(chroma_dir, erp_http, capsys):
    seen = []
    llm = llm_ok()
    erp = ErpClient("http://testserver", http_client=erp_http)
    code = cli.run_process(NC_101, deps(chroma_dir, erp, llm), lambda payload: seen.append(payload) or APPROVE)
    out = capsys.readouterr().out
    assert code == 0
    [ticket] = erp_http.get("/tickets").json()
    assert ticket["verdict"] == "NON_CONFORME" and ticket["nc_id"] == "NC-2026-101"
    assert f"Ticket créé : {ticket['id']}" in out
    # Affichage : verdict, tableau des mesures, documents similaires, proposition, durée LLM.
    assert "Verdict de l'oracle : Non conforme" in out
    assert "Porosité" in out and "2.8 %" in out and "2.0" in out and "0.8 %" in out
    assert out.count("score=") == 3
    assert "Proposition (origine : llm)" in out
    assert "ALERTE" not in out
    assert "Appel LLM :" in out and "1 appel(s)" in out
    # Le valideur reçoit le payload de human_gate.
    [payload] = seen
    assert payload["verdict"] == "NON_CONFORME" and payload["proposition"]["origine"] == "llm"


def test_erp_injoignable_code_1_message_clair(chroma_dir, capsys):
    erp = ErpClient("http://127.0.0.1:9", timeout=0.5)
    code = cli.run_process(NC_101, deps(chroma_dir, erp, llm_ok()), lambda p: APPROVE)
    out = capsys.readouterr().out
    assert code == 1
    assert "ERREUR : ERP indisponible : serveur injoignable à http://127.0.0.1:9" in out
    assert "Ticket créé" not in out and "Verdict de l'oracle" not in out


def test_doublon_code_1_sans_llm_ni_decision(chroma_dir, erp_http, capsys):
    erp = ErpClient("http://testserver", http_client=erp_http)
    assert cli.run_process(NC_101, deps(chroma_dir, erp, llm_ok()), lambda p: APPROVE) == 0
    [ticket] = erp_http.get("/tickets").json()
    capsys.readouterr()
    llm = FakeLLM()

    def decide(payload):
        raise AssertionError("aucune décision ne doit être demandée")

    assert cli.run_process(NC_101, deps(chroma_dir, erp, llm), decide) == 1
    out = capsys.readouterr().out
    assert f"ERREUR : Ticket déjà existant pour NC-2026-101 : {ticket['id']}" in out
    assert llm.n_calls == 0 and "Appel LLM" not in out


def test_rejet_aucun_ticket_code_0(chroma_dir, erp_http, capsys):
    erp = ErpClient("http://testserver", http_client=erp_http)
    code = cli.run_process(NC_101, deps(chroma_dir, erp, llm_ok()), lambda p: REJECT)
    assert code == 0
    assert "aucun ticket créé" in capsys.readouterr().out
    assert erp_http.get("/tickets").json() == []


def test_repli_affiche_alerte_garde_fou(chroma_dir, erp_http, capsys):
    erp = ErpClient("http://testserver", http_client=erp_http)
    llm = FakeLLM(LLMError("Ollama injoignable"))
    assert cli.run_process(NC_101, deps(chroma_dir, erp, llm), lambda p: APPROVE) == 0
    out = capsys.readouterr().out
    assert "Proposition (origine : deterministe)" in out
    assert "ALERTE garde-fou" in out and "Ollama injoignable" in out


def test_sans_llm_conforme(chroma_dir, erp_http, capsys):
    erp = ErpClient("http://testserver", http_client=erp_http)
    assert cli.run_process(NC_102, deps(chroma_dir, erp), lambda p: APPROVE) == 0
    out = capsys.readouterr().out
    assert "Verdict de l'oracle : Conforme" in out
    assert "Appel LLM : aucun" in out
    assert erp_http.get("/tickets").json()[0]["verdict"] == "CONFORME"


def test_index_absent_code_1(tmp_path, erp_http, capsys):
    erp = ErpClient("http://testserver", http_client=erp_http)
    llm = FakeLLM()
    code = cli.run_process(NC_101, deps(tmp_path / "vide", erp, llm), lambda p: APPROVE)
    assert code == 1 and llm.n_calls == 0
    assert "ERREUR : Index RAG indisponible : lancez python -m shopfloor.cli ingest" in capsys.readouterr().out


def test_fiche_absente_code_1(chroma_dir, erp_http, tmp_path, capsys):
    erp = ErpClient("http://testserver", http_client=erp_http)
    assert cli.run_process(tmp_path / "absente.md", deps(chroma_dir, erp), lambda p: APPROVE) == 1
    assert "ERREUR : fiche illisible" in capsys.readouterr().out


def test_interruption_sans_decision_code_1(chroma_dir, erp_http, capsys):
    def decide(payload):
        raise EOFError

    erp = ErpClient("http://testserver", http_client=erp_http)
    assert cli.run_process(NC_101, deps(chroma_dir, erp, llm_ok()), decide) == 1
    assert erp_http.get("/tickets").json() == []


# --- Décision interactive -------------------------------------------------------------------------


def scripted(*answers):
    it = iter(answers)
    return lambda prompt="": next(it)


@pytest.mark.parametrize("answers, expected", [
    (("a",), HumanDecision(decision="approve", valide_par="Valideur")),
    (("x", "r", "à revoir"), HumanDecision(decision="reject", valide_par="Valideur", commentaire="à revoir")),
    (("r", ""), HumanDecision(decision="reject", valide_par="Valideur")),
    (("m", "", "m", "Refaire le test d'étanchéité."),
     HumanDecision(decision="edit", valide_par="Valideur", action_corrective="Refaire le test d'étanchéité.")),
])
def test_ask_decision(answers, expected):
    assert cli.ask_decision({}, "Valideur", scripted(*answers)) == expected


def test_ask_decision_demande_le_valideur():
    decision = cli.ask_decision({}, None, scripted("  ", "Valideur", "a"))
    assert decision.valide_par == "Valideur"


# --- Couche CLI -----------------------------------------------------------------------------------


def test_cli_process_sans_llm_erp_injoignable(chroma_dir, monkeypatch, capsys):
    """La CLI câble Settings, retriever et ERP ; ici l'ERP réel est absent -> code 1."""
    monkeypatch.setenv("CHROMA_DIR", str(chroma_dir))
    code = cli.main(
        ["process", str(NC_101), "--llm", "none", "--erp-url", "http://127.0.0.1:9",
         "--decision", "approve", "--valide-par", "Chef d'atelier fictif"],
        embedder=FakeEmbedder(),
    )
    out = capsys.readouterr().out
    assert code == 1
    # Étape 8a : arrêt dès check_existing, avant l'oracle et toute proposition.
    assert "Verdict de l'oracle" not in out and "Proposition" not in out
    assert "ERREUR : ERP indisponible : serveur injoignable à http://127.0.0.1:9" in out


def test_cli_decision_exige_valide_par(capsys):
    with pytest.raises(SystemExit):
        cli.main(["process", str(NC_101), "--decision", "approve"], embedder=FakeEmbedder())
    assert "--valide-par" in capsys.readouterr().err


# --- Étape 7b : messages d'erreur ---------------------------------------------------------------------

OLLAMA_KO = "ERREUR : Ollama indisponible : lancez l'application Ollama"


def ollama_absent() -> OllamaEmbedder:
    return OllamaEmbedder(Settings(ollama_host="http://127.0.0.1:9"))


def test_process_embedder_injoignable_code_1(chroma_dir, erp_http, capsys):
    erp = ErpClient("http://testserver", http_client=erp_http)
    d = replace(deps(chroma_dir, erp, FakeLLM()), retriever=make_retriever(chroma_dir, ollama_absent()))
    assert cli.run_process(NC_101, d, lambda p: APPROVE) == 1
    assert OLLAMA_KO in capsys.readouterr().out
    assert erp_http.get("/tickets").json() == []


def test_process_llm_injoignable_alerte(chroma_dir, erp_http, capsys):
    erp = ErpClient("http://testserver", http_client=erp_http)
    llm = OllamaLLM(Settings(ollama_host="http://127.0.0.1:9"), timeout=2)
    assert cli.run_process(NC_101, deps(chroma_dir, erp, llm), lambda p: APPROVE) == 0
    out = capsys.readouterr().out
    assert "ALERTE garde-fou :\n  - Ollama indisponible : lancez l'application Ollama" in out


def test_cli_ingest_ollama_injoignable(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("CHROMA_DIR", str(tmp_path / "chroma"))
    assert cli.main(["ingest"], embedder=ollama_absent()) == 1
    assert OLLAMA_KO in capsys.readouterr().out


def test_cli_search_ollama_injoignable(chroma_dir, monkeypatch, capsys):
    monkeypatch.setenv("CHROMA_DIR", str(chroma_dir))
    assert cli.main(["search", "porosité"], embedder=ollama_absent()) == 1
    assert OLLAMA_KO in capsys.readouterr().out


def test_cli_search_collection_absente(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("CHROMA_DIR", str(tmp_path / "vide"))
    assert cli.main(["search", "porosité"], embedder=FakeEmbedder()) == 1
    assert "ERREUR : Index RAG indisponible : lancez python -m shopfloor.cli ingest" in capsys.readouterr().out


# --- Étape 8a : affichage des unités -------------------------------------------------------------------

@pytest.mark.parametrize("valeur, unite, attendu", [
    (Decimal("2.8"), "pct", "2.8 %"),
    (Decimal("12"), "um", "12 µm"),
    (Decimal("91.2"), "deg", "91.2°"),
    (Decimal("180"), "degC", "180 °C"),
    (Decimal("3.20"), "mm", "3.20 mm"),  # autres codes : tels quels
    (Decimal("85"), "GU", "85 GU"),
    (Decimal("1"), "classe", "1 classe"),
    (Decimal("-0.15"), "mm", "-0.15 mm"),
    (None, "pct", "-"),
])
def test_fmt_mesure(valeur, unite, attendu):
    assert cli.fmt_mesure(valeur, unite) == attendu


def test_tableau_oracle_ecart_avec_unite(chroma_dir, erp_http, capsys):
    erp = ErpClient("http://testserver", http_client=erp_http)
    cli.run_process(NC_101, deps(chroma_dir, erp, llm_ok()), lambda p: REJECT)
    [ligne] = [l for l in capsys.readouterr().out.splitlines() if l.strip().startswith("Porosité")]
    assert ligne.split() == ["Porosité", "2.8", "%", "-", "2.0", "0.8", "%", "Non", "conforme"]
    assert "pct" not in ligne
