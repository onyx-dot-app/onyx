import json
from uuid import uuid4

import pytest
from pydantic import JsonValue

from onyx.llm.models import ToolResult
from onyx.tools.models import (
    CodeModeExposure,
    CodeModeResultSpec,
    LlmPythonExecutionResult,
)
from onyx.tools.tool_implementations.code_mode.stubs import (
    MAX_STUB_CHARS,
    build_tool_stubs,
    function_name,
    program_value,
    schema_annotation,
    tool_arguments,
)
from onyx.tools.tool_implementations.images.image_generation_tool import (
    ImageGenerationTool,
)
from onyx.tools.tool_implementations.python.python_tool import PythonTool
from tests.unit.onyx.tools.code_mode.fakes import (
    FakeMCPTool,
    FakeTool,
    FakeWebSearchTool,
)


def _unused(*_: object) -> ToolResult:
    return ToolResult(content="")


@pytest.mark.parametrize(
    ("tool_name", "expected"),
    [
        ("mcp-server.get-issue", "mcp_server_get_issue"),
        ("3d_render", "tool_3d_render"),
        ("print", "print_tool"),
        ("class", "class_tool"),
        ("json", "json_tool"),
        ("typing", "typing_tool"),
        ("os", "os_tool"),
        ("store", "store_tool"),
        ("load", "load_tool"),
        ("TypedDict", "TypedDict_tool"),
        ("tool_search", "tool_search_tool"),
        ("functions", "functions_tool"),
        ("yield_control", "yield_control_tool"),
        ("SearchResults", "SearchResults"),
    ],
)
def test_function_names_avoid_invalid_and_reserved_names(
    tool_name: str, expected: str
) -> None:
    assert function_name(tool_name) == expected


def test_function_names_avoid_the_declared_result_types() -> None:
    tools = [
        FakeWebSearchTool(_unused),
        FakeTool("SearchResults", _unused),
        FakeTool("SearchResult", _unused),
    ]
    functions = build_tool_stubs(tools).functions
    assert functions["SearchResults_tool"].tool.name == "SearchResults"
    assert functions["SearchResult_tool"].tool.name == "SearchResult"


def test_function_names_are_unique_and_sorted() -> None:
    tools = [FakeTool(name, _unused) for name in ["b-tool", "b_tool", "a"]]
    functions = build_tool_stubs(tools).functions
    assert list(functions) == ["a", "b_tool", "b_tool_2"]
    assert functions["b_tool"].tool.name == "b-tool"


def test_built_in_like_search_tool_gets_typed_result() -> None:
    stubs = build_tool_stubs([FakeWebSearchTool(_unused)])
    # The stub declares the JSON of the results model: keys it leaves out when
    # empty are NotRequired, and field descriptions become docstrings.
    assert "class SearchResult(TypedDict):" in stubs.text
    assert (
        '    document: int\n    """Citation number. Cite it in the answer as [n]."""'
        in stubs.text
    )
    assert "    url: NotRequired[str]\n" in stubs.text
    assert "class SearchResults(TypedDict):\n    results: list[SearchResult]" in (
        stubs.text
    )
    assert "async def web_search(*, queries: list[str]) -> SearchResults:" in stubs.text
    assert "Search the web for information." in stubs.text


class _BatchedSearchTool(FakeWebSearchTool):
    @property
    def code_mode_result(self) -> CodeModeResultSpec:
        return super().code_mode_result.model_copy(
            update={"usage": "Pass all queries in one call."}
        )


def test_usage_note_reaches_the_docstring() -> None:
    stubs = build_tool_stubs([_BatchedSearchTool(_unused)])
    assert "snippets.\n\n    Pass all queries in one call.\n\n    Args:" in stubs.text


