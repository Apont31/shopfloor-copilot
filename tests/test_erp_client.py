from typing import get_args

import pytest
from fastapi.testclient import TestClient

from shopfloor.erp.api import create_app
from shopfloor.erp.client import ErpClient, ErpConflictError, ErpError, ErpUnavailableError
from shopfloor.erp.schemas import Ticket, TicketCreate
from shopfloor.models import Verdict


def payload(**overrides):
    data = {
        "nc_id": "NC-TEST-001",
        "part_ref": "CP-210",
        "procede": "composite",
        "site": "Site-Fictif-A",
        "verdict": "NON_CONFORME",
        "rules_hash": "abc123",
        "action_proposee": "Reprise du stratifié (fictif).",
        "sources": ["PROC-001"],
        "valide_par": "Opérateur fictif",
    }
    data.update(overrides)
    return TicketCreate(**data)


@pytest.fixture
def erp(tmp_path):
    return ErpClient("http://testserver", http_client=TestClient(create_app(tmp_path / "erp.db")))


def test_creation_et_lecture(erp):
    ticket = erp.create_ticket(payload())
    assert isinstance(ticket, Ticket)
    assert ticket.id == "TCK-0001"
    assert ticket.statut == "OUVERT"
    assert erp.get_ticket(ticket.id) == ticket


def test_creation_depuis_dict(erp):
    ticket = erp.create_ticket(payload().model_dump())
    assert ticket.nc_id == "NC-TEST-001"


def test_conflit_409(erp):
    first = erp.create_ticket(payload())
    with pytest.raises(ErpConflictError) as exc:
        erp.create_ticket(payload())
    assert exc.value.existing_id == first.id
    assert exc.value.status_code == 409


def test_id_inconnu_erp_error(erp):
    with pytest.raises(ErpError) as exc:
        erp.get_ticket("TCK-9999")
    assert exc.value.status_code == 404
    assert not isinstance(exc.value, (ErpConflictError, ErpUnavailableError))


def test_payload_invalide_erp_error(erp):
    with pytest.raises(ErpError):
        erp.create_ticket({"nc_id": "NC-X"})


def test_find_by_nc_id(erp):
    assert erp.find_by_nc_id("NC-2026-101") is None
    created = erp.create_ticket(payload())
    assert erp.find_by_nc_id(created.nc_id) == created
    assert erp.find_by_nc_id("NC-INCONNUE") is None


def test_find_by_nc_id_injoignable():
    with pytest.raises(ErpUnavailableError):
        ErpClient("http://127.0.0.1:9", timeout=0.5).find_by_nc_id("NC-2026-101")


def test_api_injoignable():
    erp = ErpClient("http://127.0.0.1:9", timeout=0.5)
    with pytest.raises(ErpUnavailableError):
        erp.create_ticket(payload())
    with pytest.raises(ErpUnavailableError):
        erp.get_ticket("TCK-0001")


def test_health(erp):
    assert erp.health() is None


def test_health_injoignable():
    with pytest.raises(ErpUnavailableError):
        ErpClient("http://127.0.0.1:9", timeout=0.5).health()


def test_list_tickets(erp):
    assert erp.list_tickets() == []
    first = erp.create_ticket(payload())
    second = erp.create_ticket(payload(nc_id="NC-TEST-002"))
    assert erp.list_tickets() == [first, second]


def test_list_tickets_injoignable():
    with pytest.raises(ErpUnavailableError):
        ErpClient("http://127.0.0.1:9", timeout=0.5).list_tickets()


def test_verdict_literal_aligne_sur_enum():
    """Seul test autorisé à importer shopfloor.models : l'ERP ne dépend pas du cœur."""
    literal = TicketCreate.model_fields["verdict"].annotation
    assert sorted(get_args(literal)) == sorted(v.value for v in Verdict)


def test_close_et_context_manager():
    with ErpClient("http://127.0.0.1:9", timeout=0.5) as erp:
        assert not erp._http.is_closed
    assert erp._http.is_closed


def test_close_ne_ferme_pas_un_client_injecte(tmp_path):
    http = TestClient(create_app(tmp_path / "erp.db"))
    with ErpClient("http://testserver", http_client=http) as erp:
        erp.create_ticket(payload())
    assert not http.is_closed
    assert http.get("/health").status_code == 200
