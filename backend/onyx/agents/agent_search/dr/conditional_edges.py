from collections.abc import Hashable

from langgraph.graph import END
from langgraph.types import Send

from onyx.agents.agent_search.dr.enums import DRPath
from onyx.agents.agent_search.dr.states import MainState


def decision_router(state: MainState) -> list[Send | Hashable] | DRPath | str:
    if not state.tools_used:
        raise IndexError("state.tools_used cannot be empty")

    # next_tool is either a generic tool name or a DRPath string
    next_tool_name = state.tools_used[-1]

    available_tools = state.available_tools
    if not available_tools:
        raise ValueError("No tool is available. This should not happen.")

    if next_tool_name in available_tools:
        next_tool_path = available_tools[next_tool_name].path
    elif next_tool_name == DRPath.END.value:
        return END
    elif next_tool_name == DRPath.LOGGER.value:
        return DRPath.LOGGER
    elif next_tool_name == DRPath.CLOSER.value:
        return DRPath.CLOSER
    else:
        return DRPath.ORCHESTRATOR

    # handle invalid paths
    if next_tool_path == DRPath.CLARIFIER:
        raise ValueError("CLARIFIER is not a valid path during iteration")

    # handle tool calls without a query
    if (
        next_tool_path
        in (
            DRPath.INTERNAL_SEARCH,
            DRPath.WEB_SEARCH,
            DRPath.KNOWLEDGE_GRAPH,
            DRPath.IMAGE_GENERATION,
        )
        and len(state.query_list) == 0
    ):
        return DRPath.CLOSER

    return next_tool_path


def completeness_router(state: MainState) -> DRPath | str:
    if not state.tools_used:
        raise IndexError("tools_used cannot be empty")

    # go to closer if path is CLOSER or no queries
    next_path = state.tools_used[-1]

    if next_path == DRPath.ORCHESTRATOR.value:
        return DRPath.ORCHESTRATOR
    return DRPath.LOGGER
