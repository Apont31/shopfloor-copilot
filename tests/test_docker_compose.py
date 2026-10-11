"""docker-compose.yml : lecture YAML et règles de sécurité, sans lancer Docker."""

from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
COMPOSE = ROOT / "docker-compose.yml"
IMAGE = "ghcr.io/apont31/shopfloor-copilot:latest"


@pytest.fixture(scope="module")
def services() -> dict:
    return yaml.safe_load(COMPOSE.read_text(encoding="utf-8"))["services"]


def test_trois_services(services):
    assert set(services) == {"erp", "ui", "ingest"}


@pytest.mark.parametrize("nom", ["erp", "ui", "ingest"])
def test_image_ghcr_avec_build_local(services, nom):
    assert services[nom]["image"] == IMAGE
    assert services[nom]["build"] == "."


@pytest.mark.parametrize("nom, port", [("erp", 8000), ("ui", 8501)])
def test_ports_publies_sur_127_0_0_1(services, nom, port):
    assert services[nom]["ports"] == [f"127.0.0.1:{port}:{port}"]


def test_aucun_port_hors_127_0_0_1(services):
    for svc in services.values():
        for p in svc.get("ports", []):
            assert str(p).startswith("127.0.0.1:"), p


def test_ingest_dans_le_profil_tools(services):
    assert services["ingest"]["profiles"] == ["tools"]
    assert services["ingest"]["command"] == ["python", "-m", "shopfloor.cli", "ingest"]
    assert "ports" not in services["ingest"]


@pytest.mark.parametrize("nom", ["erp", "ui"])
def test_services_permanents_hors_profil(services, nom):
    assert "profiles" not in services[nom]


def test_ui_attend_erp_sain_et_joint_ollama_de_l_hote(services):
    ui = services["ui"]
    assert ui["depends_on"] == {"erp": {"condition": "service_healthy"}}
    assert ui["environment"]["ERP_URL"] == "http://erp:8000"
    assert ui["environment"]["OLLAMA_HOST"] == "http://host.docker.internal:11434"
    assert ui["environment"]["STREAMLIT_SERVER_ADDRESS"] == "0.0.0.0"
    assert "host.docker.internal:host-gateway" in ui["extra_hosts"]


def test_ingest_memes_volumes_et_ollama_que_ui(services):
    ui, ingest = services["ui"], services["ingest"]
    assert ingest["volumes"] == ui["volumes"]
    assert ingest["environment"]["OLLAMA_HOST"] == ui["environment"]["OLLAMA_HOST"]
    assert "./data:/app/data:ro" in ui["volumes"]


@pytest.mark.parametrize("nom, chemin", [("erp", "/health"), ("ui", "/_stcore/health")])
def test_healthchecks(services, nom, chemin):
    assert any(chemin in part for part in services[nom]["healthcheck"]["test"])
