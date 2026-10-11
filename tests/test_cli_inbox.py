"""Sous-commandes run-inbox, pending et decide (étape 9) : fonctions testables et couche CLI.

FakeLLM, faux retriever, bases SQLite dans tmp_path, ERP en TestClient.
"""

import shutil
from pathlib import Path

import pytest
from fakes import FakeLLM, fake_retriever, proposal_json
from fastapi.testclient import TestClient

from shopfloor import cli
from shopfloor.agent.graph import Deps
from shopfloor.erp.api import create_app
from shopfloor.erp.client import ErpClient
from shopfloor.journal import Journal
from shopfloor.oracle.loader import load_tolerances
from shopfloor.rag.embeddings import FakeEmbedder
from shopfloor.service import Service

ROOT = Path(__file__).resolve().parents[1]
INBOX = ROOT / "data" / "nc_inbox"
TOLERANCES = load_tolerances(ROOT / "config" / "tolerances.yaml")
VALIDEUR = "Chef d'atelier fictif"


@pytest.fixture
def erp_http(tmp_path):
    return TestClient(create_app(tmp_path / "erp.db"))


@pytest.fixture
def inbox(tmp_path):
    d = tmp_path / "inbox"
    d.mkdir()
    for nc_id in ("NC-2026-101", "NC-2026-102", "NC-2026-103"):
        shutil.copy(INBOX / f"{nc_id}.md", d / f"{nc_id}.md")
    return d


def make_service(tmp_path, erp_client, llm=None) -> Service:
    deps = Deps(tolerances=TOLERANCES, retriever=fake_retriever, llm=llm, erp=erp_client)
    return Service(deps, state_db=tmp_path / "state.db", journal_db=tmp_path / "journal.db")


@pytest.fixture
def service(tmp_path, erp_http):
    erp = ErpClient("http://testserver", http_client=erp_http)
    with make_service(tmp_path, erp, FakeLLM(proposal_json(sources=[]))) as s:
        yield s


def ligne(out: str, debut: str) -> list[str]:
    [l] = [l for l in out.splitlines() if l.strip().startswith(debut)]
    return l.split()


def test_run_inbox_recapitulatif(service, inbox, capsys):
    assert cli.run_inbox(service, inbox) == 0
    out = capsys.readouterr().out
    assert "3 fiche(s), 3 traitée(s), 0 déjà journalisée(s) ignorée(s)" in out
    assert ligne(out, "Fiche") == ["Fiche", "Verdict", "Statut", "Origine", "LLM", "Détail"]
    assert ligne(out, "NC-2026-101")[:5] == ["NC-2026-101", "Non", "conforme", "en_attente", "llm"]
    assert ligne(out, "NC-2026-102") == ["NC-2026-102", "Conforme", "en_attente", "deterministe", "-"]
    assert ligne(out, "NC-2026-103") == ["NC-2026-103", "Indéterminé", "en_attente", "deterministe", "-"]
    assert "Récapitulatif : 3 en_attente" in out
    assert "Appels LLM : " in out and "Appels LLM : aucun" not in out


def test_run_inbox_idempotent(service, inbox, capsys):
    cli.run_inbox(service, inbox)
    capsys.readouterr()
    assert cli.run_inbox(service, inbox) == 0
    out = capsys.readouterr().out
    assert "3 fiche(s), 0 traitée(s), 3 déjà journalisée(s) ignorée(s)" in out
    assert "Récapitulatif" not in out


def test_run_inbox_fiche_journalisee_ailleurs_comptee_ignoree(tmp_path, service, inbox, capsys, monkeypatch):
    """Un autre processus journalise NC-2026-101 pendant son traitement : ignorée, sans exception (étape 10c)."""
    record_pending = service.journal.record_pending

    def autre_processus_d_abord(**values):
        if values["nc_id"] == "NC-2026-101":
            with Journal(tmp_path / "journal.db") as autre:
                autre.record_pending(**values)
        return record_pending(**values)

    monkeypatch.setattr(service.journal, "record_pending", autre_processus_d_abord)
    assert cli.run_inbox(service, inbox) == 0
    out = capsys.readouterr().out
    assert "3 fiche(s), 2 traitée(s), 1 déjà journalisée(s) ignorée(s)" in out
    assert ligne(out, "NC-2026-102")[0] == "NC-2026-102" and "NC-2026-101  " not in out


