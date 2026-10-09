from decimal import Decimal
from pathlib import Path

import pytest
import yaml

from shopfloor.corpus import read_document
from shopfloor.models import to_decimal
from shopfloor.oracle.loader import ToleranceError, load_tolerances

ROOT = Path(__file__).resolve().parents[1]
TOLERANCES = ROOT / "config" / "tolerances.yaml"
DOCS = ROOT / "data" / "docs"


def spec(**overrides):
    base = {
        "id": "XX-1.cote",
        "part_ref": "XX-1",
        "procede": "tolerie",
        "caracteristique": "cote",
        "unite": "mm",
        "min": 1.0,
        "max": 2.0,
        "resolution": 0.1,
        "source": "PROC-TOL-01",
    }
    base.update(overrides)
    return base


def write_yaml(tmp_path, specs):
    p = tmp_path / "tolerances.yaml"
    p.write_text(yaml.safe_dump({"version": 1, "specs": specs}), encoding="utf-8")
    return p


def test_chargement_reussit():
    table = load_tolerances(TOLERANCES)
    assert table.version == 1


def test_neuf_specs_ids_uniques():
    ids = [s.id for s in load_tolerances(TOLERANCES).specs]
    assert len(ids) == 9
    assert len(set(ids)) == 9


def test_decimal_exact_sans_artefact_flottant():
    specs = {s.id: s for s in load_tolerances(TOLERANCES).specs}
    s = specs["CP-210.epaisseur"]
    assert s.min == Decimal("3.05")
    assert str(s.min) == "3.05"
    assert isinstance(s.max, Decimal) and isinstance(s.resolution, Decimal)


def test_bornes_unilaterales_chargees_a_none():
    specs = {s.id: s for s in load_tolerances(TOLERANCES).specs}
    assert specs["CP-210.porosite"].min is None
    assert specs["CP-210.porosite"].max == Decimal("2.0")


def test_valide_minimal(tmp_path):
    table = load_tolerances(write_yaml(tmp_path, [spec()]))
    assert table.specs[0].min == Decimal("1.0")


def test_min_egal_max_accepte(tmp_path):
    load_tolerances(write_yaml(tmp_path, [spec(min=1.5, max=1.5)]))


@pytest.mark.parametrize(
    "specs",
    [
        pytest.param([spec(min=2.5, max=2.0)], id="min_sup_max"),
        pytest.param([spec(min=None, max=None)], id="aucune_borne"),
        pytest.param([spec(unite="inch")], id="unite_inconnue"),
        pytest.param([spec(), spec()], id="id_double"),
        pytest.param([spec(procede="usinage")], id="procede_inconnu"),
        pytest.param([{k: v for k, v in spec().items() if k != "resolution"}], id="champ_manquant"),
        pytest.param([spec(max="abc")], id="valeur_non_numerique"),
        pytest.param([spec(max=True)], id="valeur_booleenne"),
        pytest.param([spec(max=float("nan"))], id="valeur_nan"),
        pytest.param([spec(max=float("inf"))], id="valeur_infinie"),
    ],
)
def test_yaml_invalide_leve_erreur(tmp_path, specs):
    with pytest.raises(ToleranceError):
        load_tolerances(write_yaml(tmp_path, specs))


def test_yaml_sans_liste_specs_leve_erreur(tmp_path):
    p = tmp_path / "tolerances.yaml"
    p.write_text("version: 1\n", encoding="utf-8")
    with pytest.raises(ToleranceError):
        load_tolerances(p)


def test_chaque_source_est_un_doc_id_existant():
    doc_ids = {read_document(p)[0]["doc_id"] for p in DOCS.glob("*.md")}
    for s in load_tolerances(TOLERANCES).specs:
        assert s.source in doc_ids, s.id


