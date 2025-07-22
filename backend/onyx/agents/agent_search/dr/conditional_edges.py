from collections.abc import Hashable

from langgraph.graph import END
from langgraph.types import Send

from onyx.agents.agent_search.dr.states import DRPath
from onyx.agents.agent_search.dr.states import MainState
from onyx.agents.agent_search.dr.states import QuestionUpdate


def decision_router(state: MainState) -> list[Send | Hashable] | DRPath | str:
    if not state.query_path:
        raise IndexError("state.query_path cannot be empty")

    # go to closer if path is CLOSER or no queries
    next_path = state.query_path[-1]

    if next_path == DRPath.USER_FEEDBACK:
        return END

    elif next_path == DRPath.ORCHESTRATOR:
        return DRPath.ORCHESTRATOR

    elif next_path == DRPath.INTERNET_SEARCH:
        return DRPath.INTERNET_SEARCH

    elif (
        next_path == DRPath.CLOSER
        or (len(state.query_list) == 0)
        and (state.iteration_nr > 0)
    ):
        return DRPath.CLOSER

    # send search/kg requests (parallel only for search)
    queries = (
        state.query_list
        if next_path == DRPath.SEARCH or next_path == DRPath.INTERNET_SEARCH
        else state.query_list[:1]
    )
    return [
        Send(
            next_path,
            QuestionUpdate(
                iteration_nr=state.iteration_nr,
                parallelization_nr=parallelization_nr,
                question=query,
            ),
        )
        for parallelization_nr, query in enumerate(queries)
    ]
