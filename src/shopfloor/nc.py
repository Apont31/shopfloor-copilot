"""Lecture déterministe d'une fiche NC (front-matter structuré + description libre). Aucun LLM."""

from pathlib import Path

from pydantic import ValidationError

from shopfloor.corpus import read_document
from shopfloor.models import NCRecord

REQUIRED_FIELDS = ("nc_id", "date", "site", "procede", "part_ref", "lot", "mesures")
MEASURE_FIELDS = ("caracteristique", "valeur", "unite")


class NCParseError(ValueError):
    """Fiche NC illisible : champ manquant ou valeur invalide."""


def parse_nc_file(path: str | Path) -> NCRecord:
    path = Path(path)
    try:
        meta, body = read_document(path)
    except (OSError, UnicodeDecodeError, ValueError) as e:
        raise NCParseError(f"{path.name} : {e}") from e

    missing = [k for k in REQUIRED_FIELDS if meta.get(k) is None]
    if missing:
        raise NCParseError(f"{path.name} : champ(s) manquant(s) : {', '.join(missing)}")

    mesures = meta["mesures"]
    if not isinstance(mesures, list):
        raise NCParseError(f"{path.name} : mesures doit être une liste")
    for i, m in enumerate(mesures):
        if not isinstance(m, dict):
            raise NCParseError(f"{path.name} : mesure n°{i + 1} mal formée")
        missing = [k for k in MEASURE_FIELDS if m.get(k) is None]
        if missing:
            raise NCParseError(f"{path.name} : mesure n°{i + 1}, champ(s) manquant(s) : {', '.join(missing)}")
        # Seul un nombre YAML est accepté : "2,8" ou "2.8" entre guillemets sont refusés.
        v = m["valeur"]
        if isinstance(v, bool) or not isinstance(v, (int, float)):
            raise NCParseError(f"{path.name} : mesure n°{i + 1}, valeur non numérique : {v!r}")

    try:
        return NCRecord(
            **{k: meta[k] for k in REQUIRED_FIELDS if k != "mesures"},
            mesures=tuple(mesures),
            description=body.strip(),
        )
    except ValidationError as e:
        raise NCParseError(f"{path.name} : {e}") from e
