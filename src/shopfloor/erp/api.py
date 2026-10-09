"""Fausse API ERP (FastAPI + SQLite).

L'ERP simule un système externe : ce module n'importe rien de shopfloor hors du paquet erp.
Lancement : ERP_DB=erp.db uvicorn shopfloor.erp.api:app --port 8000
"""

import os
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse

from . import db
from .schemas import Ticket, TicketCreate


def create_app(db_path: str | Path) -> FastAPI:
    app = FastAPI(title="Fausse API ERP (données fictives)", version="0.5.0")
    state = {"ready": False}

    def ensure_db() -> None:
        # Initialisation paresseuse : importer le module ne crée aucun fichier.
        if not state["ready"]:
            db.init_db(db_path)
            state["ready"] = True

    @app.get("/health")
    def health() -> dict:
        return {"status": "ok"}

    @app.post(
        "/tickets",
        status_code=201,
        response_model=Ticket,
        responses={409: {"description": "Un ticket existe déjà pour ce nc_id (existing_id dans le corps)"}},
    )
    def create_ticket(payload: TicketCreate):
        ensure_db()
        try:
            return db.insert_ticket(db_path, payload)
        except db.DuplicateNcError as e:
            return JSONResponse(
                status_code=409,
                content={"detail": str(e), "nc_id": e.nc_id, "existing_id": e.existing_id},
            )

    @app.get("/tickets/{ticket_id}", response_model=Ticket)
    def get_ticket(ticket_id: str):
        ensure_db()
        ticket = db.get_ticket(db_path, ticket_id)
        if ticket is None:
            raise HTTPException(status_code=404, detail=f"ticket inconnu : {ticket_id}")
        return ticket

    @app.get("/tickets", response_model=list[Ticket])
    def list_tickets():
        ensure_db()
        return db.list_tickets(db_path)

    return app


app = create_app(os.getenv("ERP_DB", "erp.db"))
