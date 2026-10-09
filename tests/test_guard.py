"""Garde-fou de la sortie LLM et propositions déterministes (skill oracle-guard)."""

from pathlib import Path

import pytest
from pydantic import ValidationError

from shopfloor.agent.fallback import default_proposal
from shopfloor.agent.guard import affirme_conformite, check_proposal
from shopfloor.models import ActionProposal, Verdict
from shopfloor.nc import parse_nc_file
from shopfloor.oracle.conformity import check_conformity
from shopfloor.oracle.loader import load_tolerances

ROOT = Path(__file__).resolve().parents[1]
TOLERANCES = load_tolerances(ROOT / "config" / "tolerances.yaml")
RETRIEVED = ["NC-2025-014", "PROC-COMP-01", "PROC-QUA-01"]


def oracle_for(nc_id: str):
    return check_conformity(parse_nc_file(ROOT / "data" / "nc_inbox" / f"{nc_id}.md"), TOLERANCES)


NON_CONFORME = oracle_for("NC-2026-101")
CONFORME = oracle_for("NC-2026-102")
INDETERMINE = oracle_for("NC-2026-103")


def proposal(**overrides) -> ActionProposal:
    data = {
        "resume": "Porosité hors tolérance sur le panneau.",
        "cause_probable": "Fuite de bâche à vide.",
        "action_corrective": "Rechercher la fuite et refaire le test d'étanchéité.",
        "decision_suggeree": "rebut",
        "sources": ["NC-2025-014"],
        "origine": "llm",
    }
    data.update(overrides)
    return ActionProposal(**data)


def test_oracles_de_reference():
    assert (NON_CONFORME.verdict, CONFORME.verdict, INDETERMINE.verdict) == (
        Verdict.NON_CONFORME, Verdict.CONFORME, Verdict.INDETERMINE,
    )


def test_proposition_valide_acceptee():
    result = check_proposal(proposal(), NON_CONFORME, RETRIEVED)
    assert result.ok and result.motifs == ()


@pytest.mark.parametrize("text", [
    "La pièce est non conforme : porosité trop élevée.",
    "Pièce non-conforme, isolée en zone NC.",
    "Pièces NON CONFORMES sur ce lot.",
    "Pièce non‑conforme (tiret insécable).",
    "Verdict NON_CONFORME établi par l'oracle.",
    "Traiter la non-conformité selon PROC-QUA-01.",
    "Réaliser l'action conformément à PROC-COMP-01.",
])
def test_negation_ou_vocabulaire_neutre_accepte(text):
    assert not affirme_conformite(text)
    assert check_proposal(proposal(resume=text), NON_CONFORME, RETRIEVED).ok


@pytest.mark.parametrize("text", [
    "La pièce est conforme, aucune action nécessaire.",
    "Pièce CONFORME.",
    "Les mesures sont Conformes au plan.",
    "La porosité reste dans les tolérances.",
    "Porosité DANS LA TOLÉRANCE du plan.",
    "Mesure dans les tolerances, pas d'écart.",
    "Pièce en tolérance.",
])
def test_affirmation_de_conformite_rejetee(text):
    assert affirme_conformite(text)
    for champ in ("resume", "cause_probable", "action_corrective"):
        result = check_proposal(proposal(**{champ: text}), NON_CONFORME, RETRIEVED)
        assert not result.ok
        assert any(champ in m and "conformité" in m for m in result.motifs)


@pytest.mark.parametrize("text", [
    "La pièce n'est pas conforme.",
    "La pièce n'est toujours pas conforme.",
    "Le panneau n'a jamais été conforme sur ce lot.",
    "Pas réellement conforme.",
])
def test_negation_dans_les_3_mots_precedents_acceptee(text):
    assert not affirme_conformite(text)
    assert check_proposal(proposal(cause_probable=text), NON_CONFORME, RETRIEVED).ok


@pytest.mark.parametrize("text", [
    "Elle est conforme.",
    "Pas de doute, elle est conforme.",  # « pas » est à 4 mots de « conforme »
    "Jamais vu un tel écart, mais pièce conforme.",
    "Pas sûr : est conforme.",  # « est conforme » toujours rejeté, même avec une négation proche
    "Pas dans les tolérances du plan ? Si.",
    "Non, pièce en tolérance.",
])
def test_affirmation_rejetee_malgre_une_negation_eloignee_ou_hors_fenetre(text):
    assert affirme_conformite(text)
    assert not check_proposal(proposal(resume=text), NON_CONFORME, RETRIEVED).ok


def test_conformite_non_controlee_hors_non_conforme():
    """Le contrôle (b) ne s'applique qu'à un verdict NON_CONFORME."""
    p = proposal(resume="Toutes les mesures sont conformes.", sources=[])
    assert check_proposal(p, CONFORME, []).ok
    assert check_proposal(p, INDETERMINE, []).ok


def test_source_inventee_rejetee():
    result = check_proposal(proposal(sources=["NC-2025-014", "NC-9999"]), NON_CONFORME, RETRIEVED)
    assert not result.ok
    assert any("NC-9999" in m for m in result.motifs)
    assert not any("NC-2025-014" in m for m in result.motifs)


def test_aucune_source_acceptee():
    assert check_proposal(proposal(sources=[]), NON_CONFORME, RETRIEVED).ok


@pytest.mark.parametrize("action", ["", "   "])
def test_action_vide_rejetee(action):
    # ActionProposal refuse déjà une action vide ; le garde-fou la rejette aussi (objet non validé).
    with pytest.raises(ValidationError):
        proposal(action_corrective=action)
    p = proposal().model_copy(update={"action_corrective": action})
    result = check_proposal(p, NON_CONFORME, RETRIEVED)
    assert not result.ok
    assert "action_corrective vide" in result.motifs


def test_plusieurs_motifs_cumules():
    p = proposal(resume="Pièce conforme.", sources=["NC-9999"]).model_copy(update={"action_corrective": ""})
    assert len(check_proposal(p, NON_CONFORME, RETRIEVED).motifs) == 3


def test_action_proposal_refuse_un_verdict():
    with pytest.raises(ValidationError):
        proposal(verdict="CONFORME")


def test_action_proposal_decision_et_origine_fermees():
    with pytest.raises(ValidationError):
        proposal(decision_suggeree="accepter")
    with pytest.raises(ValidationError):
        proposal(origine="humain")


def test_action_proposal_figee():
    with pytest.raises(ValidationError):
        proposal().resume = "autre"


@pytest.mark.parametrize("oracle_result, fragment", [
    (CONFORME, "fausse alerte"),
    (INDETERMINE, "hors référentiel"),
    (NON_CONFORME, "PROC-QUA-01"),
])
def test_default_proposal(oracle_result, fragment):
    p = default_proposal(oracle_result)
    assert p.origine == "deterministe"
    assert p.decision_suggeree == "escalade"
    assert fragment in p.action_corrective
    assert p == default_proposal(oracle_result)  # déterministe


def test_default_proposal_non_conforme_passe_le_garde_fou():
    """Le texte figé du repli ne doit jamais affirmer la conformité."""
    p = default_proposal(NON_CONFORME)
    assert p.sources == ["PROC-QUA-01"]
    assert check_proposal(p, NON_CONFORME, p.sources).ok
