"""Guards built-in tool LLM-facing names against OpenAI's reserved function names.

OpenAI reserves certain function names for its own model harness and rejects any
request whose tools array defines one of them (400 invalid_request_error:
"The function name 'python' is reserved for use by this model."), enforced
server-side since 2026-07-21. A collision breaks every chat that has the tool
attached, across all GPT models served via api.openai.com.
"""

from onyx.tools.built_in_tools import (
    BUILT_IN_TOOL_MAP,
    TOOL_NAME_TO_CLASS,
    llm_tool_name,
)

# Names OpenAI is known to reserve. Extend if OpenAI reserves more of its
# harness tool names (e.g. "browser", "bash") and starts rejecting them.
OPENAI_RESERVED_FUNCTION_NAMES = {"python"}


def test_builtin_tool_names_avoid_openai_reserved_names() -> None:
    for tool_name in TOOL_NAME_TO_CLASS:
        assert tool_name not in OPENAI_RESERVED_FUNCTION_NAMES, (
            f"Built-in tool name {tool_name!r} collides with an OpenAI-reserved "
            "function name; OpenAI rejects requests defining it. Rename the "
            "tool's NAME (and migrate the tool table's name column)."
        )


def test_tool_name_map_covers_all_builtin_tools() -> None:
    # Every built-in tool must resolve to an LLM-facing name — a missing entry
    # would silently skip the reserved-name check above.
    assert len(TOOL_NAME_TO_CLASS) == len(BUILT_IN_TOOL_MAP)


def test_llm_tool_name_resolves_builtins_from_code() -> None:
    # The tool table's name column is seeded by migration and still says
    # "python" on existing deployments; the code constant must win so history
    # replay never sends the reserved name to OpenAI.
    assert llm_tool_name("PythonTool", "python") == "run_python"


def test_llm_tool_name_passes_through_custom_tools() -> None:
    # Custom/MCP tools have no in-code class; their DB name is authoritative.
    assert llm_tool_name(None, "my_custom_tool") == "my_custom_tool"
    assert llm_tool_name("NotARealBuiltin", "my_custom_tool") == "my_custom_tool"
