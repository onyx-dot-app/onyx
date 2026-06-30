"""Tests for MCPTool.tool_definition() schema normalization.

MCP servers may legally return `inputSchema` values that omit `properties`
(e.g. `{"type": "object"}` for zero-arg tools like AWS Knowledge MCP's
`aws___list_regions`). Azure OpenAI rejects such schemas with
"object schema missing properties", which breaks every chat request for
the persona as soon as one offending tool is registered.

These tests pin the contract that MCPTool.tool_definition() always returns
a JSON-Schema-valid `parameters` dict with a `properties` key.
"""

from typing import Any
from unittest.mock import MagicMock
from unittest.mock import patch

import pytest

from onyx.db.enums import MCPAuthenticationType
from onyx.server.query_and_chat.placement import Placement
from onyx.tools.interface import Tool
from onyx.tools.models import ToolResponse
from onyx.tools.tool_constructor import _disambiguate_mcp_tool_names
from onyx.tools.tool_implementations.mcp.mcp_tool import _normalize_parameters_schema
from onyx.tools.tool_implementations.mcp.mcp_tool import MCPTool


class TestNormalizeParametersSchema:
    def test_empty_dict_gets_object_shell(self) -> None:
        assert _normalize_parameters_schema({}) == {
            "type": "object",
            "properties": {},
        }

    def test_none_gets_object_shell(self) -> None:
        assert _normalize_parameters_schema(None) == {
            "type": "object",
            "properties": {},
        }

    def test_object_without_properties_gets_seeded(self) -> None:
        # This is the AWS Knowledge MCP case: aws___list_regions returns
        # `{"type": "object"}` for a zero-arg tool.
        assert _normalize_parameters_schema({"type": "object"}) == {
            "type": "object",
            "properties": {},
        }

    def test_object_with_properties_is_passed_through(self) -> None:
        schema = {
            "type": "object",
            "properties": {"region": {"type": "string"}},
            "required": ["region"],
        }
        assert _normalize_parameters_schema(schema) == schema

    def test_schema_without_type_treated_as_object(self) -> None:
        # Some MCP servers omit `type` entirely; JSON Schema defaults to
        # accepting anything, but OpenAI's validator expects an object.
        assert _normalize_parameters_schema({"description": "no args"}) == {
            "description": "no args",
            "type": "object",
            "properties": {},
        }

    def test_non_object_schema_is_left_alone(self) -> None:
        # A non-object root schema (rare but valid JSON Schema) shouldn't
        # have `properties` forced onto it.
        schema = {"type": "string"}
        assert _normalize_parameters_schema(schema) == schema

    def test_existing_empty_properties_preserved(self) -> None:
        schema = {"type": "object", "properties": {}}
        assert _normalize_parameters_schema(schema) == schema


class _StaticTool(Tool[None]):
    def __init__(self, name: str) -> None:
        super().__init__(emitter=MagicMock())
        self._name = name

    @property
    def id(self) -> int:
        return 2

    @property
    def name(self) -> str:
        return self._name

    @property
    def description(self) -> str:
        return "Static tool"

    @property
    def display_name(self) -> str:
        return self._name

    def tool_definition(self) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": self._name,
                "description": self.description,
                "parameters": {"type": "object", "properties": {}},
            },
        }

    def emit_start(self, placement: Placement) -> None:
        pass

    def run(
        self,
        placement: Placement,
        override_kwargs: None = None,
        **llm_kwargs: Any,
    ) -> ToolResponse:
        raise NotImplementedError


def _make_tool(
    input_schema: dict,
    tool_name: str = "aws___list_regions",
    server_name: str = "aws-knowledge",
) -> MCPTool:
    mcp_server = MagicMock()
    mcp_server.name = server_name
    mcp_server.server_url = "http://mcp.example"
    mcp_server.auth_type = MCPAuthenticationType.NONE
    mcp_server.transport = None
    return MCPTool(
        tool_id=1,
        emitter=MagicMock(),
        mcp_server=mcp_server,
        tool_name=tool_name,
        tool_description="List AWS regions",
        tool_definition=input_schema,
    )


class TestMCPToolDefinition:
    def test_zero_arg_mcp_tool_emits_valid_openai_schema(self) -> None:
        # Regression: the AWS Knowledge MCP server returned
        # `{"type": "object"}` for aws___list_regions, which Azure OpenAI
        # rejected. The parameters field must always include `properties`.
        tool = _make_tool({"type": "object"})

        params = tool.tool_definition()["function"]["parameters"]

        assert params == {"type": "object", "properties": {}}

    def test_empty_input_schema_emits_valid_openai_schema(self) -> None:
        tool = _make_tool({})

        params = tool.tool_definition()["function"]["parameters"]

        assert params == {"type": "object", "properties": {}}

    def test_populated_schema_is_preserved(self) -> None:
        input_schema = {
            "type": "object",
            "properties": {"region": {"type": "string"}},
            "required": ["region"],
        }
        tool = _make_tool(input_schema)

        params = tool.tool_definition()["function"]["parameters"]

        assert params == input_schema

    def test_normalization_does_not_mutate_stored_schema(self) -> None:
        # Azure-only normalization shouldn't corrupt the schema we kept for
        # display / future re-serialization.
        stored = {"type": "object"}
        tool = _make_tool(stored)

        tool.tool_definition()

        assert stored == {"type": "object"}


class TestMCPToolLLMNames:
    def test_mcp_tool_keeps_original_name_without_conflicts(self) -> None:
        tool = _make_tool({"type": "object"})

        _disambiguate_mcp_tool_names([tool])

        assert tool.name == "aws___list_regions"
        assert tool.tool_definition()["function"]["name"] == "aws___list_regions"

    def test_mcp_tool_disambiguates_at_construction_when_names_conflict(self) -> None:
        mcp_tool = _make_tool(
            {"type": "object"}, tool_name="shared", server_name="server name"
        )
        static_tool = _StaticTool("shared")

        _disambiguate_mcp_tool_names([mcp_tool, static_tool])

        assert mcp_tool.name == "mcp_server_name_shared"
        assert (
            mcp_tool.tool_definition()["function"]["name"] == "mcp_server_name_shared"
        )
        assert static_tool.name == "shared"

    def test_second_order_disambiguated_name_conflicts_are_allowed(self) -> None:
        mcp_tool = _make_tool(
            {"type": "object"}, tool_name="shared", server_name="server"
        )
        conflicting_tool = _StaticTool("shared")
        second_order_conflicting_tool = _StaticTool("mcp_server_shared")

        tools: list[Tool] = [mcp_tool, conflicting_tool, second_order_conflicting_tool]
        _disambiguate_mcp_tool_names(tools)

        assert [tool.name for tool in tools] == [
            "mcp_server_shared",
            "shared",
            "mcp_server_shared",
        ]

    def test_disambiguated_mcp_tool_calls_server_with_original_name(self) -> None:
        mcp_tool = _make_tool({"type": "object"}, tool_name="shared")
        conflicting_tool = _StaticTool("shared")
        _disambiguate_mcp_tool_names([mcp_tool, conflicting_tool])

        with patch(
            "onyx.tools.tool_implementations.mcp.mcp_tool.call_mcp_tool",
            return_value={"ok": True},
        ) as mock_call_mcp_tool:
            mcp_tool.run(Placement(turn_index=0))

        mock_call_mcp_tool.assert_called_once()
        assert mock_call_mcp_tool.call_args.args[1] == "shared"


if __name__ == "__main__":
    pytest.main([__file__, "-xv"])
