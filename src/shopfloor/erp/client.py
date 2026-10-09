"""Client HTTP de la fausse API ERP.

Aucune exception httpx brute ne remonte : tout est traduit en ErpError ou ses sous-classes.
"""

import httpx
from pydantic import ValidationError

from .schemas import Ticket, TicketCreate


class ErpError(Exception):
    """Erreur générique de l'ERP."""

    def __init__(self, message: str, status_code: int | None = None):
        super().__init__(message)
        self.status_code = status_code


class ErpUnavailableError(ErpError):
    """ERP injoignable (connexion refusée, timeout, réseau)."""


class ErpConflictError(ErpError):
    """Un ticket existe déjà pour ce nc_id."""

    def __init__(self, message: str, existing_id: str | None):
        super().__init__(message, status_code=409)
        self.existing_id = existing_id


class ErpClient:
    def __init__(self, base_url: str, timeout: float = 5.0, http_client: httpx.Client | None = None):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        # Un client injecté (TestClient, client partagé) garde son propre timeout.
        self._http = http_client if http_client is not None else httpx.Client(timeout=timeout)

    def _request(self, method: str, path: str, **kwargs) -> httpx.Response:
        try:
            return self._http.request(method, f"{self.base_url}{path}", **kwargs)
        except (httpx.TimeoutException, httpx.NetworkError) as e:
            raise ErpUnavailableError(f"ERP injoignable : {e.__class__.__name__}: {e}") from None
        except httpx.HTTPError as e:
            raise ErpError(f"erreur HTTP : {e.__class__.__name__}: {e}") from None

    @staticmethod
    def _parse_ticket(resp: httpx.Response) -> Ticket:
        try:
            return Ticket.model_validate(resp.json())
        except (ValueError, ValidationError) as e:
            raise ErpError(f"réponse ERP invalide : {e}", status_code=resp.status_code) from None

    @staticmethod
    def _detail(resp: httpx.Response):
        try:
            return resp.json()
        except ValueError:
            return resp.text

    def create_ticket(self, payload: TicketCreate | dict) -> Ticket:
        try:
            body = TicketCreate.model_validate(payload).model_dump(mode="json")
        except ValidationError as e:
            raise ErpError(f"ticket invalide : {e}") from None
        resp = self._request("POST", "/tickets", json=body)
        if resp.status_code == 201:
            return self._parse_ticket(resp)
        if resp.status_code == 409:
            detail = self._detail(resp)
            existing_id = detail.get("existing_id") if isinstance(detail, dict) else None
            raise ErpConflictError(f"ticket déjà existant : {existing_id}", existing_id=existing_id)
        raise ErpError(f"création refusée ({resp.status_code}) : {self._detail(resp)}", resp.status_code)

    def get_ticket(self, ticket_id: str) -> Ticket:
        resp = self._request("GET", f"/tickets/{ticket_id}")
        if resp.status_code == 200:
            return self._parse_ticket(resp)
        raise ErpError(f"lecture impossible ({resp.status_code}) : {self._detail(resp)}", resp.status_code)
