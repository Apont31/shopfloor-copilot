"""Journal des traitements (SQLite) : une ligne par fiche, pour la file de validation et le futur tableau de pilotage.

Écrit uniquement par la couche service (shopfloor.service), jamais par les nœuds du graphe.
"""

import datetime
import sqlite3
import threading
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict

Statut = Literal["en_attente", "approuve", "modifie", "rejete", "erreur", "doublon"]
Origine = Literal["llm", "deterministe", "aucune"]
STATUTS_DECISION = ("approuve", "modifie", "rejete", "erreur")
STATUTS_ERREUR = ("erreur", "doublon")
FILTRES = ("statut", "site", "procede", "verdict", "origine")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    nc_id TEXT NOT NULL UNIQUE,
    fichier TEXT NOT NULL,
    site TEXT,
    procede TEXT,
    part_ref TEXT,
    verdict TEXT CHECK (verdict IN ('CONFORME', 'NON_CONFORME', 'INDETERMINE')),
    origine TEXT NOT NULL CHECK (origine IN ('llm', 'deterministe', 'aucune')),
    guard_ok INTEGER CHECK (guard_ok IN (0, 1)),
    llm_ms INTEGER,
    statut TEXT NOT NULL
        CHECK (statut IN ('en_attente', 'approuve', 'modifie', 'rejete', 'erreur', 'doublon')),
    ticket_id TEXT,
    erreur TEXT,
    created_at TEXT NOT NULL,
    decided_at TEXT,
    decided_by TEXT
)
"""


class JournalError(Exception):
    """Écriture refusée : fiche déjà journalisée, ou décision sur une fiche qui n'est pas en attente."""


