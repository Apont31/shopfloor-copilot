"""Graphe LangGraph de l'agent (décision D3).

parse_nc -> check_existing -> oracle -> [NON_CONFORME] retrieve_similar -> propose_action -> human_gate
                                     -> [CONFORME, INDETERMINE] propose_default -> human_gate
human_gate -> [approve, edit] create_ticket
Une fiche illisible s'arrête après parse_nc ; une fiche déjà traitée ou un ERP injoignable après check_existing ; un index RAG ou Ollama indisponible après retrieve_similar ;
un rejet humain s'arrête après human_gate.
"""

from pathlib import Path

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command

from shopfloor.agent import nodes
from shopfloor.agent.nodes import Deps
from shopfloor.agent.state import CHECKPOINT_TYPES, AgentState, HumanDecision
from shopfloor.models import Verdict
from shopfloor.nc import NCParseError, parse_nc_file

__all__ = ["Deps", "build_graph", "thread_config", "initial_state", "start", "resume", "get_state"]

# Champs que chaque nœud a le droit d'écrire. Seul le nœud oracle écrit « oracle ».
WRITES: dict[str, frozenset[str]] = {
    "parse_nc": frozenset({"nc", "error"}),
    "check_existing": frozenset({"error"}),
    "oracle": frozenset({"oracle"}),
    "retrieve_similar": frozenset({"similar", "passages", "error"}),
    "propose_action": frozenset({"proposal", "guard", "llm_calls"}),
    "propose_default": frozenset({"proposal"}),
    "human_gate": frozenset({"human"}),
    "create_ticket": frozenset({"ticket", "error"}),
}


def _bind(name: str, deps: Deps):
    fn = getattr(nodes, name)
    allowed = WRITES[name]

    def run(state: AgentState) -> dict:
        update = fn(state, deps)
        interdits = set(update) - allowed
        if interdits:
            raise RuntimeError(f"le nœud {name} n'a pas le droit d'écrire : {', '.join(sorted(interdits))}")
        return update

    run.__name__ = name
    return run


def _after_parse(state: AgentState) -> str:
    return END if state.error is not None else "check_existing"


def _after_check_existing(state: AgentState) -> str:
    return END if state.error is not None else "oracle"


def _after_oracle(state: AgentState) -> str:
    return "retrieve_similar" if state.oracle.verdict == Verdict.NON_CONFORME else "propose_default"


def _after_retrieve(state: AgentState) -> str:
    return END if state.error is not None else "propose_action"


def _after_human(state: AgentState) -> str:
    return "create_ticket" if state.human.decision in ("approve", "edit") else END


def build_graph(deps: Deps):
    builder = StateGraph(AgentState)
    for name in WRITES:
        builder.add_node(name, _bind(name, deps))
    builder.add_edge(START, "parse_nc")
    builder.add_conditional_edges("parse_nc", _after_parse, ["check_existing", END])
    builder.add_conditional_edges("check_existing", _after_check_existing, ["oracle", END])
    builder.add_conditional_edges("oracle", _after_oracle, ["retrieve_similar", "propose_default"])
    builder.add_conditional_edges("retrieve_similar", _after_retrieve, ["propose_action", END])
    builder.add_edge("propose_action", "human_gate")
    builder.add_edge("propose_default", "human_gate")
    builder.add_conditional_edges("human_gate", _after_human, ["create_ticket", END])
    builder.add_edge("create_ticket", END)
    # Désérialisation du checkpoint limitée aux types de l'état (pas d'objet arbitraire).
    serde = JsonPlusSerializer(allowed_msgpack_modules=CHECKPOINT_TYPES)
    return builder.compile(checkpointer=InMemorySaver(serde=serde))


def thread_config(nc_id: str) -> dict:
    return {"configurable": {"thread_id": nc_id}}


def initial_state(nc_path: str | Path) -> dict:
    """Tous les champs explicitement : relancer une fiche sur le même thread repart d'un état propre."""
    return AgentState(nc_path=str(nc_path)).model_dump()


def _thread_id(nc_path: str | Path) -> str:
    try:
        return parse_nc_file(nc_path).nc_id
    except NCParseError:
        return Path(nc_path).stem


def start(graph, nc_path: str | Path) -> dict:
    """Lance le traitement d'une fiche (thread_id = nc_id). Renvoie la config du thread."""
    config = thread_config(_thread_id(nc_path))
    graph.invoke(initial_state(nc_path), config)
    return config


def resume(graph, config: dict, decision: HumanDecision | dict) -> None:
    graph.invoke(Command(resume=decision), config)


def get_state(graph, config: dict) -> AgentState:
    return AgentState.model_validate(graph.get_state(config).values)
