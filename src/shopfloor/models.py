"""Modèles de données partagés."""

import datetime
from decimal import Decimal, InvalidOperation
from enum import Enum
from typing import Literal

from pydantic import BaseModel, ConfigDict, field_validator


def to_decimal(v):
    """Convertit en Decimal via str() pour éviter les artefacts de flottants (3.05 reste 3.05)."""
    if v is None:
        return None
    if isinstance(v, bool):
        raise ValueError("un booléen n'est pas une valeur numérique")
    try:
        d = v if isinstance(v, Decimal) else Decimal(str(v))
    except InvalidOperation:
        raise ValueError(f"valeur non numérique : {v!r}") from None
    if not d.is_finite():
        raise ValueError(f"valeur non finie : {v!r}")
    return d


class ToleranceSpec(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str
    part_ref: str
    procede: Literal["composite", "tolerie", "peinture"]
    caracteristique: str
    unite: str
    nominal: Decimal | None = None
    min: Decimal | None
    max: Decimal | None
    resolution: Decimal
    source: str

    @field_validator("nominal", "min", "max", "resolution", mode="before")
    @classmethod
    def convert_decimals(cls, v):
        return to_decimal(v)


class ToleranceTable(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    version: int
    specs: tuple[ToleranceSpec, ...]
    rules_hash: str

    def get(self, part_ref: str, caracteristique: str) -> ToleranceSpec | None:
        for s in self.specs:
            if s.part_ref == part_ref and s.caracteristique == caracteristique:
                return s
        return None

    def has_part_ref(self, part_ref: str) -> bool:
        return any(s.part_ref == part_ref for s in self.specs)


class Verdict(str, Enum):
    CONFORME = "CONFORME"
    NON_CONFORME = "NON_CONFORME"
    INDETERMINE = "INDETERMINE"


class Measurement(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    caracteristique: str
    valeur: Decimal
    unite: str

    @field_validator("valeur", mode="before")
    @classmethod
    def convert_decimal(cls, v):
        if v is None:
            raise ValueError("valeur manquante")
        return to_decimal(v)


class NCRecord(BaseModel):
    """Fiche NC lue de façon déterministe (front-matter + corps)."""

    model_config = ConfigDict(frozen=True, extra="forbid", coerce_numbers_to_str=True)

    nc_id: str
    date: datetime.date
    site: str
    procede: str
    part_ref: str
    lot: str
    mesures: tuple[Measurement, ...]
    description: str


class MeasureResult(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    caracteristique: str
    valeur: Decimal
    unite: str
    spec_id: str | None
    min: Decimal | None
    max: Decimal | None
    ecart: Decimal | None
    statut: Verdict
    motif: str


class OracleResult(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    nc_id: str
    verdict: Verdict
    details: tuple[MeasureResult, ...]
    rules_hash: str