def test_run_inbox_erreur_code_1(tmp_path, inbox, capsys):
    with make_service(tmp_path, ErpClient("http://127.0.0.1:9", timeout=0.5)) as service:
        (inbox / "NC-2026-102.md").unlink()
        (inbox / "NC-2026-103.md").unlink()
        assert cli.run_inbox(service, inbox) == 1
    out = capsys.readouterr().out
    assert ligne(out, "NC-2026-101") == ["NC-2026-101", "-", "erreur", "aucune", "-", "ERP", "indisponible"]
    assert "Récapitulatif : 1 erreur" in out and "Appels LLM : aucun" in out


def test_pending_affiche_la_file(service, inbox, capsys):
    cli.run_inbox(service, inbox)
    capsys.readouterr()
    assert cli.print_pending(service) == 0
    out = capsys.readouterr().out
    assert "File de validation : 3 fiche(s) en attente" in out
    assert "NC-2026-101  Non conforme  - pièce CP-210 (Composite), Site Beta" in out
    assert "Mesure      : Porosité 2.8 % (min -, max 2.0) Non conforme" in out
    assert "Proposition : origine llm, décision suggérée rebut" in out
    assert "Mesure      : Rugosité 3.2 µm (min -, max -) Indéterminé" in out
    assert "ALERTE" not in out


def test_pending_vide(service, capsys):
    assert cli.print_pending(service) == 0
    assert "File de validation : 0 fiche(s) en attente" in capsys.readouterr().out


def test_pending_affiche_l_alerte_du_garde_fou(tmp_path, erp_http, inbox, capsys):
    erp = ErpClient("http://testserver", http_client=erp_http)
    adverse = proposal_json(resume="La pièce est conforme.", sources=[])
    with make_service(tmp_path, erp, FakeLLM(adverse)) as service:
        service.process_inbox(inbox)
        cli.print_pending(service)
    out = capsys.readouterr().out
    assert "ALERTE garde-fou :\n    - resume affirme la conformité" in out
    assert "Proposition : origine deterministe" in out


@pytest.mark.parametrize("decision, action, attendu", [
    ("approve", None, "NC-2026-101 : approuve par Chef d'atelier fictif, ticket créé : TCK-"),
    ("edit", "Refaire le test d'étanchéité.", "NC-2026-101 : modifie par Chef d'atelier fictif, ticket créé : TCK-"),
    ("reject", None, "NC-2026-101 : rejete par Chef d'atelier fictif, aucun ticket créé"),
])
def test_run_decide(service, inbox, erp_http, capsys, decision, action, attendu):
    service.process_inbox(inbox)
    assert cli.run_decide(service, "NC-2026-101", decision, VALIDEUR, action) == 0
    assert attendu in capsys.readouterr().out
    tickets = erp_http.get("/tickets").json()
    assert len(tickets) == (0 if decision == "reject" else 1)
    if action:
        assert tickets[0]["action_proposee"] == action


def test_run_decide_fiche_inconnue_code_1(service, capsys):
    assert cli.run_decide(service, "NC-INCONNUE", "approve", VALIDEUR) == 1
    assert "ERREUR : NC-INCONNUE : fiche absente du journal" in capsys.readouterr().out


def test_run_decide_erp_injoignable_code_1(tmp_path, inbox, erp_http, capsys):
    with make_service(tmp_path, ErpClient("http://testserver", http_client=erp_http)) as service:
        service.process_inbox(inbox)
    with make_service(tmp_path, ErpClient("http://127.0.0.1:9", timeout=0.5)) as service:
        assert cli.run_decide(service, "NC-2026-102", "approve", VALIDEUR) == 1
        assert service.journal.get_run("NC-2026-102").statut == "en_attente"
    assert ("ERREUR : NC-2026-102 : ERP indisponible : lancez le serveur ERP. "
            "La fiche reste en attente de validation.") in capsys.readouterr().out


# --- Couche CLI (main) ----------------------------------------------------------------------------


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("STATE_DB", str(tmp_path / "state.db"))
    monkeypatch.setenv("JOURNAL_DB", str(tmp_path / "journal.db"))
    monkeypatch.setenv("CHROMA_DIR", str(tmp_path / "chroma"))
    return tmp_path