class Run(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    nc_id: str
    fichier: str
    site: str | None
    procede: str | None
    part_ref: str | None
    verdict: Literal["CONFORME", "NON_CONFORME", "INDETERMINE"] | None
    origine: Origine
    guard_ok: bool | None  # None : pas de proposition du LLM à contrôler
    llm_ms: int | None  # None : aucun appel au LLM
    statut: Statut
    ticket_id: str | None
    erreur: str | None
    created_at: datetime.datetime
    decided_at: datetime.datetime | None
    decided_by: str | None


def _now() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")


class Journal:
    """Accès au journal. Connexion partagée entre threads (Streamlit), protégée par un verrou."""

    def __init__(self, path: str | Path):
        self.conn = sqlite3.connect(str(path), check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.lock = threading.Lock()
        with self.lock, self.conn:
            self.conn.execute(_SCHEMA)

    def close(self) -> None:
        self.conn.close()

    def __enter__(self) -> "Journal":
        return self

    def __exit__(self, *exc_info) -> None:
        self.close()

    def _insert(self, **values) -> Run:
        values["created_at"] = _now()
        cols = ", ".join(values)
        marks = ", ".join("?" for _ in values)
        try:
            with self.lock, self.conn:
                self.conn.execute(f"INSERT INTO runs ({cols}) VALUES ({marks})", tuple(values.values()))
        except sqlite3.IntegrityError as e:
            if self.get_run(values["nc_id"]) is not None:
                raise JournalError(f"{values['nc_id']} est déjà journalisée") from e
            raise
        return self.get_run(values["nc_id"])

    def record_pending(
        self,
        *,
        nc_id: str,
        fichier: str,
        site: str,
        procede: str,
        part_ref: str,
        verdict: str,
        origine: Origine,
        guard_ok: bool | None,
        llm_ms: int | None,
    ) -> Run:
        """Fiche traitée jusqu'à la validation humaine : statut en_attente."""
        return self._insert(
            nc_id=nc_id, fichier=fichier, site=site, procede=procede, part_ref=part_ref, verdict=verdict,
            origine=origine, guard_ok=guard_ok, llm_ms=llm_ms, statut="en_attente",
        )

    def record_error(
        self,
        *,
        nc_id: str,
        fichier: str,
        erreur: str,
        statut: Literal["erreur", "doublon"] = "erreur",
        site: str | None = None,
        procede: str | None = None,
        part_ref: str | None = None,
        verdict: str | None = None,
        ticket_id: str | None = None,
    ) -> Run:
        """Traitement arrêté avant la validation humaine (erreur) ou fiche déjà portée par un ticket (doublon)."""
        if statut not in STATUTS_ERREUR:
            raise ValueError(f"statut d'erreur invalide : {statut}")
        return self._insert(
            nc_id=nc_id, fichier=fichier, site=site, procede=procede, part_ref=part_ref, verdict=verdict,
            origine="aucune", guard_ok=None, llm_ms=None, statut=statut, ticket_id=ticket_id, erreur=erreur,
        )

    def record_decision(
        self,
        nc_id: str,
        *,
        statut: Literal["approuve", "modifie", "rejete", "erreur"],
        decided_by: str,
        ticket_id: str | None = None,
        erreur: str | None = None,
    ) -> Run:
        """Décision humaine sur une fiche en attente. statut erreur : décision prise mais ticket non créé."""
        if statut not in STATUTS_DECISION:
            raise ValueError(f"statut de décision invalide : {statut}")
        with self.lock, self.conn:
            cur = self.conn.execute(
                "UPDATE runs SET statut = ?, ticket_id = ?, erreur = ?, decided_at = ?, decided_by = ? "
                "WHERE nc_id = ? AND statut = 'en_attente'",
                (statut, ticket_id, erreur, _now(), decided_by, nc_id),
            )
        if cur.rowcount != 1:
            raise JournalError(f"aucune fiche en attente pour {nc_id}")
        return self.get_run(nc_id)

    def delete_error(self, nc_id: str) -> None:
        """Efface la ligne d'une fiche en erreur : elle redeviendra traitable (relance)."""
        with self.lock, self.conn:
            cur = self.conn.execute("DELETE FROM runs WHERE nc_id = ? AND statut = 'erreur'", (nc_id,))
        if cur.rowcount != 1:
            raise JournalError(f"aucune fiche en erreur pour {nc_id}")

    def get_run(self, nc_id: str) -> Run | None:
        with self.lock:
            row = self.conn.execute("SELECT * FROM runs WHERE nc_id = ?", (nc_id,)).fetchone()
        return None if row is None else _to_run(row)

    def count_by_statut(self) -> dict[str, int]:
        """Nombre de fiches par statut, sans lire les lignes (compteurs de l'interface)."""
        with self.lock:
            rows = self.conn.execute("SELECT statut, COUNT(*) FROM runs GROUP BY statut").fetchall()
        return {statut: n for statut, n in rows}

    def fingerprint(self) -> tuple:
        """Empreinte du journal : change dès qu'une fiche est ajoutée, décidée ou effacée, quelle que soit la
        session ou le processus. Sert à invalider les données gardées en cache par l'interface."""
        with self.lock:
            row = self.conn.execute(
                "SELECT COUNT(*), COALESCE(MAX(id), 0), COALESCE(SUM(statut = 'en_attente'), 0), MAX(decided_at) "
                "FROM runs"
            ).fetchone()
        return tuple(row)

    def list_runs(self, **filtres: str | None) -> list[Run]:
        """Toutes les fiches, de la plus ancienne à la plus récente. Filtres par égalité : statut, site,
        procede, verdict, origine (une valeur None est ignorée)."""
        inconnus = set(filtres) - set(FILTRES)
        if inconnus:
            raise ValueError(f"filtre(s) inconnu(s) : {', '.join(sorted(inconnus))}")
        actifs = {k: v for k, v in filtres.items() if v is not None}
        where = " AND ".join(f"{k} = ?" for k in actifs)
        sql = "SELECT * FROM runs" + (f" WHERE {where}" if where else "") + " ORDER BY id"
        with self.lock:
            rows = self.conn.execute(sql, tuple(actifs.values())).fetchall()
        return [_to_run(r) for r in rows]


def _to_run(row: sqlite3.Row) -> Run:
    data = {k: row[k] for k in row.keys() if k != "id"}
    if data["guard_ok"] is not None:
        data["guard_ok"] = bool(data["guard_ok"])
    return Run.model_validate(data)
