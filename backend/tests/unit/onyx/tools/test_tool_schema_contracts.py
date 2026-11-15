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


def _strict_parameters(**properties: JsonValue) -> dict[str, JsonValue]:
    return {
        "type": "object",
        "additionalProperties": False,
        "properties": properties,
        "required": list(properties),
    }


def _nullable(schema: dict[str, JsonValue], description: str) -> JsonValue:
    return {"anyOf": [schema, {"type": "null"}], "description": description}


_STRING: dict[str, JsonValue] = {"type": "string"}
_INTEGER: dict[str, JsonValue] = {"type": "integer"}
_STRINGS: dict[str, JsonValue] = {"type": "array", "items": _STRING}


@pytest.mark.parametrize(
    ("tool_class", "parameters"),
    [
        (
            FileReaderTool,
            _strict_parameters(
                file_id={**_STRING, "description": "The UUID of the file to read."},
                start_char=_nullable(
                    _INTEGER,
                    "Character offset to start reading from. Use null for the "
                    "default of 0.",
                ),
                num_chars=_nullable(
                    _INTEGER,
                    "Number of characters to return (max 16000). Use null for the "
                    "default of 16000.",
                ),
            ),
        ),
        (
            KnowledgeGraphTool,
            _strict_parameters(query={**_STRING, "description": "What to search for"}),
        ),
        (
            MemoryTool,
            _strict_parameters(
                memory={
                    **_STRING,
                    "description": "The text of the memory to add or update. "
                    "Should be a concise, standalone statement that captures the "
                    "key information. For example: 'User prefers dark mode' or "
                    "'User's favorite frontend framework is React'.",
                }
            ),
        ),
        (
            OpenURLTool,
            _strict_parameters(
                urls={
                    **_STRINGS,
                    "description": "List of URLs to open and read, can be a single "
                    "URL or multiple URLs. This will return the text content of the "
                    "page(s).",
                }
            ),
        ),
        (
            SearchTool,
            _strict_parameters(
                queries={
                    **_STRINGS,
                    "description": "List of up to 3 search queries to execute, "
                    "typically a single query. Later queries are ignored. Query "
                    "expansion and filter extraction steps will be run automatically "
                    "downstream, do not include time or source type scoping details "
                    "in your query.",
                }
            ),
        ),
        (
            WebSearchTool,
            _strict_parameters(
                queries={
                    **_STRINGS,
                    "description": "One or more queries to look up on the web. Must "
                    "contain only printable characters",
                }
            ),
        ),
    ],
    ids=lambda value: value.__name__ if isinstance(value, type) else "",
)
def test_builtin_tool_parameters_come_from_arguments(
    tool_class: type[Tool], parameters: dict[str, JsonValue]
) -> None:
    assert _builtin_definition(tool_class).parameters == parameters


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
