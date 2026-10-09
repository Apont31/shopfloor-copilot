"""Régénère les tableaux de tolérances des procédures depuis config/tolerances.yaml.

Usage :
    python scripts/sync_tolerances.py            # réécrit les tableaux entre les marqueurs
    python scripts/sync_tolerances.py --check    # code 1 et liste des écarts si un document n'est plus aligné
"""

import argparse
import sys
from decimal import Decimal
from pathlib import Path

from shopfloor.corpus import split_front_matter
from shopfloor.models import ToleranceSpec
from shopfloor.oracle.loader import load_tolerances

ROOT = Path(__file__).resolve().parents[1]
START = "<!-- TOLERANCES:START -->"
END = "<!-- TOLERANCES:END -->"


def fmt(value: Decimal | None, resolution: Decimal) -> str:
    """Affiche la valeur au pas de la résolution (3.2 -> 3.20 si résolution 0.01)."""
    if value is None:
        return "—"
    q = value.quantize(resolution)
    return str(q if q == value else value)


def render_table(specs: list[ToleranceSpec]) -> str:
    lines = [
        "| Caractéristique | Unité | Nominal | Min | Max | Résolution |",
        "|---|---|---|---|---|---|",
    ]
    for s in specs:
        lines.append(
            f"| {s.caracteristique} | {s.unite} | {fmt(s.nominal, s.resolution)} | "
            f"{fmt(s.min, s.resolution)} | {fmt(s.max, s.resolution)} | {s.resolution} |"
        )
    return "\n".join(lines)


def sync(tolerances: Path, docs: Path, check: bool) -> tuple[list[str], list[str]]:
    """Renvoie (écarts, fichiers réécrits). En mode check, rien n'est écrit."""
    table = load_tolerances(tolerances)
    by_source: dict[str, list[ToleranceSpec]] = {}
    for s in table.specs:
        by_source.setdefault(s.source, []).append(s)

    report: list[str] = []
    rewritten: list[str] = []
    seen_sources = set()
    for path in sorted(docs.glob("*.md")):
        raw = path.read_bytes().decode("utf-8")
        meta, _ = split_front_matter(raw)
        doc_id = meta.get("doc_id")
        has_markers = START in raw and END in raw
        if doc_id not in by_source:
            if has_markers:
                report.append(f"{path.name} : marqueurs présents mais aucune spec n'a source={doc_id}")
            continue
        seen_sources.add(doc_id)
        if not has_markers:
            report.append(f"{path.name} : marqueurs {START} / {END} absents")
            continue

        nl = "\r\n" if "\r\n" in raw else "\n"
        before, rest = raw.split(START, 1)
        current, after = rest.split(END, 1)
        expected = nl + render_table(by_source[doc_id]).replace("\n", nl) + nl
        if current == expected:
            continue
        if check:
            report.append(f"{path.name} : tableau désaligné avec {tolerances.name}")
        else:
            path.write_bytes((before + START + expected + END + after).encode("utf-8"))
            rewritten.append(f"{path.name} : tableau régénéré")

    for source in sorted(set(by_source) - seen_sources):
        report.append(f"source {source} : aucun document avec ce doc_id dans {docs}")
    return report, rewritten


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--check", action="store_true", help="vérifie sans écrire")
    parser.add_argument("--tolerances", type=Path, default=ROOT / "config" / "tolerances.yaml")
    parser.add_argument("--docs", type=Path, default=ROOT / "data" / "docs")
    args = parser.parse_args(argv)

    report, rewritten = sync(args.tolerances, args.docs, args.check)
    for line in rewritten + report:
        print(line)
    if report:
        print(f"{len(report)} écart(s).")
        return 1
    print("OK : documents alignés sur le YAML.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
