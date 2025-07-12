from onyx.agents.agent_search.dr.states import DRPath
from onyx.agents.agent_search.dr.states import MainState


def decision_router(state: MainState) -> DRPath:
    if not state.query_path:
        raise IndexError("state.query_path cannot be empty")
    return state.query_path[-1]
