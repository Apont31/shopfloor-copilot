"""Sous-commande reset (étape 14) : bases dans tmp_path, verrouillage simulé, confirmation."""

from pathlib import Path

import pytest

from shopfloor import cli
from shopfloor.config import Settings

ROOT = Path(__file__).resolve().parents[1]
NOMS = ("erp.db", "shopfloor_journal.db", "shopfloor_state.db")
TOUS = [n + s for n in NOMS for s in ("", "-wal", "-shm")]


@pytest.fixture
def env(tmp_path, monkeypatch):
    """Bases pointées dans tmp_path, plus un index RAG et un dossier data/ qui ne doivent jamais bouger."""
    monkeypatch.setenv("ERP_DB", str(tmp_path / "erp.db"))
    monkeypatch.setenv("JOURNAL_DB", str(tmp_path / "shopfloor_journal.db"))
    monkeypatch.setenv("STATE_DB", str(tmp_path / "shopfloor_state.db"))
    monkeypatch.setenv("CHROMA_DIR", str(tmp_path / ".chroma"))
    (tmp_path / ".chroma").mkdir()
    (tmp_path / ".chroma" / "chroma.sqlite3").write_text("index")
    (tmp_path / "data").mkdir()
    (tmp_path / "data" / "fiche.md").write_text("fiche")
    return tmp_path


def creer(tmp_path, noms=TOUS):
    for n in noms:
        (tmp_path / n).write_text("x")


def restants(tmp_path):
    return sorted(n for n in TOUS if (tmp_path / n).exists())


def test_reset_targets_lit_settings():
    s = Settings(erp_db="a.db", journal_db="b.db", state_db="c.db")
    assert [str(p) for p in cli.reset_targets(s)] == [
        "a.db", "a.db-wal", "a.db-shm", "b.db", "b.db-wal", "b.db-shm", "c.db", "c.db-wal", "c.db-shm"]


def test_suppression_complete_avec_yes(env, capsys):
    creer(env)
    assert cli.main(["reset", "--yes"]) == 0
    assert restants(env) == []
    out = capsys.readouterr().out
    assert "9 fichier(s) supprimé(s)" in out
    for n in TOUS:
        assert str(env / n) in out
    # Jamais l'index RAG ni data/.
    assert (env / ".chroma" / "chroma.sqlite3").read_text() == "index"
    assert (env / "data" / "fiche.md").read_text() == "fiche"


def test_suppression_partielle_seulement_les_presents(env, capsys):
    creer(env, ["erp.db", "shopfloor_state.db-wal"])
    assert cli.main(["reset", "--yes"]) == 0
    assert restants(env) == []
    assert "2 fichier(s) supprimé(s)" in capsys.readouterr().out


def test_absence_de_fichiers(env, capsys):
    assert cli.main(["reset", "--yes"]) == 0
    assert "Rien à supprimer" in capsys.readouterr().out


def test_confirmation_acceptee(env):
    creer(env)
    assert cli.run_reset(Settings(), input_fn=lambda _: "o") == 0
    assert restants(env) == []


@pytest.mark.parametrize("reponse", ["", "n", "non", "yes"])
def test_refus_sans_confirmation(env, capsys, reponse):
    creer(env)
    assert cli.run_reset(Settings(), input_fn=lambda _: reponse) == 1
    assert restants(env) == sorted(TOUS)
    assert "Annulé : aucun fichier supprimé." in capsys.readouterr().out


def test_refus_sur_fin_de_saisie(env, monkeypatch):
    creer(env)

    def eof(_):
        raise EOFError

    monkeypatch.setattr("builtins.input", eof)
    assert cli.main(["reset"]) == 1
    assert restants(env) == sorted(TOUS)


def test_fichier_verrouille(env, monkeypatch, capsys):
    creer(env)
    verrouille = env / "shopfloor_journal.db"
    unlink = Path.unlink

    def unlink_simule(self, missing_ok=False):
        if self == verrouille:
            raise PermissionError(32, "Le processus ne peut pas accéder au fichier")
        return unlink(self, missing_ok=missing_ok)

    monkeypatch.setattr(Path, "unlink", unlink_simule)
    assert cli.main(["reset", "--yes"]) == 1
    captured = capsys.readouterr()
    assert "Fermez l'interface et le serveur ERP, puis relancez reset" in captured.out
    assert "Traceback" not in captured.out + captured.err
    # Ce qui précède le fichier verrouillé est supprimé et listé ; le reste est intact.
    assert "3 fichier(s) supprimé(s)" in captured.out
    assert restants(env) == sorted(n for n in TOUS if n.startswith(("shopfloor_journal", "shopfloor_state")))


def test_chemin_protege_refuse(env, monkeypatch, capsys):
    monkeypatch.setenv("ERP_DB", str(env / ".chroma" / "chroma.sqlite3"))
    assert cli.main(["reset", "--yes"]) == 1
    assert "chemin protégé" in capsys.readouterr().out
    assert (env / ".chroma" / "chroma.sqlite3").read_text() == "index"


def test_dossier_data_du_depot_protege(env, monkeypatch, capsys):
    monkeypatch.setenv("JOURNAL_DB", str(ROOT / "data" / "journal.db"))
    assert cli.main(["reset", "--yes"]) == 1
    assert "chemin protégé" in capsys.readouterr().out
