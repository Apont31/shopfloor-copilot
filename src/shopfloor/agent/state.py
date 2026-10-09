"""État Pydantic de l'agent et décision humaine attendue à la reprise."""

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, StringConstraints, model_validator

from shopfloor.agent.guard import GuardResult
from shopfloor.erp.schemas import Ticket
from shopfloor.models import (
    ActionProposal,
    Measurement,
    MeasureResult,
    NCRecord,
    OracleResult,
    Verdict,
)
from shopfloor.rag.retriever import RetrievedChunk

NonEmptyStr = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]


class HumanDecision(BaseModel):
    """Valeur attendue par Command(resume=...) au nœud human_gate."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    decision: Literal["approve", "reject", "edit"]
    action_corrective: NonEmptyStr | None = None
    valide_par: NonEmptyStr
    commentaire: str | None = None

    @model_validator(mode="after")
    def edit_exige_une_action(self):
        if self.decision == "edit" and self.action_corrective is None:
            raise ValueError("decision edit : action_corrective est obligatoire")
        return self


class AgentState(BaseModel):
    nc_path: str
    nc: NCRecord | None = None
    oracle: OracleResult | None = None  # écrit uniquement par le nœud oracle
    similar: list[RetrievedChunk] = []
    proposal: ActionProposal | None = None
    guard: GuardResult | None = None
    llm_calls: int = 0
    human: HumanDecision | None = None
    ticket: Ticket | None = None
    error: str | None = None


# Types sérialisés dans le checkpoint : autorisés explicitement (pas de désérialisation arbitraire).
CHECKPOINT_TYPES = (
    AgentState,
    NCRecord,
    Measurement,
    OracleResult,
    MeasureResult,
    Verdict,
    RetrievedChunk,
    ActionProposal,
    GuardResult,
    HumanDecision,
    Ticket,
)
