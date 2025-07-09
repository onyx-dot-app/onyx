from onyx.agents.agent_search.dr.states import DRPath
from onyx.agents.agent_search.dr.states import MainState


MainState


def decision_router(
    state: MainState,
) -> str:

    last_decision = state.query_path[-1]

    if last_decision == DRPath.KNOWLEDGE_GRAPH:
        return "kg_query"
    elif last_decision == DRPath.SEARCH:
        return "search"
    elif last_decision == DRPath.CLOSER:
        return "closer"
    else:
        raise ValueError(f"Invalid decision: {last_decision}")
