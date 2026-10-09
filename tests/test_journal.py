"""Journal SQLite des traitements (étape 9) : écriture, décision, filtres, unicité du nc_id."""

import threading

import pytest

from shopfloor.journal import Journal, JournalError


@pytest.fixture
def journal(tmp_path):
    with Journal(tmp_path / "journal.db") as j:
        yield j


def pending(journal, nc_id="NC-1", **overrides):
    values = dict(
        nc_id=nc_id, fichier=f"{nc_id}.md", site="Site Alpha", procede="composite", part_ref="CP-210",
        verdict="NON_CONFORME", origine="llm", guard_ok=True, llm_ms=1234,
    )
    values.update(overrides)
    return journal.record_pending(**values)


def test_record_pending_et_get_run(journal):
    run = pending(journal)
    assert run == journal.get_run("NC-1")
    assert (run.statut, run.verdict, run.origine, run.guard_ok, run.llm_ms) == (
        "en_attente", "NON_CONFORME", "llm", True, 1234
    )
    assert run.created_at.tzinfo is not None
    assert run.decided_at is None and run.decided_by is None and run.ticket_id is None


def test_get_run_inconnu(journal):
    assert journal.get_run("NC-X") is None


def test_nc_id_unique(journal):
    pending(journal)
    with pytest.raises(JournalError, match="déjà journalisée"):
        journal.record_error(nc_id="NC-1", fichier="NC-1.md", erreur="ERP indisponible")


def test_record_error_et_doublon(journal):
    e = journal.record_error(nc_id="NC-1", fichier="NC-1.md", erreur="ERP indisponible")
    d = journal.record_error(
        nc_id="NC-2", fichier="NC-2.md", erreur="Ticket déjà existant", statut="doublon", ticket_id="TCK-0001",
        site="Site Beta", procede="peinture", part_ref="PP-120",
    )
    assert (e.statut, e.origine, e.guard_ok, e.llm_ms, e.site) == ("erreur", "aucune", None, None, None)
    assert (d.statut, d.ticket_id, d.site) == ("doublon", "TCK-0001", "Site Beta")
    with pytest.raises(ValueError):
        journal.record_error(nc_id="NC-3", fichier="NC-3.md", erreur="x", statut="approuve")


@pytest.mark.parametrize("statut, ticket_id", [("approuve", "TCK-0001"), ("modifie", "TCK-0002"), ("rejete", None)])
def test_record_decision(journal, statut, ticket_id):
    pending(journal)
    run = journal.record_decision("NC-1", statut=statut, decided_by="Valideur", ticket_id=ticket_id)
    assert (run.statut, run.ticket_id, run.decided_by) == (statut, ticket_id, "Valideur")
    assert run.decided_at is not None and run.decided_at >= run.created_at


def test_record_decision_seulement_sur_une_fiche_en_attente(journal):
    pending(journal)
    journal.record_decision("NC-1", statut="rejete", decided_by="Valideur")
    with pytest.raises(JournalError, match="aucune fiche en attente"):
        journal.record_decision("NC-1", statut="approuve", decided_by="Autre", ticket_id="TCK-0009")
    with pytest.raises(JournalError):
        journal.record_decision("NC-X", statut="rejete", decided_by="Valideur")
    assert journal.get_run("NC-1").statut == "rejete"


def test_record_decision_statut_invalide(journal):
    pending(journal)
    for statut in ("en_attente", "doublon"):
        with pytest.raises(ValueError):
            journal.record_decision("NC-1", statut=statut, decided_by="Valideur")


def test_delete_error_rend_la_fiche_traitable(journal):
    journal.record_error(nc_id="NC-1", fichier="NC-1.md", erreur="ERP indisponible")
    journal.delete_error("NC-1")
    assert journal.get_run("NC-1") is None
    pending(journal)  # le nc_id est de nouveau libre
    assert journal.get_run("NC-1").statut == "en_attente"


@pytest.mark.parametrize("statut", ["doublon", "en_attente", None])
def test_delete_error_seulement_sur_une_fiche_en_erreur(journal, statut):
    if statut == "doublon":
        journal.record_error(nc_id="NC-1", fichier="NC-1.md", erreur="doublon", statut="doublon")
    elif statut == "en_attente":
        pending(journal)
    with pytest.raises(JournalError, match="aucune fiche en erreur pour NC-1"):
        journal.delete_error("NC-1")
    assert (journal.get_run("NC-1") is None) == (statut is None)


def test_list_runs_filtres(journal):
    pending(journal, "NC-1")
    pending(journal, "NC-2", site="Site Beta", procede="peinture", part_ref="PP-120", verdict="CONFORME",
            origine="deterministe", guard_ok=None, llm_ms=None)
    journal.record_error(nc_id="NC-3", fichier="NC-3.md", erreur="fiche illisible")
    assert [r.nc_id for r in journal.list_runs()] == ["NC-1", "NC-2", "NC-3"]
    assert [r.nc_id for r in journal.list_runs(statut="en_attente")] == ["NC-1", "NC-2"]
    assert [r.nc_id for r in journal.list_runs(statut="en_attente", procede="peinture")] == ["NC-2"]
    assert [r.nc_id for r in journal.list_runs(site="Site Alpha", verdict="NON_CONFORME")] == ["NC-1"]
    assert [r.nc_id for r in journal.list_runs(origine="aucune")] == ["NC-3"]
    assert journal.list_runs(statut=None, site=None) == journal.list_runs()
    with pytest.raises(ValueError, match="filtre"):
        journal.list_runs(nc_id="NC-1; DROP TABLE runs")


def test_persistance_entre_deux_connexions(tmp_path):
    with Journal(tmp_path / "j.db") as j:
        pending(j)
    with Journal(tmp_path / "j.db") as j:
        assert j.get_run("NC-1").statut == "en_attente"


def test_utilisable_depuis_un_autre_thread(journal):
    """check_same_thread=False : l'interface Streamlit lira le journal depuis ses propres threads."""
    pending(journal)
    result = []
    t = threading.Thread(target=lambda: result.append(journal.list_runs()))
    t.start()
    t.join()
    assert [r.nc_id for r in result[0]] == ["NC-1"]