def test_mcp_like_schema_with_odd_names_and_refs() -> None:
    parameters: dict[str, JsonValue] = {
        "type": "object",
        "$defs": {
            "Label": {"type": "object", "properties": {"name": {"type": "string"}}},
            "Node": {
                "type": "object",
                "properties": {"child": {"$ref": "#/$defs/Node"}},
            },
        },
        "properties": {
            "repo-name": {"type": "string", "description": "Repository."},
            "state": {"enum": ["open", "closed"]},
            "labels": {"type": "array", "items": {"$ref": "#/$defs/Label"}},
            "limit": {"type": ["integer", "null"]},
            "node": {"$ref": "#/$defs/Node"},
            "filter": {"anyOf": [{"type": "string"}, {"type": "number"}]},
            "class": {"type": "boolean"},
        },
        "required": ["repo-name", "state"],
    }
    tool = FakeTool("mcp_github-list.issues", _unused, parameters=parameters)
    stubs = build_tool_stubs([tool])
    function = stubs.functions["mcp_github_list_issues"]

    assert (
        "async def mcp_github_list_issues(*, repo_name: str, "
        "state: Literal['open', 'closed'], class_: bool | None = None, "
        "filter: str | float | None = None, "
        "labels: list[dict[str, Any]] | None = None, limit: int | None = None, "
        "node: dict[str, Any] | None = None) -> Any:"
    ) in function.stub
    assert "Tool name: mcp_github-list.issues" in function.stub
    assert "(tool argument `repo-name`) Repository." in function.stub
    assert function.argument_names["repo_name"] == "repo-name"
    assert function.argument_names["class_"] == "class"
    assert tool_arguments(function, {"repo_name": "onyx", "limit": None}) == {
        "repo-name": "onyx"
    }
    with pytest.raises(TypeError, match="Argument `limit` of .* must be JSON data"):
        tool_arguments(function, {"repo_name": "onyx", "limit": float("nan")})


def test_openapi_like_schema_without_required_makes_every_argument_optional() -> None:
    parameters: dict[str, JsonValue] = {
        "type": "object",
        "properties": {
            "requestBody": {
                "type": "object",
                "properties": {"title": {"type": "string"}},
            },
            "id": {"type": "integer"},
        },
    }
    stubs = build_tool_stubs(
        [FakeTool("create_ticket", _unused, parameters=parameters)]
    )
    stub = stubs.functions["create_ticket"].stub
    assert (
        "async def create_ticket(*, id: int | None = None, "
        "requestBody: dict[str, Any] | None = None) -> Any:"
    ) in stub
    assert "requestBody: Keys: title?." in stub


def test_strict_nullable_required_arguments_are_optional_and_sent_as_null() -> None:
    parameters: dict[str, JsonValue] = {
        "type": "object",
        "properties": {
            "file_id": {"type": "string"},
            "start_char": {"anyOf": [{"type": "integer"}, {"type": "null"}]},
            "mode": {"type": ["string", "null"], "enum": ["a", "b", None]},
        },
        "required": ["file_id", "start_char", "mode"],
        "additionalProperties": False,
    }
    stubs = build_tool_stubs([FakeTool("read", _unused, parameters=parameters)])
    function = stubs.functions["read"]
    assert (
        "async def read(*, file_id: str, mode: Literal['a', 'b'] | None = None, "
        "start_char: int | None = None) -> Any:"
    ) in function.stub
    assert tool_arguments(function, {"file_id": "f", "start_char": 5}) == {
        "file_id": "f",
        "start_char": 5,
        "mode": None,
    }


def test_recursive_refs_are_bounded() -> None:
    root: dict[str, JsonValue] = {
        "$defs": {"Tree": {"type": "array", "items": {"$ref": "#/$defs/Tree"}}}
    }
    annotation = schema_annotation({"$ref": "#/$defs/Tree"}, root)
    assert annotation == "list[list[Any]]"


