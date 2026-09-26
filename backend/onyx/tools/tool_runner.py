from collections.abc import Callable
from functools import partial

from pydantic import JsonValue

from onyx.agents.models import RunState
from onyx.agents.tools import AgentTool, ToolInvocation, ToolOutcome
from onyx.llm.models import ToolResult
from onyx.tools.interface import Tool, ToolContext
from onyx.tools.models import ToolCallException
from onyx.tools.tool_implementations.open_url.open_url_tool import OpenURLTool
from onyx.tools.tool_implementations.search.search_tool import SearchTool
from onyx.tools.tool_implementations.web_search.web_search_tool import WebSearchTool
from onyx.tracing.framework.create import function_span
from onyx.utils.logger import setup_logger

logger = setup_logger()


QUERIES_FIELD = "queries"
URLS_FIELD = "urls"

MERGEABLE_TOOL_FIELDS: dict[str, str] = {
    SearchTool.NAME: QUERIES_FIELD,
    WebSearchTool.NAME: QUERIES_FIELD,
    OpenURLTool.NAME: URLS_FIELD,
}


def _merge_tool_arguments(
    first: dict[str, JsonValue], second: dict[str, JsonValue], *, field: str
) -> dict[str, JsonValue] | None:
    """Combine query lists only when all other retrieval settings match.

    SearchTool and WebSearchTool merge queries; OpenURLTool merges urls.
    This collapses repeated retrieval calls into a single call per tool.
    Other tool calls are left unchanged.
    """
    if {key: value for key, value in first.items() if key != field} != {
        key: value for key, value in second.items() if key != field
    }:
        return None
    left, right = first.get(field), second.get(field)
    if not isinstance(left, list) or not isinstance(right, list):
        return None
    if (
        not left
        or not right
        or any(not isinstance(value, str) for value in left + right)
    ):
        return None
    merged_args = first.copy()
    merged_args[field] = left + right
    return merged_args


def _tool_failure(tool_name: str, error: ToolCallException) -> ToolResult:
    logger.warning("Tool call rejected by %s: %s", tool_name, error)
    return ToolResult(content=error.llm_facing_message, is_error=True)


def run_tool(
    tool: Tool, invocation: ToolInvocation, context: ToolContext
) -> ToolOutcome:
    invocation.cancellation.check()
    with function_span(tool.name) as span:
        span.span_data.input = str(invocation.arguments)
        try:
            result = tool.run(invocation, context)
        except ToolCallException as error:
            result = _tool_failure(tool.name, error)
        span.span_data.output = (
            result.text if isinstance(result, ToolResult) else result.model_dump_json()
        )
    invocation.cancellation.check()
    return result


def complete_tool_children(
    tool: Tool,
    invocation: ToolInvocation,
    context: ToolContext,
    children: list[RunState],
) -> ToolResult:
    invocation.cancellation.check()
    with function_span(tool.name) as span:
        span.span_data.input = str(invocation.arguments)
        try:
            result = tool.complete_children(invocation, context, children)
        except ToolCallException as error:
            result = _tool_failure(tool.name, error)
        span.span_data.output = result.text
    invocation.cancellation.check()
    return result


def bind_tool(tool: Tool, get_context: Callable[[], ToolContext]) -> AgentTool:
    definition = tool.tool_definition()
    merge_field = MERGEABLE_TOOL_FIELDS.get(tool.name)
    return AgentTool(
        name=definition.name,
        description=definition.description,
        parameters=definition.parameters,
        execute=lambda invocation: run_tool(tool, invocation, get_context()),
        execution_mode=tool.execution_mode,
        merge_arguments=partial(_merge_tool_arguments, field=merge_field)
        if merge_field is not None
        else None,
        complete_children=lambda invocation, children: complete_tool_children(
            tool, invocation, get_context(), children
        ),
    )
