"""Owned tools author strict schemas; external schemas keep their contracts."""

import pytest
from jsonschema import Draft202012Validator
from pydantic import JsonValue

from onyx.coding_agent.tool_definitions import (
    BASH_TOOL_DESCRIPTION,
    CODING_AGENT_THINK_TOOL_DESCRIPTION,
    CODING_AGENT_TOOL_DESCRIPTION,
    GENERATE_ANSWER_TOOL_DESCRIPTION,
)
from onyx.deep_research.tool_definitions import (
    GENERATE_PLAN_TOOL_DESCRIPTION,
    GENERATE_REPORT_TOOL_DESCRIPTION,
    RESEARCH_AGENT_GENERATE_REPORT_TOOL_DESCRIPTION,
    RESEARCH_AGENT_THINK_TOOL_DESCRIPTION,
    RESEARCH_AGENT_TOOL_DESCRIPTION,
    THINK_TOOL_DESCRIPTION,
)
from onyx.llm.models import ToolDefinition
from onyx.tools.interface import Tool
from onyx.tools.tool_implementations.bash.bash_tool import BashTool
from onyx.tools.tool_implementations.coding_agent.coding_agent_tool import (
    CodingAgentTool,
)
from onyx.tools.tool_implementations.custom.openapi_parsing import MethodSpec
from onyx.tools.tool_implementations.file_reader.file_reader_tool import FileReaderTool
from onyx.tools.tool_implementations.images.image_generation_tool import (
    ImageGenerationTool,
)
from onyx.tools.tool_implementations.knowledge_graph.knowledge_graph_tool import (
    KnowledgeGraphTool,
)
from onyx.tools.tool_implementations.memory.memory_tool import MemoryTool
from onyx.tools.tool_implementations.open_url.open_url_tool import OpenURLTool
from onyx.tools.tool_implementations.python.python_tool import PythonTool
from onyx.tools.tool_implementations.search.search_tool import SearchTool
from onyx.tools.tool_implementations.web_search.web_search_tool import WebSearchTool


def _builtin_definition(tool_class: type[Tool]) -> ToolDefinition:
    # Definitions use class constants; constructing live clients is unnecessary.
    tool = tool_class.__new__(tool_class)
    if isinstance(tool, OpenURLTool):
        tool._web_fetch_disabled = False
    return tool.tool_definition()


def _check_closed_objects(schema: JsonValue) -> None:
    assert isinstance(schema, dict)
    if schema.get("type") == "object":
        assert schema["additionalProperties"] is False
        properties = schema["properties"]
        assert isinstance(properties, dict)
        required = schema["required"]
        assert isinstance(required, list)
        assert set(required) == set(properties)
        for prop in properties.values():
            _check_closed_objects(prop)
    if "items" in schema:
        _check_closed_objects(schema["items"])
    if "anyOf" in schema:
        options = schema["anyOf"]
        assert isinstance(options, list)
        for option in options:
            _check_closed_objects(option)


@pytest.mark.parametrize(
    "definition",
    [
        *[
            _builtin_definition(tool_class)
            for tool_class in (
                BashTool,
                CodingAgentTool,
                FileReaderTool,
                ImageGenerationTool,
                KnowledgeGraphTool,
                MemoryTool,
                OpenURLTool,
                PythonTool,
                SearchTool,
                WebSearchTool,
            )
        ],
        BASH_TOOL_DESCRIPTION,
        CODING_AGENT_THINK_TOOL_DESCRIPTION,
        CODING_AGENT_TOOL_DESCRIPTION,
        GENERATE_ANSWER_TOOL_DESCRIPTION,
        GENERATE_PLAN_TOOL_DESCRIPTION,
        GENERATE_REPORT_TOOL_DESCRIPTION,
        RESEARCH_AGENT_GENERATE_REPORT_TOOL_DESCRIPTION,
        RESEARCH_AGENT_THINK_TOOL_DESCRIPTION,
        RESEARCH_AGENT_TOOL_DESCRIPTION,
        THINK_TOOL_DESCRIPTION,
    ],
    ids=lambda definition: definition.name,
)
def test_owned_tool_schema_is_strict(definition: ToolDefinition) -> None:
    assert definition.strict
    schema = definition.parameters
    assert schema["type"] == "object"
    Draft202012Validator.check_schema(schema)
    _check_closed_objects(schema)


def test_openapi_tool_preserves_external_schema_and_stays_non_strict() -> None:
    external_schema: dict[str, JsonValue] = {
        "type": "object",
        "properties": {"metadata": {"type": "object", "properties": {}}},
    }
    method = MethodSpec(
        name="update_metadata",
        raw_name="update_metadata",
        summary="Update metadata",
        path="/metadata",
        method="post",
        spec={
            "requestBody": {
                "content": {"application/json": {"schema": external_schema}}
            }
        },
    )
    definition = method.to_tool_definition()
    assert not definition.strict
    assert definition.parameters == {
        "type": "object",
        "properties": {"requestBody": external_schema},
    }
    Draft202012Validator(definition.parameters).validate(
        {"requestBody": {"metadata": {"arbitrary_key": None}}}
    )