def test_rules_hash_stable_et_sensible_au_contenu(tmp_path):
    h1 = load_tolerances(TOLERANCES).rules_hash
    h2 = load_tolerances(TOLERANCES).rules_hash
    assert h1 == h2
    assert len(h1) == 64
    p = tmp_path / "t.yaml"
    p.write_bytes(TOLERANCES.read_bytes() + b"\n# modif\n")
    assert load_tolerances(p).rules_hash != h1


def test_to_decimal():
    assert to_decimal(None) is None
    assert to_decimal(3.05) == Decimal("3.05")
    assert to_decimal(180) == Decimal("180")
    for invalide in (False, "abc", "nan", float("inf")):
        with pytest.raises(ValueError):
            to_decimal(invalide)


# --- Étape 3 : durcissement du chargeur ---------------------------------------


@pytest.mark.parametrize("version", [2, 0, "1", 1.0, True, None], ids=repr)
def test_version_differente_de_1_refusee(tmp_path, version):
    p = tmp_path / "tolerances.yaml"
    p.write_text(yaml.safe_dump({"version": version, "specs": [spec()]}), encoding="utf-8")
    with pytest.raises(ToleranceError, match="version"):
        load_tolerances(p)


def test_couple_part_ref_caracteristique_en_double_refuse(tmp_path):
    with pytest.raises(ToleranceError, match="en double"):
        load_tolerances(write_yaml(tmp_path, [spec(id="A"), spec(id="B")]))


@pytest.mark.parametrize("resolution", [0, -0.1])
def test_resolution_non_positive_refusee(tmp_path, resolution):
    with pytest.raises(ToleranceError, match="resolution"):
        load_tolerances(write_yaml(tmp_path, [spec(resolution=resolution)]))


@pytest.mark.parametrize(
    "bornes",
    [
        pytest.param({"min": 1.0, "max": 2.0, "nominal": 2.1}, id="au_dessus"),
        pytest.param({"min": 1.0, "max": 2.0, "nominal": 0.9}, id="en_dessous"),
        pytest.param({"min": None, "max": 2.0, "nominal": 2.1}, id="unilaterale_max"),
        pytest.param({"min": 1.0, "max": None, "nominal": 0.9}, id="unilaterale_min"),
    ],
)
def test_nominal_hors_bornes_refuse(tmp_path, bornes):
    with pytest.raises(ToleranceError, match="nominal"):
        load_tolerances(write_yaml(tmp_path, [spec(**bornes)]))


@pytest.mark.parametrize("nominal", [1.0, 2.0, 1.5])
def test_nominal_dans_bornes_incluses_accepte(tmp_path, nominal):
    load_tolerances(write_yaml(tmp_path, [spec(nominal=nominal)]))


@pytest.mark.parametrize(
    "bornes",
    [
        pytest.param({"min": 1.05, "max": 2.0}, id="min"),
        pytest.param({"min": 1.0, "max": 2.05}, id="max"),
    ],
)
def test_borne_non_multiple_de_resolution_refusee(tmp_path, bornes):
    with pytest.raises(ToleranceError, match="multiple"):
        load_tolerances(write_yaml(tmp_path, [spec(**bornes)]))


def test_meme_hash_en_lf_et_en_crlf(tmp_path):
    text = TOLERANCES.read_bytes().replace(b"\r\n", b"\n")
    lf, crlf = tmp_path / "lf.yaml", tmp_path / "crlf.yaml"
    lf.write_bytes(text)
    crlf.write_bytes(text.replace(b"\n", b"\r\n"))
    assert b"\r\n" in crlf.read_bytes()
    assert load_tolerances(lf).rules_hash == load_tolerances(crlf).rules_hash
    assert load_tolerances(lf).rules_hash == load_tolerances(TOLERANCES).rules_hash


def test_get_par_part_ref_et_caracteristique():
    table = load_tolerances(TOLERANCES)
    assert table.get("CP-210", "porosite").id == "CP-210.porosite"
    assert table.get("CP-210", "rugosite") is None
    assert table.get("XX-999", "porosite") is None
    assert table.get("SE-450", "porosite") is None
