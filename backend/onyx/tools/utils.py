import json
from collections.abc import Callable
from typing import Any

from onyx.llm.model_capabilities import find_model_obj, get_model_map
from onyx.tools.interface import Tool


def explicit_tool_calling_supported(model_provider: str, model_name: str) -> bool:
    model_map = get_model_map()
    model_obj = find_model_obj(
        model_map=model_map,
        provider=model_provider,
        model_name=model_name,
    )

    if not model_obj:
        return False
    return bool(model_obj.get("supports_function_calling"))


def compute_tool_tokens(tool: Tool, token_counter: Callable[[str], int]) -> int:
    return token_counter(json.dumps(tool.tool_definition()))


def compute_all_tool_tokens(
    tools: list[Tool], token_counter: Callable[[str], int]
) -> int:
    return sum(compute_tool_tokens(tool, token_counter) for tool in tools)


def compute_tool_definition_tokens(
    tool_definitions: list[dict[str, Any]], token_counter: Callable[[str], int]
) -> int:
    return sum(
        token_counter(json.dumps(tool_definition))
        for tool_definition in tool_definitions
    )


def generate_tools_description(tools: list[Tool]) -> str:
    if not tools:
        return ""
    if len(tools) == 1:
        return tools[0].name
    if len(tools) == 2:
        return f"{tools[0].name} and {tools[1].name}"

    names = [tool.name for tool in tools[:-1]]
    return ", ".join(names) + f", and {tools[-1].name}"
