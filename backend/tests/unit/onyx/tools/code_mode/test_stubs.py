import ast
import json
from collections.abc import Iterator
from uuid import uuid4

import pytest
from pydantic import BaseModel, Field, JsonValue, create_model
from pydantic_monty import Monty, MontyTypingError

from onyx.llm.models import ToolResult
from onyx.tools.models import (
    CodeModeExposure,
    CodeModeResultKind,
    CodeModeResultSpec,
    LlmPythonExecutionResult,
)
from onyx.tools.tool_implementations.code_mode.sandbox import PRELUDE_STUBS
from onyx.tools.tool_implementations.code_mode.stubs import (
    MAX_STUB_CHARS,
    ToolStubs,
    build_tool_stubs,
    function_name,
    model_declarations,
    program_value,
    schema_type,
    tool_arguments,
)
from onyx.tools.tool_implementations.code_mode.tool_search import MAX_TOOL_SEARCH_LIMIT
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


def _full_text(stubs: ToolStubs) -> str:
    """The stub module of a program that names every function."""
    return stubs.program_text(" ".join(stubs.functions))


def _with_deferred(count: int) -> ToolStubs:
    """A listed tool and `count` MCP tools, each with its own result type."""
    parameters: dict[str, JsonValue] = {
        "type": "object",
        "properties": {"value": {"type": "string"}},
    }
    return build_tool_stubs(
        [
            FakeTool("listed", _unused),
            *(
                FakeMCPTool(
                    f"remote_{index}",
                    _unused,
                    parameters,
                    output_schema={
                        "type": "object",
                        "properties": {f"field_{index}": {"type": "string"}},
                    },
                )
                for index in range(count)
            ),
        ]
    )


def test_a_program_type_checks_against_only_the_functions_it_names() -> None:
    code = "print(await mcp__acme_1__remote_3(value='x'))\n"
    stubs = _with_deferred(300)
    text = stubs.program_text(code)
    # The text does not grow with the deferred functions that the code does
    # not name.
    assert text == _with_deferred(10).program_text(code)
    assert "async def listed(" in text and "async def mcp__acme_1__remote_3(" in text
    assert "field_3: NotRequired[str]" in text
    assert "remote_4" not in text and "field_4" not in text
    assert PRELUDE_STUBS in text and PRELUDE_STUBS not in stubs.listed_text
    # Python reads names in NFKC form.
    assert "def mcp__acme_1__remote_5(" in stubs.program_text(
        "await mcp__\uff41cme_1__remote_5()"
    )


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
    assert "class SearchResult(TypedDict):" in _full_text(stubs)
    assert (
        '    document: int\n    """Citation number. Cite it in the answer as [n]."""'
        in _full_text(stubs)
    )
    assert "    url: NotRequired[str]\n" in _full_text(stubs)
    assert "class SearchResults(TypedDict):\n    results: list[SearchResult]" in (
        _full_text(stubs)
    )
    assert (
        "async def web_search(*, queries: list[str]) -> SearchResults:"
        in _full_text(stubs)
    )
    assert "Search the web for information." in _full_text(stubs)


class _BatchedSearchTool(FakeWebSearchTool):
    @property
    def code_mode_result(self) -> CodeModeResultSpec:
        return super().code_mode_result.model_copy(
            update={"usage": "Pass all queries in one call."}
        )


def test_usage_note_reaches_the_docstring() -> None:
    stubs = build_tool_stubs([_BatchedSearchTool(_unused)])
    assert "snippets.\n\n    Pass all queries in one call.\n\n    Args:" in _full_text(
        stubs
    )


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
    # An explicit None is sent for an argument that accepts null only.
    assert tool_arguments(
        function, {"repo_name": "onyx", "limit": None, "class_": None}
    ).value == {"repo-name": "onyx", "limit": None}
    with pytest.raises(TypeError, match=r"must be JSON data.* at \['limit'\]"):
        tool_arguments(function, {"repo_name": "onyx", "limit": float("nan")})


def test_tool_arguments_stop_at_their_byte_limit() -> None:
    function = build_tool_stubs([FakeTool("echo", _unused)]).functions["echo"]
    shared: list[object] = ["x" * 1024]
    for _ in range(40):
        shared = [shared, shared]
    with pytest.raises(ValueError, match="exceeds the limit of 262144 bytes"):
        tool_arguments(function, {"value": shared})


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
    assert tool_arguments(function, {"file_id": "f", "start_char": 5}).value == {
        "file_id": "f",
        "start_char": 5,
        "mode": None,
    }


