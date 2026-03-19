from types import SimpleNamespace
from typing import cast
from unittest.mock import MagicMock

import pytest

from onyx.db.models import MCPServer
from onyx.tools.tool_implementations.mcp.mcp_tool import MCPTool
from onyx.tools.tool_implementations.mcp.schema_utils import normalize_mcp_input_schema


class TestNormalizeMcpInputSchema:
    def test_empty_schema_defaults_to_empty_object(self) -> None:
        assert normalize_mcp_input_schema({}) == {
            "type": "object",
            "properties": {},
        }

    def test_object_like_schema_gets_missing_type_added(self) -> None:
        assert normalize_mcp_input_schema(
            {
                "properties": {
                    "query": {"type": "string"},
                },
                "required": ["query"],
            }
        ) == {
            "type": "object",
            "properties": {
                "query": {"type": "string"},
            },
            "required": ["query"],
        }

    def test_object_like_schema_with_invalid_type_gets_overridden(self) -> None:
        assert normalize_mcp_input_schema(
            {
                "type": "array",
                "properties": {
                    "query": {"type": "string"},
                },
            }
        ) == {
            "type": "object",
            "properties": {
                "query": {"type": "string"},
            },
        }

    def test_non_object_root_schema_degrades_to_empty_object(self) -> None:
        assert normalize_mcp_input_schema(
            {"type": "array", "items": {"type": "string"}}
        ) == {
            "type": "object",
            "properties": {},
        }

    def test_non_object_root_schema_logs_warning(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        caplog.set_level("WARNING")

        normalize_mcp_input_schema(
            {"type": "array", "items": {"type": "string"}},
            tool_name="falcon_list_enabled_modules",
        )

        assert "falcon_list_enabled_modules" in caplog.text
        assert "falling back to empty object schema" in caplog.text


class TestMCPToolDefinition:
    def test_tool_definition_uses_normalized_schema(self) -> None:
        tool = MCPTool(
            tool_id=1,
            emitter=MagicMock(),
            mcp_server=cast(MCPServer, SimpleNamespace(name="crowdstrike")),
            tool_name="falcon_list_enabled_modules",
            tool_description="Lists enabled modules",
            tool_definition={},
        )

        definition = tool.tool_definition()

        assert definition["type"] == "function"
        assert definition["function"]["name"] == "falcon_list_enabled_modules"
        assert definition["function"]["parameters"] == {
            "type": "object",
            "properties": {},
        }
