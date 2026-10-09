"""Chargement et validation de config/tolerances.yaml. Aucune logique de conformité ici."""

import hashlib
from pathlib import Path

import yaml
from pydantic import ValidationError

from shopfloor.models import ToleranceSpec, ToleranceTable

ALLOWED_UNITS = frozenset({"mm", "pct", "degC", "deg", "um", "classe", "GU"})


class ToleranceError(ValueError):
    """Fichier de tolérances invalide."""


def load_tolerances(path: str | Path) -> ToleranceTable:
    raw = Path(path).read_bytes()
    rules_hash = hashlib.sha256(raw).hexdigest()
    try:
        data = yaml.safe_load(raw.decode("utf-8"))
    except (UnicodeDecodeError, yaml.YAMLError) as e:
        raise ToleranceError(f"YAML illisible : {e}") from e
    if not isinstance(data, dict) or not isinstance(data.get("specs"), list):
        raise ToleranceError("format attendu : version puis une liste specs")

    try:
        specs = tuple(ToleranceSpec(**s) for s in data["specs"])
        table = ToleranceTable(version=data.get("version"), specs=specs, rules_hash=rules_hash)
    except (TypeError, ValidationError) as e:
        raise ToleranceError(f"spec invalide : {e}") from e

    seen: set[str] = set()
    for s in table.specs:
        if s.id in seen:
            raise ToleranceError(f"id en double : {s.id}")
        seen.add(s.id)
        if s.min is None and s.max is None:
            raise ToleranceError(f"{s.id} : au moins une borne (min ou max) est requise")
        if s.min is not None and s.max is not None and s.min > s.max:
            raise ToleranceError(f"{s.id} : min ({s.min}) > max ({s.max})")
        if s.unite not in ALLOWED_UNITS:
            raise ToleranceError(f"{s.id} : unité inconnue {s.unite!r}")
    return table