def test_null_admitted_through_enum_const_or_ref_is_sent() -> None:
    parameters: dict[str, JsonValue] = {
        "type": "object",
        "$defs": {"MaybeInt": {"anyOf": [{"type": "integer"}, {"type": "null"}]}},
        "properties": {
            "mode": {"enum": ["a", None]},
            "unset": {"const": None},
            "count": {"$ref": "#/$defs/MaybeInt"},
            "label": {"enum": ["x", "y"]},
        },
        "required": ["mode", "unset", "count"],
    }
    function = build_tool_stubs(
        [FakeTool("update", _unused, parameters=parameters)]
    ).functions["update"]
    assert function.nullable_arguments == {"mode", "unset", "count"}
    assert tool_arguments(function, {"mode": None, "label": None}).value == {
        "mode": None,
        "unset": None,
        "count": None,
    }


def test_a_long_ref_chain_builds_and_types_nullability_with_its_annotation() -> None:
    length = 1_200
    defs: dict[str, JsonValue] = {
        f"d{index}": {"$ref": f"#/$defs/d{index + 1}"} for index in range(length)
    }
    defs[f"d{length}"] = {"type": ["integer", "null"]}
    parameters: dict[str, JsonValue] = {
        "type": "object",
        "$defs": defs,
        "properties": {
            "deep": {"$ref": "#/$defs/d0"},
            "near": {"$ref": f"#/$defs/d{length - 1}"},
        },
        "required": ["deep", "near"],
    }
    function = build_tool_stubs(
        [FakeTool("chain", _unused, parameters=parameters)]
    ).functions["chain"]
    # Past the depth bound the type is Any and null is not known to be
    # accepted; a short chain types both.
    assert "deep: Any" in function.stub
    assert "near: int | None = None" in function.stub
    assert function.nullable_arguments == {"near"}


def test_additional_properties_admit_other_keyword_arguments() -> None:
    open_map = FakeTool(
        "tag",
        _unused,
        parameters={"type": "object", "additionalProperties": {"type": "string"}},
    )
    mixed = FakeTool(
        "label",
        _unused,
        parameters={
            "type": "object",
            "properties": {"kwargs": {"type": "integer"}},
            "required": ["kwargs"],
            "additionalProperties": True,
        },
    )
    functions = build_tool_stubs([open_map, mixed]).functions
    assert "async def tag(**kwargs: str) -> Any:" in functions["tag"].stub
    assert "async def label(*, kwargs: int, **kwargs_: Any) -> Any:" in (
        functions["label"].stub
    )
    assert tool_arguments(functions["tag"], {"team": "core"}).value == {"team": "core"}


def test_argument_names_are_python_identifiers_in_normal_form() -> None:
    parameters: dict[str, JsonValue] = {
        "type": "object",
        "properties": {"version²": {"type": "string"}, "ﬁle": {"type": "string"}},
    }
    function = build_tool_stubs(
        [FakeTool("fetch", _unused, parameters=parameters)]
    ).functions["fetch"]
    assert function.argument_names == {"file": "ﬁle", "version2": "version²"}
    ast.parse(function.stub)


def test_required_entries_that_are_not_names_are_ignored() -> None:
    tool = FakeMCPTool(
        "list-tickets",
        _unused,
        {
            "type": "object",
            "properties": {"filter": {"type": "object", "required": [{}]}},
            "required": [[], "filter"],
        },
        output_schema={
            "type": "object",
            "properties": {"tickets": {"type": "array"}},
            "required": [[]],
        },
    )
    function = build_tool_stubs([tool]).functions["mcp__acme_1__list_tickets"]
    assert function.required_arguments == {"filter"}
    assert "tickets: NotRequired[list[Any]]" in "\n".join(function.declarations)


def test_recursive_refs_are_bounded() -> None:
    root: dict[str, JsonValue] = {
        "$defs": {"Tree": {"type": "array", "items": {"$ref": "#/$defs/Tree"}}}
    }
    annotation = schema_type({"$ref": "#/$defs/Tree"}, root).annotation
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


