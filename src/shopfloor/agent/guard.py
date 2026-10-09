"""Garde-fou appliqué à la sortie du LLM (skill oracle-guard). Fonction pure, sans LLM ni I/O.

Il ne juge pas la conformité : il vérifie seulement que la proposition ne contredit pas le verdict
de l'oracle, ne cite que des documents réellement retrouvés et contient une action.
"""

import re
import unicodedata
from collections.abc import Iterable

from pydantic import BaseModel, ConfigDict

from shopfloor.models import ActionProposal, OracleResult, Verdict


class GuardResult(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    ok: bool
    motifs: tuple[str, ...] = ()


# Appliqués à un texte normalisé : minuscules, sans accents, tirets unifiés, espaces simples.
# Rejetés même en présence d'une négation proche.
_TOUJOURS_REJETES = (
    re.compile(r"\best conformes?\b"),
    re.compile(r"\bdans (la|les) tolerances?\b"),
    re.compile(r"\ben tolerances?\b"),
)
# « conforme(s) » est accepté si l'un de ces mots figure parmi les 3 mots qui précèdent.
# Mots = suites de \w : « non-conforme » donne « non », « conforme » ; « non_conforme » reste un seul mot.
_NEGATIONS = frozenset({"non", "pas", "jamais"})
_FENETRE_NEGATION = 3
_TIRETS = dict.fromkeys(map(ord, "‐‑‒–—−"), "-")


def _normalize(text: str) -> str:
    text = unicodedata.normalize("NFKD", text)
    text = "".join(c for c in text if not unicodedata.combining(c))
    text = text.translate(_TIRETS).lower()
    return re.sub(r"\s+", " ", text)


def _conforme_sans_negation(norm: str) -> bool:
    mots = re.findall(r"\w+", norm)
    return any(
        mot in ("conforme", "conformes")
        and not _NEGATIONS.intersection(mots[max(0, i - _FENETRE_NEGATION):i])
        for i, mot in enumerate(mots)
    )


def affirme_conformite(text: str) -> bool:
    norm = _normalize(text)
    return any(p.search(norm) for p in _TOUJOURS_REJETES) or _conforme_sans_negation(norm)


def check_proposal(
    proposal: ActionProposal, oracle_result: OracleResult, retrieved_doc_ids: Iterable[str]
) -> GuardResult:
    motifs: list[str] = []

    connus = set(retrieved_doc_ids)
    inventees = [s for s in proposal.sources if s not in connus]
    if inventees:
        motifs.append(f"source(s) absente(s) des documents retrouvés : {', '.join(inventees)}")

    if oracle_result.verdict == Verdict.NON_CONFORME:
        for champ in ("resume", "cause_probable", "action_corrective"):
            if affirme_conformite(getattr(proposal, champ)):
                motifs.append(f"{champ} affirme la conformité alors que l'oracle a établi NON_CONFORME")

    # Défense en profondeur : ActionProposal l'interdit déjà, sauf objet construit sans validation.
    if not proposal.action_corrective or not proposal.action_corrective.strip():
        motifs.append("action_corrective vide")

    return GuardResult(ok=not motifs, motifs=tuple(motifs))
