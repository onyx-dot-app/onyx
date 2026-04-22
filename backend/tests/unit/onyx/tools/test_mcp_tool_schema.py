"""Tests for MCPTool.tool_definition() schema normalization.

MCP servers may legally return `inputSchema` values that omit `properties`
(e.g. `{"type": "object"}` for zero-arg tools like AWS Knowledge MCP's
`aws___list_regions`). Azure OpenAI rejects such schemas with
"object schema missing properties", which breaks every chat request for
the persona as soon as one offending tool is registered.

These tests pin the contract that MCPTool.tool_definition() always returns
a JSON-Schema-valid `parameters` dict with a `properties` key.
"""

from unittest.mock import MagicMock

import pytest

from onyx.tools.tool_implementations.mcp.mcp_tool import (
    _normalize_parameters_schema,
)
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


def _make_tool(input_schema: dict) -> MCPTool:
    mcp_server = MagicMock()
    mcp_server.name = "aws-knowledge"
    return MCPTool(
        tool_id=1,
        emitter=MagicMock(),
        mcp_server=mcp_server,
        tool_name="aws___list_regions",
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


if __name__ == "__main__":
    pytest.main([__file__, "-xv"])