def test_result_declarations_count_toward_the_stub_limit() -> None:
    tool = FakeMCPTool(
        "report",
        _unused,
        {"type": "object", "properties": {"id": {"type": "string"}}},
        output_schema={
            "type": "object",
            "properties": {
                **{f"field_{n}": {"type": "string"} for n in range(2_000)},
                "kind": {"enum": [f"kind_{n}" for n in range(3_000)]},
            },
        },
    )
    function = build_tool_stubs([tool]).functions["mcp__acme_1__report"]
    assert function.declarations == ()
    assert (
        "async def mcp__acme_1__report(*, id: str | None = None) -> Any:"
        in function.stub
    )
    assert len(function.stub) <= MAX_STUB_CHARS


def test_multi_member_all_of_is_any() -> None:
    root: dict[str, JsonValue] = {}
    assert (
        schema_type({"allOf": [{"type": "integer"}, {"minimum": 1}]}, root).annotation
        == "Any"
    )
    assert schema_type({"allOf": [{"type": "integer"}]}, root).annotation == "int"


def test_docstring_text_cannot_end_the_docstring() -> None:
    class _QuotedTool(FakeTool):
        @property
        def code_mode_result(self) -> CodeModeResultSpec:
            return super().code_mode_result.model_copy(
                update={"returns": 'The """ text \\'}
            )

    stubs = build_tool_stubs(
        [_QuotedTool('a"""b\\', _unused, description='Ends with """')]
    )
    ast.parse(_full_text(stubs))
    assert 'Tool name: a\\"""b\\\\' in _full_text(stubs)

    class _Quoted(BaseModel):
        name: str = Field(description='Ends with "a quote"')

    [declaration] = model_declarations(_Quoted)
    [class_def] = ast.parse(declaration).body
    assert isinstance(class_def, ast.ClassDef)
    assert [
        node.value.value
        for node in class_def.body
        if isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant)
    ] == ['Ends with "a quote"']


@pytest.fixture(scope="module")
def type_checker() -> Iterator[Monty]:
    with Monty(min_processes=1, max_processes=1) as pool:
        yield pool


@pytest.mark.parametrize("name", ["\x00", "a\rb", "\ud800"])
def test_control_characters_in_a_tool_name_keep_the_stubs_valid(
    name: str, type_checker: Monty
) -> None:
    stubs = build_tool_stubs([FakeTool(name, _unused), FakeTool("plain", _unused)])

    module = ast.parse(_full_text(stubs))

    docstrings = [
        ast.get_docstring(node, clean=False)
        for node in module.body
        if isinstance(node, ast.AsyncFunctionDef)
    ]
    assert any(f"Tool name: {name}\n" in (text or "") for text in docstrings)

    # The sandbox's type checker reads the same stubs: a wrong argument to the
    # ordinary tool is its only diagnostic.
    code = "await plain(value=1)\n"
    with (
        type_checker.checkout(
            type_check=True,
            type_check_stubs=stubs.program_text(code),
            type_check_format="concise",
        ) as session,
        pytest.raises(MontyTypingError) as error,
    ):
        session.feed_run(code)
    assert str(error.value).strip().splitlines() == [
        "main.py:1:13: error[invalid-argument-type] Argument to function `plain` "
        "is incorrect: Expected `str`, found `Literal[1]`"
    ]


@pytest.mark.parametrize("description", ["\x00", "a\rb", "\ud800"])
def test_control_characters_in_a_field_description_keep_the_model_valid(
    description: str,
) -> None:
    model = create_model("Odd", value=(str, Field(description=description)))

    [declaration] = model_declarations(model)

    [class_def] = ast.parse(declaration).body
    assert isinstance(class_def, ast.ClassDef)
    assert [
        node.value.value
        for node in class_def.body
        if isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant)
    ] == [description]


def test_an_invalid_schema_type_renders_as_any_without_failing_other_tools() -> None:
    odd = FakeTool(
        "odd",
        _unused,
        parameters={"type": "object", "properties": {"value": {"type": {}}}},
    )
    functions = build_tool_stubs([odd, FakeTool("plain", _unused)]).functions
    assert "async def odd(*, value: Any = None) -> Any:" in functions["odd"].stub
    assert "plain" in functions


