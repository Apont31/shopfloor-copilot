"""Modèles de données partagés."""

from decimal import Decimal, InvalidOperation
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
