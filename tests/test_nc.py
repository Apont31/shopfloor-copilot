from decimal import Decimal
from pathlib import Path

import pytest
import yaml

from shopfloor.models import NCRecord, Verdict
from shopfloor.nc import REQUIRED_FIELDS, NCParseError, parse_nc_file
from shopfloor.oracle.conformity import check_conformity
from shopfloor.oracle.loader import load_tolerances

ROOT = Path(__file__).resolve().parents[1]
INBOX = ROOT / "data" / "nc_inbox"
TOLERANCES = ROOT / "config" / "tolerances.yaml"


def base_meta():
    return {
        "nc_id": "NC-TEST-001",
        "date": "2026-01-01",
        "site": "Atelier test (fictif)",
        "procede": "composite",
        "part_ref": "CP-210",
        "lot": "L-TEST",
        "mesures": [{"caracteristique": "porosite", "valeur": 2.8, "unite": "pct"}],
    }


def write_fiche(tmp_path, meta, body="Description de test.\n", raw_front=None):
    front = raw_front if raw_front is not None else yaml.safe_dump(meta, allow_unicode=True)
    p = tmp_path / "fiche.md"
    p.write_text(f"---\n{front}---\n\n{body}", encoding="utf-8")
    return p


# --- Lecture des fiches de démo ---------------------------------------------------


@pytest.mark.parametrize("path", sorted(INBOX.glob("*.md")), ids=lambda p: p.stem)
def test_fiches_inbox_se_lisent(path):
    nc = parse_nc_file(path)
    assert isinstance(nc, NCRecord)
    assert nc.nc_id == path.stem
    assert nc.mesures and all(isinstance(m.valeur, Decimal) for m in nc.mesures)
    assert nc.description


def test_valeurs_lues_exactement():
    nc = parse_nc_file(INBOX / "NC-2026-101.md")
    assert (nc.part_ref, nc.procede, nc.lot) == ("CP-210", "composite", "L26-0209-C")
    m = nc.mesures[0]
    assert (m.caracteristique, m.valeur, m.unite) == ("porosite", Decimal("2.8"), "pct")
    assert str(m.valeur) == "2.8"


def test_fiche_minimale_valide(tmp_path):
    nc = parse_nc_file(write_fiche(tmp_path, base_meta()))
    assert nc.description == "Description de test."


def test_numero_de_lot_numerique_converti_en_texte(tmp_path):
    meta = base_meta() | {"lot": 12345}
    assert parse_nc_file(write_fiche(tmp_path, meta)).lot == "12345"


def test_cle_inconnue_du_front_matter_ignoree(tmp_path):
    # Un champ « verdict » ajouté à la fiche n'entre pas dans NCRecord.
    meta = base_meta() | {"verdict": "CONFORME"}
    nc = parse_nc_file(write_fiche(tmp_path, meta))
    assert not hasattr(nc, "verdict")


# --- Erreurs NCParseError -----------------------------------------------------------


@pytest.mark.parametrize("champ", REQUIRED_FIELDS)
def test_champ_manquant(tmp_path, champ):
    meta = base_meta()
    del meta[champ]
    with pytest.raises(NCParseError, match=champ):
        parse_nc_file(write_fiche(tmp_path, meta))


@pytest.mark.parametrize("champ", ["caracteristique", "valeur", "unite"])
def test_champ_de_mesure_manquant(tmp_path, champ):
    meta = base_meta()
    del meta["mesures"][0][champ]
    with pytest.raises(NCParseError, match=champ):
        parse_nc_file(write_fiche(tmp_path, meta))


@pytest.mark.parametrize("valeur", ["abc", "2,8", "2.8", True, [2.8]], ids=repr)
def test_valeur_non_numerique(tmp_path, valeur):
    meta = base_meta()
    meta["mesures"][0]["valeur"] = valeur
    with pytest.raises(NCParseError, match="non numérique"):
        parse_nc_file(write_fiche(tmp_path, meta))


@pytest.mark.parametrize("valeur", [".nan", ".inf"])
def test_valeur_non_finie(tmp_path, valeur):
    front = yaml.safe_dump(base_meta()).replace("valeur: 2.8", f"valeur: {valeur}")
    with pytest.raises(NCParseError):
        parse_nc_file(write_fiche(tmp_path, None, raw_front=front))


@pytest.mark.parametrize(
    "mesures",
    [
        pytest.param("porosite 2.8", id="pas_une_liste"),
        pytest.param(["porosite"], id="mesure_pas_un_dict"),
        pytest.param([{"caracteristique": "porosite", "valeur": 2.8, "unite": "pct", "x": 1}], id="cle_en_trop"),
    ],
)
def test_mesures_mal_formees(tmp_path, mesures):
    meta = base_meta() | {"mesures": mesures}
    with pytest.raises(NCParseError):
        parse_nc_file(write_fiche(tmp_path, meta))


def test_date_invalide(tmp_path):
    with pytest.raises(NCParseError):
        parse_nc_file(write_fiche(tmp_path, base_meta() | {"date": "pas une date"}))


def test_sans_front_matter(tmp_path):
    p = tmp_path / "fiche.md"
    p.write_text("Juste du texte.\n", encoding="utf-8")
    with pytest.raises(NCParseError):
        parse_nc_file(p)


def test_fichier_absent(tmp_path):
    with pytest.raises(NCParseError):
        parse_nc_file(tmp_path / "absent.md")


# --- Bout en bout : lecture + oracle ------------------------------------------------


@pytest.mark.parametrize(
    "nc_id, attendu",
    [
        ("NC-2026-101", Verdict.NON_CONFORME),
        ("NC-2026-102", Verdict.CONFORME),
        ("NC-2026-103", Verdict.INDETERMINE),
    ],
)
def test_verdicts_bout_en_bout(nc_id, attendu):
    table = load_tolerances(TOLERANCES)
    r = check_conformity(parse_nc_file(INBOX / f"{nc_id}.md"), table)
    assert r.nc_id == nc_id
    assert r.verdict == attendu
    assert r.rules_hash == table.rules_hash