def test_stub_text_is_deterministic() -> None:
    tools = [
        FakeTool("zeta", _unused),
        FakeWebSearchTool(_unused),
        FakeTool("a", _unused),
    ]
    first = _full_text(build_tool_stubs(tools))
    second = _full_text(build_tool_stubs(list(reversed(tools))))
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
    ) in _full_text(stubs)
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
            assert f"    {name}: " in _full_text(stubs), field
    assert "    generated_files: list[PythonExecutionFile]" in _full_text(stubs)
    assert "class PythonExecutionFile(TypedDict):" in _full_text(stubs)
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
    with pytest.raises(ValueError):
        index.tool_search("tickets", limit=0)

    many = build_tool_stubs(
        [
            FakeTool(f"ticket_{n}", _unused, exposure=CodeModeExposure.DEFERRED)
            for n in range(MAX_TOOL_SEARCH_LIMIT + 5)
        ]
    ).tool_index
    assert many is not None
    assert len(many.tool_search("ticket", limit=100)) == MAX_TOOL_SEARCH_LIMIT


def test_tool_search_matches_words_in_any_script() -> None:
    tools = [
        FakeTool(
            name, _unused, description=description, exposure=CodeModeExposure.DEFERRED
        )
        for name, description in [
            ("billing_lookup", "Rechnungen und Zahlungsstatus prüfen."),
            ("ticket_lookup", "Найти заявки в службе поддержки."),
        ]
    ]
    index = build_tool_stubs(tools).tool_index
    assert index is not None
    assert [match.name for match in index.search("заявки", 8)] == ["ticket_lookup"]
    assert [match.name for match in index.search("prüfen", 8)] == ["billing_lookup"]


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
    function = build_tool_stubs([tool]).functions["mcp__acme_1__list_tickets"]
    declarations = "\n".join(function.declarations)
    assert "class McpAcme1ListTicketsResult(TypedDict):" in declarations
    assert "next_page: NotRequired[str]" in declarations
    assert "-> McpAcme1ListTicketsResult:" in function.stub


def test_mcp_result_types_are_python_names_that_match_their_keys() -> None:
    def tool(output_schema: dict[str, JsonValue]) -> FakeMCPTool:
        return FakeMCPTool(
            "list_items",
            _unused,
            {"type": "object", "properties": {}},
            server="_3d",
            output_schema=output_schema,
        )

    items: dict[str, JsonValue] = {
        "type": "object",
        "properties": {"items": {"type": "array"}},
    }
    stubs = build_tool_stubs([tool(items)])
    [function] = stubs.functions.values()
    assert "class Mcp3d1ListItemsResult(TypedDict):" in function.declarations[0]
    ast.parse(_full_text(stubs))

    # Python reads the field `ﬁle` as `file`, which is not the JSON key.
    compatibility: dict[str, JsonValue] = {
        "type": "object",
        "properties": {"ﬁle": {"type": "string"}},
    }
    [function] = build_tool_stubs([tool(compatibility)]).functions.values()
    assert function.declarations == ()
    assert ") -> dict[str, Any]:" in function.stub


def _titled_item() -> type[BaseModel]:
    class Item(BaseModel):
        title: str

    return Item


def _linked_item() -> type[BaseModel]:
    class Item(BaseModel):
        url: str

    return Item


def test_result_models_with_one_name_are_rejected() -> None:
    result = create_model(
        "Result", first=(_titled_item(), ...), second=(_linked_item(), ...)
    )

    class _ModelTool(FakeTool):
        @property
        def code_mode_result(self) -> CodeModeResultSpec:
            return CodeModeResultSpec(kind=CodeModeResultKind.JSON_OBJECT, model=result)

    # Both Item models are declared, so neither is dropped without notice.
    assert [d.splitlines()[0] for d in model_declarations(result)] == [
        "class Item(TypedDict):",
        "class Item(TypedDict):",
        "class Result(TypedDict):",
    ]
    with pytest.raises(ValueError, match="Two result models are named Item"):
        build_tool_stubs([_ModelTool("fetch", _unused)])


def test_soft_keywords_keep_their_names_as_arguments_and_fields() -> None:
    schema: dict[str, JsonValue] = {
        "type": "object",
        "properties": {"type": {"type": "string"}},
        "required": ["type"],
    }
    tool = FakeMCPTool("list_items", _unused, schema, output_schema=schema)
    function = build_tool_stubs([tool]).functions["mcp__acme_1__list_items"]
    assert (
        "async def mcp__acme_1__list_items(*, type: str) -> McpAcme1ListItemsResult:"
        in (function.stub)
    )
    assert (
        "class McpAcme1ListItemsResult(TypedDict):\n    type: str"
        in (function.declarations[0])
    )
    assert function.argument_names == {"type": "type"}
