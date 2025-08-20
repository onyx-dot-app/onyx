from collections.abc import Hashable

from langgraph.graph import END
from langgraph.types import Send

from onyx.agents.agent_search.dr.enums import DRPath
from onyx.agents.agent_search.dr.states import MainState


def decision_router(state: MainState) -> list[Send | Hashable] | DRPath | str:
    if not state.tools_used:
        raise IndexError("state.tools_used cannot be empty")

    # next_tool is either a generic tool name or a DRPath string
    next_tool = state.tools_used[-1]
    try:
        next_path = DRPath(next_tool)
    except ValueError:
        next_path = DRPath.GENERIC_TOOL

    # handle END
    if next_path == DRPath.END:
        return END

    # handle invalid paths
    if next_path == DRPath.CLARIFIER:
        raise ValueError("CLARIFIER is not a valid path during iteration")

    # handle tool calls without a query
    if (
        next_path
        in (
            DRPath.INTERNAL_SEARCH,
            DRPath.INTERNET_SEARCH,
            DRPath.KNOWLEDGE_GRAPH,
            DRPath.IMAGE_GENERATION,
        )
        and len(state.query_list) == 0
    ):
        return DRPath.CLOSER

    return next_path


def completeness_router(state: MainState) -> DRPath | str:
    if not state.tools_used:
        raise IndexError("tools_used cannot be empty")

    # go to closer if path is CLOSER or no queries
    next_path = state.tools_used[-1]

    if next_path == DRPath.ORCHESTRATOR.value:
        return DRPath.ORCHESTRATOR
    return END
