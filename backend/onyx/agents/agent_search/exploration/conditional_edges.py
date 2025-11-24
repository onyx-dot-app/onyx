from collections.abc import Hashable

from langgraph.graph import END
from langgraph.types import Send

from onyx.agents.agent_search.exploration.enums import DRPath
from onyx.agents.agent_search.exploration.states import CSUpdateConsolidatorInput
from onyx.agents.agent_search.exploration.states import MainState


def decision_router(state: MainState) -> list[Send | Hashable] | DRPath | str:
    if not state.tools_used:
        raise IndexError("state.tools_used cannot be empty")

    # next_tool is either a generic tool name or a DRPath string
    next_tool_name = state.tools_used[-1]

    available_tools = state.available_tools
    if next_tool_name == DRPath.THINKING.value:
        return DRPath.ORCHESTRATOR  # thinking alteady done
    elif not available_tools:
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


def cs_update_consolidator_router(state: MainState) -> list[Send] | DRPath | str:

    knowledge_update_pairs = state.knowledge_update_pairs

    sends: list[Send] = [
        Send(
            "cs_consolidator",
            CSUpdateConsolidatorInput(
                area=area,
                update_type=update_type,
                update_pair=update_pair,
            ),
        )
        for area in ["user", "company", "search_strategy", "reasoning_strategy"]
        for update_type in knowledge_update_pairs.get(area, {})
        for update_pair in knowledge_update_pairs.get(area, {}).get(update_type, [])
    ]

    if not sends:
        return DRPath.LOGGER

    return sends
