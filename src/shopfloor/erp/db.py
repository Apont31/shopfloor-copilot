"""Stockage SQLite de la fausse API ERP (module standard sqlite3, sans ORM)."""

import datetime
import json
import sqlite3
from contextlib import closing
from pathlib import Path

from .schemas import Ticket, TicketCreate

SCHEMA = """
CREATE TABLE IF NOT EXISTS tickets (
    seq INTEGER PRIMARY KEY AUTOINCREMENT,
    id TEXT UNIQUE,
    nc_id TEXT NOT NULL UNIQUE,
    part_ref TEXT NOT NULL,
    procede TEXT NOT NULL,
    site TEXT NOT NULL,
    verdict TEXT NOT NULL,
    rules_hash TEXT NOT NULL,
    action_proposee TEXT NOT NULL,
    sources TEXT NOT NULL,
    valide_par TEXT NOT NULL,
    commentaire TEXT,
    statut TEXT NOT NULL,
    created_at TEXT NOT NULL
)
"""

COLUMNS = (
    "id, nc_id, part_ref, procede, site, verdict, rules_hash, action_proposee, "
    "sources, valide_par, commentaire, statut, created_at"
)


class DuplicateNcError(Exception):
    """Un ticket existe déjà pour ce nc_id."""

    def __init__(self, nc_id: str, existing_id: str):
        super().__init__(f"un ticket existe déjà pour {nc_id} : {existing_id}")
        self.nc_id = nc_id
        self.existing_id = existing_id


def connect(db_path: str | Path) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def init_db(db_path: str | Path) -> None:
    with closing(connect(db_path)) as conn, conn:
        conn.execute(SCHEMA)


def _row_to_ticket(row: sqlite3.Row) -> Ticket:
    data = dict(row)
    data["sources"] = json.loads(data["sources"])
    return Ticket.model_validate(data)


def insert_ticket(db_path: str | Path, payload: TicketCreate) -> Ticket:
    created_at = datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")
    with closing(connect(db_path)) as conn:
        try:
            with conn:
                cur = conn.execute(
                    "INSERT INTO tickets (nc_id, part_ref, procede, site, verdict, rules_hash, "
                    "action_proposee, sources, valide_par, commentaire, statut, created_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'OUVERT', ?)",
                    (
                        payload.nc_id,
                        payload.part_ref,
                        payload.procede,
                        payload.site,
                        payload.verdict,
                        payload.rules_hash,
                        payload.action_proposee,
                        json.dumps(payload.sources, ensure_ascii=False),
                        payload.valide_par,
                        payload.commentaire,
                        created_at,
                    ),
                )
                ticket_id = f"TCK-{cur.lastrowid:04d}"
                conn.execute("UPDATE tickets SET id = ? WHERE seq = ?", (ticket_id, cur.lastrowid))
        except sqlite3.IntegrityError:
            existing = _get_by_nc_id(conn, payload.nc_id)
            if existing is None:
                raise
            raise DuplicateNcError(payload.nc_id, existing.id) from None
        return _get_by_id(conn, ticket_id)


def _get_by_id(conn: sqlite3.Connection, ticket_id: str) -> Ticket | None:
    row = conn.execute(f"SELECT {COLUMNS} FROM tickets WHERE id = ?", (ticket_id,)).fetchone()
    return _row_to_ticket(row) if row else None


def _get_by_nc_id(conn: sqlite3.Connection, nc_id: str) -> Ticket | None:
    row = conn.execute(f"SELECT {COLUMNS} FROM tickets WHERE nc_id = ?", (nc_id,)).fetchone()
    return _row_to_ticket(row) if row else None


def get_ticket(db_path: str | Path, ticket_id: str) -> Ticket | None:
    with closing(connect(db_path)) as conn:
        return _get_by_id(conn, ticket_id)


def get_ticket_by_nc_id(db_path: str | Path, nc_id: str) -> Ticket | None:
    with closing(connect(db_path)) as conn:
        return _get_by_nc_id(conn, nc_id)


def list_tickets(db_path: str | Path) -> list[Ticket]:
    with closing(connect(db_path)) as conn:
        rows = conn.execute(f"SELECT {COLUMNS} FROM tickets ORDER BY seq").fetchall()
        return [_row_to_ticket(r) for r in rows]
