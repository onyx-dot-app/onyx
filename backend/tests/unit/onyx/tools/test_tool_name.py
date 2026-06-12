"""Tests for tool-name sanitization and collision disambiguation.

Multiple MCP servers commonly expose tools with the same generic name (e.g.
``search``). When attached to the same assistant they produce duplicate LLM
function declarations, which providers like Gemini reject with
``Duplicate function declaration found: search``. ``disambiguate_tool_names``
renames the colliding MCP tools (prefixing with the server name) while leaving
built-in tool names and user-facing display names untouched.
"""

from unittest.mock import MagicMock

import pytest

from onyx.tools.interface import Tool
from onyx.tools.tool_implementations.mcp.mcp_tool import MCPTool
from onyx.tools.tool_name import disambiguate_tool_names
from onyx.tools.tool_name import sanitize_tool_name

# OpenAI's documented function-name length limit; generated names must fit.
MAX_TOOL_NAME_LEN = 64


def _make_mcp_tool(server_name: str, tool_name: str) -> MCPTool:
    mcp_server = MagicMock()
    mcp_server.name = server_name
    return MCPTool(
        tool_id=1,
        emitter=MagicMock(),
        mcp_server=mcp_server,
        tool_name=tool_name,
        tool_description="desc",
        tool_definition={"type": "object", "properties": {}},
    )


class _FakeBuiltInTool(Tool[None]):
    """Minimal non-MCP tool to verify built-in names stay stable."""

    def __init__(self, name: str) -> None:
        super().__init__(emitter=MagicMock())
        self._name = name

    @property
    def id(self) -> int:
        return 99

    @property
    def name(self) -> str:
        return self._name

    @property
    def description(self) -> str:
        return "fake"

    @property
    def display_name(self) -> str:
        return self._name

    def tool_definition(self) -> dict:
        return {"type": "function", "function": {"name": self._name}}

    def emit_start(self, placement: object) -> None:  # noqa: ARG002
        return None

    def run(
        self, placement: object, override_kwargs: None = None, **llm_kwargs: object
    ):  # type: ignore[override]  # noqa: ARG002
        raise NotImplementedError


class TestSanitizeToolName:
    def test_replaces_invalid_chars(self) -> None:
        assert sanitize_tool_name("mcp:server:search") == "mcp_server_search"

    def test_keeps_valid_chars(self) -> None:
        assert sanitize_tool_name("get_sheet-1") == "get_sheet-1"


class TestDisambiguateToolNames:
    def test_no_collision_is_noop(self) -> None:
        a = _make_mcp_tool("atlassian", "search")
        b = _make_mcp_tool("smartsheet", "get_sheet")

        disambiguate_tool_names([a, b])

        assert a.name == "search"
        assert b.name == "get_sheet"

    def test_two_mcp_servers_same_tool_name_get_namespaced(self) -> None:
        a = _make_mcp_tool("atlassian", "search")
        b = _make_mcp_tool("smartsheet", "search")

        disambiguate_tool_names([a, b])

        # Both renamed, both unique, both prefixed with their server.
        assert a.name == "atlassian_search"
        assert b.name == "smartsheet_search"
        assert a.name != b.name

    def test_namespacing_flows_into_tool_definition(self) -> None:
        a = _make_mcp_tool("atlassian", "search")
        b = _make_mcp_tool("smartsheet", "search")

        disambiguate_tool_names([a, b])

        assert a.tool_definition()["function"]["name"] == "atlassian_search"
        assert b.tool_definition()["function"]["name"] == "smartsheet_search"

    def test_display_name_is_unchanged(self) -> None:
        a = _make_mcp_tool("atlassian", "search")
        b = _make_mcp_tool("smartsheet", "search")

        disambiguate_tool_names([a, b])

        # UI keeps showing the original tool name.
        assert a.display_name == "search"
        assert b.display_name == "search"

    def test_builtin_name_stays_stable_mcp_renamed_around_it(self) -> None:
        builtin = _FakeBuiltInTool("search")
        mcp = _make_mcp_tool("smartsheet", "search")

        disambiguate_tool_names([builtin, mcp])

        # Built-in keeps its well-known name; the MCP tool is renamed away.
        assert builtin.name == "search"
        assert mcp.name == "smartsheet_search"

    def test_server_name_with_invalid_chars_is_sanitized(self) -> None:
        a = _make_mcp_tool("Atlassian Rovo", "search")
        b = _make_mcp_tool("smartsheet", "search")

        disambiguate_tool_names([a, b])

        assert a.name == "Atlassian_Rovo_search"
        assert all(c.isalnum() or c in "_-" for c in a.name)

    def test_same_server_same_tool_twice_stays_unique(self) -> None:
        # Pathological: two tools that prefix to the identical name.
        a = _make_mcp_tool("dup", "search")
        b = _make_mcp_tool("dup", "search")

        disambiguate_tool_names([a, b])

        assert a.name != b.name
        assert {a.name, b.name} == {"dup_search", "dup_search_2"}

    def test_long_names_are_truncated_to_limit(self) -> None:
        long_server = "s" * 80
        a = _make_mcp_tool(long_server, "search")
        b = _make_mcp_tool("smartsheet", "search")

        disambiguate_tool_names([a, b])

        assert len(a.name) <= MAX_TOOL_NAME_LEN


if __name__ == "__main__":
    pytest.main([__file__, "-xv"])
