from collections.abc import Callable

from onyx.agents.models import RunState
from onyx.agents.tools import AgentTool, ToolInvocation, ToolOutcome
from onyx.llm.models import ToolResult
from onyx.tools.interface import Tool, ToolContext
from onyx.tools.models import ToolCallException
from onyx.tracing.framework.create import function_span
from onyx.utils.logger import setup_logger

logger = setup_logger()


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
    return AgentTool(
        name=definition.name,
        description=definition.description,
        parameters=definition.parameters,
        execute=lambda invocation: run_tool(tool, invocation, get_context()),
        execution_mode=tool.execution_mode,
        complete_children=lambda invocation, children: complete_tool_children(
            tool, invocation, get_context(), children
        ),
    )
