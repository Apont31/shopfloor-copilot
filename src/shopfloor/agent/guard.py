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
# « conforme(s) » non précédé de « non » ou « non- » ; « non_conforme » (sans frontière de mot) est ignoré.
_AFFIRME_CONFORMITE = (
    re.compile(r"(?<!\bnon )(?<!\bnon-)\bconformes?\b"),
    re.compile(r"\bdans (la|les) tolerances?\b"),
    re.compile(r"\ben tolerances?\b"),
)
_TIRETS = dict.fromkeys(map(ord, "‐‑‒–—−"), "-")


def _normalize(text: str) -> str:
    text = unicodedata.normalize("NFKD", text)
    text = "".join(c for c in text if not unicodedata.combining(c))
    text = text.translate(_TIRETS).lower()
    return re.sub(r"\s+", " ", text)


def affirme_conformite(text: str) -> bool:
    norm = _normalize(text)
    return any(p.search(norm) for p in _AFFIRME_CONFORMITE)


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