def test_main_run_inbox_puis_pending(env, inbox, capsys):
    """La CLI câble Settings, Service et ERP ; l'ERP réel est absent : fiches en erreur, rien en attente."""
    code = cli.main(["run-inbox", "--llm", "none", "--erp-url", "http://127.0.0.1:9", "--inbox", str(inbox)],
                    embedder=FakeEmbedder())
    assert code == 1
    out = capsys.readouterr().out
    assert "3 fiche(s), 3 traitée(s)" in out and "Récapitulatif : 3 erreur" in out
    assert (env / "state.db").exists() and (env / "journal.db").exists()

    assert cli.main(["pending"], embedder=FakeEmbedder()) == 0
    assert "File de validation : 0 fiche(s) en attente" in capsys.readouterr().out

    code = cli.main(["run-inbox", "--llm", "none", "--erp-url", "http://127.0.0.1:9", "--inbox", str(inbox)],
                    embedder=FakeEmbedder())
    assert code == 0 and "0 traitée(s), 3 déjà journalisée(s)" in capsys.readouterr().out


def test_main_decide_sur_le_journal_partage(env, inbox, erp_http, capsys):
    """Fiche mise en attente par un premier processus, décision par la commande decide."""
    erp = ErpClient("http://testserver", http_client=erp_http)
    deps = Deps(tolerances=TOLERANCES, retriever=fake_retriever, erp=erp)
    with Service(deps, state_db=env / "state.db", journal_db=env / "journal.db") as service:
        service.process_inbox(inbox)
    code = cli.main(["decide", "NC-2026-102", "reject", "--valide-par", VALIDEUR, "--commentaire", "doublon papier"],
                    embedder=FakeEmbedder())
    assert code == 0
    assert "NC-2026-102 : rejete par Chef d'atelier fictif, aucun ticket créé" in capsys.readouterr().out
    assert cli.main(["decide", "NC-2026-102", "approve", "--valide-par", VALIDEUR], embedder=FakeEmbedder()) == 1
    assert "n'est pas en attente de validation (statut : rejete)" in capsys.readouterr().out


def test_run_retry(tmp_path, inbox, erp_http, capsys):
    with make_service(tmp_path, ErpClient("http://127.0.0.1:9", timeout=0.5)) as service:
        service.process_inbox(inbox)
    with make_service(tmp_path, ErpClient("http://testserver", http_client=erp_http)) as service:
        assert cli.run_retry(service, "NC-2026-102") == 0
        assert "NC-2026-102 : sera traitée de nouveau au prochain run-inbox" in capsys.readouterr().out
        assert [r.nc_id for r in service.process_inbox(inbox)] == ["NC-2026-102"]
        assert service.journal.get_run("NC-2026-102").statut == "en_attente"
        assert cli.run_retry(service, "NC-2026-102") == 1
        assert "ERREUR : NC-2026-102 n'est pas en erreur (statut : en_attente)" in capsys.readouterr().out


def test_main_retry(env, inbox, capsys):
    cli.main(["run-inbox", "--llm", "none", "--erp-url", "http://127.0.0.1:9", "--inbox", str(inbox)],
             embedder=FakeEmbedder())
    capsys.readouterr()
    assert cli.main(["retry", "NC-2026-101"], embedder=FakeEmbedder()) == 0
    assert "NC-2026-101 : sera traitée de nouveau" in capsys.readouterr().out
    code = cli.main(["run-inbox", "--llm", "none", "--erp-url", "http://127.0.0.1:9", "--inbox", str(inbox)],
                    embedder=FakeEmbedder())
    assert code == 1 and "1 traitée(s), 2 déjà journalisée(s)" in capsys.readouterr().out


@pytest.mark.parametrize("argv, message", [
    (["decide", "NC-1", "edit", "--valide-par", "X"], "--action est obligatoire avec edit"),
    (["decide", "NC-1", "approve", "--action", "Y", "--valide-par", "X"], "--action est obligatoire avec edit"),
    (["decide", "NC-1", "approve"], "--valide-par"),
    (["decide", "NC-1", "valider", "--valide-par", "X"], "invalid choice"),
])
def test_main_decide_arguments_invalides(env, capsys, argv, message):
    with pytest.raises(SystemExit):
        cli.main(argv, embedder=FakeEmbedder())
    assert message in capsys.readouterr().err
