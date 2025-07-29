from collections.abc import Hashable

from langgraph.graph import END
from langgraph.types import Send

from onyx.agents.agent_search.dr.constants import MAX_DR_PARALLEL_SEARCH
from onyx.agents.agent_search.dr.states import DRPath
from onyx.agents.agent_search.dr.states import MainState
from onyx.agents.agent_search.dr.states import QuestionInputState


def decision_router(state: MainState) -> list[Send | Hashable] | DRPath | str:
    if not state.query_path:
        raise IndexError("state.query_path cannot be empty")

    # go to closer if path is CLOSER or no queries
    next_path = state.query_path[-1]

    if next_path == DRPath.END:
        return END
    elif next_path == DRPath.ORCHESTRATOR:
        return DRPath.ORCHESTRATOR
    elif next_path == DRPath.INTERNET_SEARCH:
        return DRPath.INTERNET_SEARCH
    elif next_path == DRPath.CLARIFIER:
        raise ValueError("CLARIFIER is not a valid path during iteration")
    elif (
        next_path == DRPath.CLOSER
        or (len(state.query_list) == 0)
        and (state.iteration_nr > 0)
    ):
        return DRPath.CLOSER

    # send search/kg requests (parallel only for search)
    # TODO: MAX_DR_PARALLEL_SEARCH should be tool-dependent
    queries = state.query_list[:MAX_DR_PARALLEL_SEARCH]
    if next_path == DRPath.KNOWLEDGE_GRAPH:
        queries = queries[:1]

    if next_path in (DRPath.SEARCH, DRPath.KNOWLEDGE_GRAPH):
        return [
            Send(
                next_path,
                QuestionInputState(
                    iteration_nr=state.iteration_nr,
                    parallelization_nr=parallelization_nr,
                    question=query,
                    tool=next_path,
                ),
            )
            for parallelization_nr, query in enumerate(queries)
        ]
    else:
        # Custom tools use the gt sub-agent
        return DRPath.GENERIC_TOOL


def completeness_router(state: MainState) -> DRPath | str:
    if not state.query_path:
        raise IndexError("query_path cannot be empty")

    # go to closer if path is CLOSER or no queries
    next_path = state.query_path[-1]

    if next_path == DRPath.ORCHESTRATOR:
        return DRPath.ORCHESTRATOR
    else:
        return END
