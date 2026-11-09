"""Property tests for the stub generator: names and schemas come from MCP servers."""

import ast

from hypothesis import given, settings
from hypothesis import strategies as st
from pydantic import JsonValue

from onyx.llm.models import ToolResult
from onyx.tools.tool_implementations.code_mode.stubs import build_tool_stubs
from tests.unit.onyx.tools.code_mode.fakes import FakeMCPTool, FakeTool

# Any text, lone surrogates included: a server can send any JSON string.
_TEXT = st.text(st.characters(exclude_categories=()), max_size=12)
_NAMES = st.text(st.characters(exclude_categories=()), min_size=1, max_size=12)

_LEAF: st.SearchStrategy[JsonValue] = st.one_of(
    st.sampled_from(
        [{"type": kind} for kind in ("string", "integer", "number", "boolean", "null")]
    ),
    st.builds(
        lambda values: {"enum": values},
        st.lists(
            st.one_of(_TEXT, st.integers(), st.none(), st.booleans()),
            min_size=1,
            max_size=3,
        ),
    ),
    st.builds(lambda text: {"type": "string", "description": text}, _TEXT),
)


def _object(properties: dict[str, JsonValue], required: int) -> JsonValue:
    return {
        "type": "object",
        "properties": properties,
        "required": list(properties)[:required],
    }


_SCHEMA: st.SearchStrategy[JsonValue] = st.recursive(
    _LEAF,
    lambda children: st.one_of(
        st.builds(
            _object,
            st.dictionaries(_NAMES, children, max_size=4),
            st.integers(0, 2),
        ),
        st.builds(lambda items: {"type": "array", "items": items}, children),
        st.builds(
            lambda options: {"anyOf": options},
            st.lists(children, min_size=1, max_size=3),
        ),
        st.builds(
            lambda kinds: {"type": kinds},
            st.lists(
                st.sampled_from(["string", "integer", "null", "object"]),
                min_size=1,
                max_size=3,
                unique=True,
            ),
        ),
    ),
    max_leaves=12,
)
_OUTPUT_SCHEMA = st.one_of(
    st.none(),
    st.builds(_object, st.dictionaries(_NAMES, _SCHEMA, max_size=4), st.integers(0, 2)),
)


def _unused(*_: object) -> ToolResult:
    return ToolResult(content="")


# Derandomized, so each CI run checks the same examples and cannot flake.
@settings(max_examples=150, deadline=None, derandomize=True)
@given(
    names=st.lists(_NAMES, min_size=1, max_size=4, unique=True),
    server=_NAMES,
    parameters=st.dictionaries(_NAMES, _SCHEMA, max_size=5),
    output_schema=_OUTPUT_SCHEMA,
)
def test_stubs_always_parse_and_keep_every_tool(
    names: list[str],
    server: str,
    parameters: dict[str, JsonValue],
    output_schema: dict[str, JsonValue] | None,
) -> None:
    schema: dict[str, JsonValue] = {"type": "object", "properties": parameters}
    tools = [
        *(
            FakeMCPTool(
                name, _unused, schema, server=server, output_schema=output_schema
            )
            for name in names
        ),
        FakeTool("plain", _unused),
    ]

    stubs = build_tool_stubs(tools)

    ast.parse(stubs.program_text(" ".join(stubs.functions)))
    assert len(stubs.functions) == len(tools)
    assert "plain" in stubs.functions
