"""Oracle de conformité : seul juge de la conformité (décision D1).

Fonction pure : aucune I/O, aucun état global, aucun LLM. Bornes incluses, comparaisons en Decimal.
"""

from decimal import Decimal

from shopfloor.models import (
    Measurement,
    MeasureResult,
    NCRecord,
    OracleResult,
    ToleranceTable,
    Verdict,
)


def check_conformity(nc: NCRecord, tolerances: ToleranceTable) -> OracleResult:
    details = tuple(_check_measure(nc, m, tolerances) for m in nc.mesures)
    return OracleResult(
        nc_id=nc.nc_id,
        verdict=_aggregate(details),
        details=details,
        rules_hash=tolerances.rules_hash,
    )


def _check_measure(nc: NCRecord, m: Measurement, tolerances: ToleranceTable) -> MeasureResult:
    spec = tolerances.get(nc.part_ref, m.caracteristique)
    base = {"caracteristique": m.caracteristique, "valeur": m.valeur, "unite": m.unite}

    if spec is None:
        return MeasureResult(
            **base, spec_id=None, min=None, max=None, ecart=None,
            statut=Verdict.INDETERMINE,
            motif=f"caractéristique inconnue : aucune tolérance pour {nc.part_ref} / {m.caracteristique}",
        )

    bounds = {"spec_id": spec.id, "min": spec.min, "max": spec.max}
    if m.unite != spec.unite:
        return MeasureResult(
            **base, **bounds, ecart=None,
            statut=Verdict.INDETERMINE,
            motif=f"unité différente : mesure en {m.unite}, tolérance en {spec.unite}",
        )
    if spec.procede != nc.procede:
        return MeasureResult(
            **base, **bounds, ecart=None,
            statut=Verdict.INDETERMINE,
            motif=f"procédé différent : fiche {nc.procede}, tolérance {spec.procede}",
        )

    if spec.max is not None and m.valeur > spec.max:
        return MeasureResult(
            **base, **bounds, ecart=m.valeur - spec.max,
            statut=Verdict.NON_CONFORME,
            motif=f"au-dessus du max ({spec.max} {spec.unite})",
        )
    if spec.min is not None and m.valeur < spec.min:
        return MeasureResult(
            **base, **bounds, ecart=m.valeur - spec.min,
            statut=Verdict.NON_CONFORME,
            motif=f"en dessous du min ({spec.min} {spec.unite})",
        )
    return MeasureResult(
        **base, **bounds, ecart=Decimal(0),
        statut=Verdict.CONFORME,
        motif="dans la tolérance (bornes incluses)",
    )


def _aggregate(details: tuple[MeasureResult, ...]) -> Verdict:
    statuts = {d.statut for d in details}
    if Verdict.NON_CONFORME in statuts:
        return Verdict.NON_CONFORME
    if not details or Verdict.INDETERMINE in statuts:
        return Verdict.INDETERMINE
    return Verdict.CONFORME
