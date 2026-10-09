"""Schémas de la fausse API ERP.

L'ERP simule un système externe : ce module n'importe rien de shopfloor.
"""

import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

VerdictLiteral = Literal["CONFORME", "NON_CONFORME", "INDETERMINE"]
NonEmptyStr = Annotated[str, StringConstraints(min_length=1)]


class TicketCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    nc_id: NonEmptyStr
    part_ref: NonEmptyStr
    procede: NonEmptyStr
    site: NonEmptyStr
    verdict: VerdictLiteral
    rules_hash: NonEmptyStr
    action_proposee: NonEmptyStr
    sources: list[str]
    valide_par: NonEmptyStr
    commentaire: str | None = None


class Ticket(TicketCreate):
    id: str = Field(pattern=r"^TCK-\d{4,}$")
    statut: Literal["OUVERT"] = "OUVERT"
    created_at: datetime.datetime
