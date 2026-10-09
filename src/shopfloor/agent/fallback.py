"""Propositions déterministes : sans LLM, ou en repli quand la sortie du LLM est rejetée (D5)."""

from shopfloor.models import ActionProposal, OracleResult, Verdict

_TEXTES = {
    Verdict.CONFORME: dict(
        resume="Toutes les mesures de la fiche respectent les tolérances de référence selon l'oracle.",
        cause_probable="Aucun écart mesuré : signalement probablement sans objet (fausse alerte).",
        action_corrective=(
            "Escalade au responsable qualité pour une clôture sans suite (fausse alerte) : "
            "confirmer les mesures, lever l'isolement de la pièce et clore la fiche."
        ),
        sources=[],
    ),
    Verdict.INDETERMINE: dict(
        resume="L'oracle ne peut pas trancher : au moins une caractéristique est hors référentiel de tolérances.",
        cause_probable="Caractéristique, unité ou référence pièce sans tolérance définie dans le référentiel.",
        action_corrective=(
            "Escalade au service qualité (caractéristique hors référentiel) selon PROC-QUA-01 : "
            "maintenir la pièce isolée en zone NC, faire définir la tolérance applicable, puis réévaluer la fiche."
        ),
        sources=["PROC-QUA-01"],
    ),
    Verdict.NON_CONFORME: dict(
        resume="L'oracle a établi au moins une mesure hors tolérance. Aucune proposition automatique validée.",
        cause_probable="Cause à analyser par le service qualité.",
        action_corrective=(
            "Escalade au responsable qualité selon PROC-QUA-01 : maintenir la pièce isolée et étiquetée "
            "en zone NC, analyser la cause racine, puis choisir la décision (retouche, rebut ou dérogation) "
            "avec validation par la personne désignée."
        ),
        sources=["PROC-QUA-01"],
    ),
}


def default_proposal(oracle_result: OracleResult) -> ActionProposal:
    return ActionProposal(
        **_TEXTES[oracle_result.verdict],
        decision_suggeree="escalade",
        origine="deterministe",
    )