def test_oversized_stub_falls_back_to_any() -> None:
    properties: dict[str, JsonValue] = {
        f"field_{index}": {"enum": [f"value_{index}_{n}" for n in range(60)]}
        for index in range(40)
    }
    tool = FakeTool(
        "big", _unused, parameters={"type": "object", "properties": properties}
    )
    stub = build_tool_stubs([tool]).functions["big"].stub
    assert len(stub) <= MAX_STUB_CHARS
    assert "field_0: Any = None" in stub


def test_stub_text_is_deterministic() -> None:
    tools = [
        FakeTool("zeta", _unused),
        FakeWebSearchTool(_unused),
        FakeTool("a", _unused),
    ]
    first = build_tool_stubs(tools).text
    second = build_tool_stubs(list(reversed(tools))).text
    assert first == second
    assert first.index("async def a(") < first.index("async def web_search(")


class FakeImageGenerationTool(ImageGenerationTool):
    """An image generation tool without a provider; only its stub is used."""

    def __init__(self) -> None:
        self._id = 5


def test_image_generation_returns_typed_images() -> None:
    stubs = build_tool_stubs([FakeImageGenerationTool()])
    function = stubs.functions["generate_image"]
    assert (
        "class ImageResult(TypedDict):\n    file_id: str\n    revised_prompt: str"
    ) in stubs.text
    assert "async def generate_image(*, prompt: str, " in function.stub
    assert ") -> list[ImageResult]:" in function.stub
    assert "The images are shown to the user automatically." in function.stub

    images = [{"file_id": "f1", "revised_prompt": "a red fox"}]
    assert program_value(function, ToolResult(content=json.dumps(images))) == images
    with pytest.raises(RuntimeError, match="content policy"):
        program_value(
            function,
            ToolResult(content=json.dumps({"error": "content policy"}), is_error=True),
        )


def test_python_results_declare_the_fields_of_their_model() -> None:
    stubs = build_tool_stubs([PythonTool(tool_id=4, chat_session_id=uuid4())])
    for name, field in LlmPythonExecutionResult.model_fields.items():
        if name != "generated_files":
            assert f"    {name}: " in stubs.text, field
    assert "    generated_files: list[PythonExecutionFile]" in stubs.text
    assert "class PythonExecutionFile(TypedDict):" in stubs.text
    assert ") -> LlmPythonExecutionResult:" in stubs.functions["run_python"].stub


def test_tool_search_ranks_name_matches_first_and_bounds_the_count() -> None:
    tools = [
        FakeTool(
            name, _unused, description=description, exposure=CodeModeExposure.DEFERRED
        )
        for name, description in [
            ("list_tickets", "List support tickets."),
            ("get_uptime", "Uptime of a service; tickets are not included."),
            ("send_email", "Send an email."),
        ]
    ]
    index = build_tool_stubs(tools).tool_index
    assert index is not None

    assert [match.name for match in index.search("tickets", 8)] == [
        "list_tickets",
        "get_uptime",
    ]
    [match] = index.tool_search("tickets", limit=1)
    assert match == {
        "name": "list_tickets",
        "description": "List support tickets.",
        "stub": index.search("tickets", 1)[0].stub,
    }
    assert index.tool_search("weather") == []
    with pytest.raises(TypeError):
        index.tool_search(1)


def test_mcp_output_schema_types_the_result() -> None:
    tool = FakeMCPTool(
        "list-tickets",
        _unused,
        {
            "type": "object",
            "properties": {"service": {"type": "string"}},
            "required": ["service"],
        },
        output_schema={
            "type": "object",
            "properties": {
                "tickets": {"type": "array", "items": {"type": "object"}},
                "next_page": {"type": "string"},
            },
            "required": ["tickets"],
        },
    )
    function = build_tool_stubs([tool]).functions["acme__list_tickets"]
    declarations = "\n".join(function.declarations)
    assert "class AcmeListTicketsResult(TypedDict):" in declarations
    assert "next_page: NotRequired[str]" in declarations
    assert "-> AcmeListTicketsResult:" in function.stub
