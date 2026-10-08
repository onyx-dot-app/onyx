"""Conversation-owned search state."""

from collections.abc import Sequence

from onyx.tools.interface import Tool
from onyx.tools.tool_implementations.search.models import SearchToolState
from onyx.tools.tool_implementations.search.search_tool import (
    SearchTool,
)


def capture_search_state(tools: Sequence[Tool]) -> dict[str, SearchToolState]:
    return {
        tool.name: tool.capture_state()
        for tool in tools
        if isinstance(tool, SearchTool)
    }


def restore_search_state(
    tools: Sequence[Tool], states: dict[str, SearchToolState]
) -> None:
    available = {tool.name: tool for tool in tools if isinstance(tool, SearchTool)}
    if states.keys() - available.keys():
        raise ValueError("Saved search tools are unavailable")
    for name, state in states.items():
        available[name].restore_state(state)
