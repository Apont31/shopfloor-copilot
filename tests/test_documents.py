import os
import shutil
import subprocess
import sys
from collections import Counter
from pathlib import Path

import pytest
import yaml

from shopfloor.corpus import read_document, split_front_matter
from shopfloor.oracle.loader import ALLOWED_UNITS

ROOT = Path(__file__).resolve().parents[1]
DOCS = ROOT / "data" / "docs"
INBOX = ROOT / "data" / "nc_inbox"
TOLERANCES = ROOT / "config" / "tolerances.yaml"
SYNC = ROOT / "scripts" / "sync_tolerances.py"

DOC_KEYS = {"doc_id", "type", "domaine", "part_ref", "date", "version", "fictif"}
DOC_TYPES = {"procedure", "gamme", "nc_historique", "transverse"}
DOMAINES = {"composite", "tolerie", "peinture", "qualite"}
INBOX_KEYS = {"nc_id", "date", "site", "procede", "part_ref", "lot", "mesures"}


def documents():
    return [(p, *read_document(p)) for p in sorted(DOCS.glob("*.md"))]


def run_sync(*args):
    env = {**os.environ, "PYTHONIOENCODING": "utf-8"}
    return subprocess.run(
        [sys.executable, str(SYNC), *args], capture_output=True, text=True, encoding="utf-8", env=env
    )


def assert_mesures_valides(mesures, where):
    assert isinstance(mesures, list) and mesures, where
    for m in mesures:
        assert set(m) == {"caracteristique", "valeur", "unite"}, where
        assert isinstance(m["valeur"], (int, float)) and not isinstance(m["valeur"], bool), where
        assert m["unite"] in ALLOWED_UNITS, where


# --- Corpus data/docs ---------------------------------------------------------


def test_dix_documents_front_matter_valide():
    docs = documents()
    assert len(docs) == 10
    for path, meta, body in docs:
        assert DOC_KEYS <= set(meta), path.name
        assert meta["fictif"] is True, path.name
        assert meta["type"] in DOC_TYPES, path.name
        assert meta["domaine"] in DOMAINES, path.name
        assert path.stem == meta["doc_id"], path.name
        assert body.strip(), path.name


def test_trois_documents_par_domaine_plus_un_transverse():
    docs = documents()
    assert Counter(m["domaine"] for _, m, _ in docs) == {
        "composite": 3, "tolerie": 3, "peinture": 3, "qualite": 1,
    }
    for domaine in ("composite", "tolerie", "peinture"):
        types = sorted(m["type"] for _, m, _ in docs if m["domaine"] == domaine)
        assert types == ["gamme", "nc_historique", "procedure"], domaine
    assert [m["type"] for _, m, _ in docs if m["domaine"] == "qualite"] == ["transverse"]


def test_nc_historiques_ont_mesures_et_sections():
    for path, meta, body in documents():
        if meta["type"] != "nc_historique":
            continue
        assert_mesures_valides(meta.get("mesures"), path.name)
        for section in ("## Description", "## Cause racine", "## Action corrective", "## Décision", "## Statut"):
            assert section in body, f"{path.name} : {section}"
        assert "Clos" in body, path.name


def test_procedures_ont_les_marqueurs():
    for path, meta, body in documents():
        if meta["type"] == "procedure":
            assert "<!-- TOLERANCES:START -->" in body and "<!-- TOLERANCES:END -->" in body, path.name


def test_sync_tolerances_check_passe():
    r = run_sync("--check")
    assert r.returncode == 0, r.stdout + r.stderr


def test_sync_tolerances_check_detecte_un_yaml_modifie(tmp_path):
    docs = tmp_path / "docs"
    shutil.copytree(DOCS, docs)
    modified = tmp_path / "tolerances.yaml"
    modified.write_text(
        TOLERANCES.read_text(encoding="utf-8").replace("min: 3.05", "min: 3.04"), encoding="utf-8"
    )
    r = run_sync("--check", "--tolerances", str(modified), "--docs", str(docs))
    assert r.returncode == 1
    assert "PROC-COMP-01.md" in r.stdout

    assert run_sync("--tolerances", str(modified), "--docs", str(docs)).returncode == 0
    assert run_sync("--check", "--tolerances", str(modified), "--docs", str(docs)).returncode == 0
    assert "| 3.04 |" in (docs / "PROC-COMP-01.md").read_text(encoding="utf-8")


def test_sync_tolerances_check_detecte_des_marqueurs_absents(tmp_path):
    docs = tmp_path / "docs"
    shutil.copytree(DOCS, docs)
    p = docs / "PROC-TOL-01.md"
    p.write_text(p.read_text(encoding="utf-8").replace("<!-- TOLERANCES:END -->", ""), encoding="utf-8")
    r = run_sync("--check", "--docs", str(docs))
    assert r.returncode == 1
    assert "PROC-TOL-01.md" in r.stdout


# --- Fiches data/nc_inbox -----------------------------------------------------


def test_trois_fiches_inbox_cles_requises_et_mesures_numeriques():
    fiches = sorted(INBOX.glob("*.md"))
    assert [p.stem for p in fiches] == ["NC-2026-101", "NC-2026-102", "NC-2026-103"]
    for p in fiches:
        meta, body = read_document(p)
        assert INBOX_KEYS <= set(meta), p.name
        assert meta["nc_id"] == p.stem
        assert_mesures_valides(meta["mesures"], p.name)
        assert body.strip(), p.name


def test_fiches_inbox_ne_portent_pas_de_verdict():
    for p in INBOX.glob("*.md"):
        meta, body = read_document(p)
        assert "verdict" not in meta, p.name
        for mot in ("NON_CONFORME", "INDETERMINE"):
            assert mot not in body, p.name


# --- Jeu d'évaluation du retrieval ---------------------------------------------


def test_retrieval_cases_pointent_vers_des_doc_ids_existants():
    cases = yaml.safe_load((ROOT / "data" / "eval" / "retrieval_cases.yaml").read_text(encoding="utf-8"))["cases"]
    assert len(cases) == 5
    doc_ids = {m["doc_id"] for _, m, _ in documents()}
    for c in cases:
        assert c["query"].strip()
        assert c["expected_doc_id"] in doc_ids, c


# --- Lecteur de front-matter --------------------------------------------------


def test_split_front_matter_lf_et_crlf():
    for nl in ("\n", "\r\n"):
        meta, body = split_front_matter(nl.join(["---", "doc_id: X", "---", "corps", ""]))
        assert meta == {"doc_id": "X"}
        assert body == "corps\n"


@pytest.mark.parametrize("text", ["pas de front-matter", "---\ndoc_id: X\n", "---\n- liste\n---\n"])
def test_split_front_matter_invalide(text):
    with pytest.raises(ValueError):
        split_front_matter(text)
