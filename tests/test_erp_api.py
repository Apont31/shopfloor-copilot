import ast
import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from shopfloor.erp.api import create_app

ERP_DIR = Path(__file__).resolve().parents[1] / "src" / "shopfloor" / "erp"


def payload(**overrides):
    data = {
        "nc_id": "NC-TEST-001",
        "part_ref": "CP-210",
        "procede": "composite",
        "site": "Site-Fictif-A",
        "verdict": "NON_CONFORME",
        "rules_hash": "abc123",
        "action_proposee": "Reprise du stratifié (fictif).",
        "sources": ["PROC-001", "NC-2025-004"],
        "valide_par": "Opérateur fictif",
        "commentaire": None,
    }
    data.update(overrides)
    return data


@pytest.fixture
def db_path(tmp_path):
    return tmp_path / "erp.db"


@pytest.fixture
def client(db_path):
    return TestClient(create_app(db_path))


def test_health(client):
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


def test_creation_201(client):
    resp = client.post("/tickets", json=payload())
    assert resp.status_code == 201
    body = resp.json()
    assert re.fullmatch(r"TCK-\d{4,}", body["id"])
    assert body["id"] == "TCK-0001"
    assert body["statut"] == "OUVERT"
    assert body["nc_id"] == "NC-TEST-001"
    assert body["sources"] == ["PROC-001", "NC-2025-004"]
    assert body["created_at"]


def test_ids_successifs(client):
    a = client.post("/tickets", json=payload(nc_id="NC-A")).json()
    b = client.post("/tickets", json=payload(nc_id="NC-B")).json()
    assert (a["id"], b["id"]) == ("TCK-0001", "TCK-0002")


def test_get_par_id(client):
    created = client.post("/tickets", json=payload()).json()
    resp = client.get(f"/tickets/{created['id']}")
    assert resp.status_code == 200
    assert resp.json() == created


def test_get_id_inconnu_404(client):
    assert client.get("/tickets/TCK-9999").status_code == 404


def test_meme_nc_id_409(client):
    first = client.post("/tickets", json=payload()).json()
    resp = client.post("/tickets", json=payload(action_proposee="Autre action."))
    assert resp.status_code == 409
    assert resp.json()["existing_id"] == first["id"]
    assert len(client.get("/tickets").json()) == 1


def test_verdict_invalide_422(client):
    assert client.post("/tickets", json=payload(verdict="OK")).status_code == 422


def test_champ_manquant_422(client):
    data = payload()
    del data["valide_par"]
    assert client.post("/tickets", json=data).status_code == 422


def test_champ_vide_422(client):
    assert client.post("/tickets", json=payload(nc_id="")).status_code == 422


def test_liste(client):
    assert client.get("/tickets").json() == []
    client.post("/tickets", json=payload(nc_id="NC-A"))
    client.post("/tickets", json=payload(nc_id="NC-B"))
    resp = client.get("/tickets")
    assert resp.status_code == 200
    assert [t["nc_id"] for t in resp.json()] == ["NC-A", "NC-B"]


def test_persistance(db_path):
    created = TestClient(create_app(db_path)).post("/tickets", json=payload()).json()
    other = TestClient(create_app(db_path))
    assert other.get(f"/tickets/{created['id']}").json() == created


def test_creation_app_ne_cree_pas_de_fichier(tmp_path):
    path = tmp_path / "jamais.db"
    create_app(path)
    assert not path.exists()


@pytest.mark.parametrize("module", sorted(ERP_DIR.glob("*.py")), ids=lambda p: p.name)
def test_erp_isole_de_shopfloor(module):
    """L'ERP simule un système externe : aucun import de shopfloor hors du paquet erp."""
    tree = ast.parse(module.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names = [a.name for a in node.names]
        elif isinstance(node, ast.ImportFrom):
            if node.level > 0:
                assert node.level == 1, f"{module.name} remonte hors du paquet erp"
                continue
            names = [node.module or ""]
        else:
            continue
        for name in names:
            assert not name.startswith("shopfloor") or name.startswith("shopfloor.erp"), (
                f"{module.name} importe {name}"
            )
