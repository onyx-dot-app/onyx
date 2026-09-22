import asyncio
import traceback
from typing import Any

from pydantic_ai import RunContext

import onyx.tracing.framework._error_tracing as _error_tracing
from onyx.chat.models import ChatMessageSimple
from onyx.configs.constants import MessageType
from onyx.db.memory import UserMemoryContext
from onyx.server.query_and_chat.streaming_models import (
    PacketException,
    SectionEnd,
)
from onyx.tools.interface import Tool
from onyx.tools.models import (
    ChatFile,
    ChatMinimalTextMessage,
    OpenURLToolOverrideKwargs,
    PythonToolOverrideKwargs,
    SearchToolOverrideKwargs,
    ToolCallException,
    ToolCallKickoff,
    ToolExecutionException,
    ToolResponse,
    WebSearchToolOverrideKwargs,
)
from onyx.tools.tool_implementations.coding_agent.coding_agent_tool import (
    CodingAgentTool,
    CodingAgentToolOverrideKwargs,
)
from onyx.tools.tool_implementations.open_url.open_url_tool import OpenURLTool
from onyx.tools.tool_implementations.python.python_tool import PythonTool
from onyx.tools.tool_implementations.search.search_tool import SearchTool
from onyx.tools.tool_implementations.web_search.web_search_tool import WebSearchTool
from onyx.tracing.framework.create import function_span
from onyx.tracing.framework.spans import SpanError
from onyx.utils.logger import setup_logger

logger = setup_logger()

GENERIC_TOOL_ERROR_MESSAGE = "Tool failed with error: {error}"


def _safe_run_single_tool(
    tool: Tool,
    tool_call: ToolCallKickoff,
    override_kwargs: Any,
) -> ToolResponse:
    """Execute a single tool and return its response.

    Exception handling:
    - ToolCallException: Expected errors from tool execution (e.g., invalid input,
      API failures). Uses the exception's llm_facing_message for LLM consumption.
    - Other exceptions: Unexpected errors. Uses a generic error message.

    In all cases (success or failure):
    - SectionEnd packet is emitted to signal tool completion
    - tool_call is set on the response for downstream processing
    """
    tool_response: ToolResponse | None = None

    with function_span(tool.name) as span_fn:
        span_fn.span_data.input = str(tool_call.tool_args)
        try:
            tool_response = tool.run(
                placement=tool_call.placement,
                override_kwargs=override_kwargs,
                **tool_call.tool_args,
            )
            span_fn.span_data.output = tool_response.llm_facing_response
        except ToolCallException as e:
            # ToolCallException is an expected error from tool execution
            # Use llm_facing_message which is specifically designed for LLM consumption
            logger.error("Tool call error for %s: %s", tool.name, e)
            tool_response = ToolResponse(
                rich_response=None,
                llm_facing_response=GENERIC_TOOL_ERROR_MESSAGE.format(
                    error=e.llm_facing_message
                ),
            )
            _error_tracing.attach_error_to_current_span(
                SpanError(
                    message="Tool call error (expected)",
                    data={
                        "tool_name": tool.name,
                        "tool_call_id": tool_call.tool_call_id,
                        "tool_args": tool_call.tool_args,
                        "error": str(e),
                        "llm_facing_message": e.llm_facing_message,
                        "stack_trace": traceback.format_exc(),
                        "error_type": "ToolCallException",
                    },
                )
            )
        except ToolExecutionException as e:
            # Unexpected error during tool execution
            logger.error("Unexpected error running tool %s: %s", tool.name, e)
            tool_response = ToolResponse(
                rich_response=None,
                llm_facing_response=GENERIC_TOOL_ERROR_MESSAGE.format(error=str(e)),
            )
            _error_tracing.attach_error_to_current_span(
                SpanError(
                    message="Tool execution error (unexpected)",
                    data={
                        "tool_name": tool.name,
                        "tool_call_id": tool_call.tool_call_id,
                        "tool_args": tool_call.tool_args,
                        "error": str(e),
                        "stack_trace": traceback.format_exc(),
                        "error_type": type(e).__name__,
                    },
                )
            )
            if e.emit_error_packet:
                tool.emitter.report(
                    placement=tool_call.placement, obj=PacketException(exception=e)
                )
        except Exception as e:
            # Unexpected error during tool execution
            logger.error("Unexpected error running tool %s: %s", tool.name, e)
            tool_response = ToolResponse(
                rich_response=None,
                llm_facing_response=GENERIC_TOOL_ERROR_MESSAGE.format(error=str(e)),
            )
            _error_tracing.attach_error_to_current_span(
                SpanError(
                    message="Tool execution error (unexpected)",
                    data={
                        "tool_name": tool.name,
                        "tool_call_id": tool_call.tool_call_id,
                        "tool_args": tool_call.tool_args,
                        "error": str(e),
                        "stack_trace": traceback.format_exc(),
                        "error_type": type(e).__name__,
                    },
                )
            )

    # Emit SectionEnd after tool completes (success or failure)
    tool.emitter.report(placement=tool_call.placement, obj=SectionEnd())

    # Set tool_call on the response for downstream processing
    tool_response.tool_call = tool_call
    return tool_response


async def run_tool_call_async(
    context: RunContext[None],
    tool_call: ToolCallKickoff,
    tools: list[Tool],
    message_history: list[ChatMessageSimple],
    user_memory_context: UserMemoryContext | None,
    user_info: str | None,
    citation_mapping: dict[int, str],
    next_citation_num: int,
    skip_search_query_expansion: bool = False,
    chat_files: list[ChatFile] | None = None,
    url_snippet_map: dict[str, str] | None = None,
    inject_memories_in_prompt: bool = True,
) -> ToolResponse:
    """Execute one validated native call with its domain context.

    The parent Agent owns concurrency, cancellation, and tool call identities.
    """
    tool = next(tool for tool in tools if tool.name == tool_call.tool_name)
    await asyncio.to_thread(tool.emit_start, placement=tool_call.placement)
    minimal_history = [
        ChatMinimalTextMessage(message=msg.message, message_type=msg.message_type)
        for msg in message_history
    ]
    override_kwargs: Any = None
    if isinstance(tool, SearchTool):
        last_user_message = next(
            (
                msg.message
                for msg in reversed(minimal_history)
                if msg.message_type == MessageType.USER
            ),
            None,
        )
        if last_user_message is None:
            raise ValueError("No user message found in message history")
        search_memory_context = (
            user_memory_context
            if inject_memories_in_prompt
            else user_memory_context.without_memories()
            if user_memory_context
            else None
        )
        override_kwargs = SearchToolOverrideKwargs(
            starting_citation_num=next_citation_num,
            original_query=last_user_message,
            message_history=minimal_history,
            user_memory_context=search_memory_context,
            user_info=user_info,
            skip_query_expansion=skip_search_query_expansion,
        )
    elif isinstance(tool, WebSearchTool):
        override_kwargs = WebSearchToolOverrideKwargs(
            starting_citation_num=next_citation_num
        )
    elif isinstance(tool, OpenURLTool):
        override_kwargs = OpenURLToolOverrideKwargs(
            starting_citation_num=next_citation_num,
            citation_mapping={url: number for number, url in citation_mapping.items()},
            url_snippet_map=url_snippet_map or {},
        )
    elif isinstance(tool, PythonTool):
        override_kwargs = PythonToolOverrideKwargs(chat_files=chat_files or [])

    if isinstance(tool, CodingAgentTool):
        response = await _safe_run_coding_tool(context, tool, tool_call)
    else:
        response = await asyncio.to_thread(
            _safe_run_single_tool, tool, tool_call, override_kwargs
        )
    return response


async def _safe_run_coding_tool(
    context: RunContext[None], tool: CodingAgentTool, call: ToolCallKickoff
) -> ToolResponse:
    with function_span(tool.name) as span:
        span.span_data.input = str(call.tool_args)
        try:
            response = await tool.run_async(
                context,
                placement=call.placement,
                override_kwargs=CodingAgentToolOverrideKwargs(),
                **call.tool_args,
            )
            span.span_data.output = response.llm_facing_response
        except Exception as error:
            logger.exception("Coding tool failed: %s", tool.name)
            message = (
                error.llm_facing_message
                if isinstance(error, ToolCallException)
                else str(error)
            )
            response = ToolResponse(
                rich_response=None,
                llm_facing_response=GENERIC_TOOL_ERROR_MESSAGE.format(error=message),
            )
            _error_tracing.attach_error_to_current_span(
                SpanError(
                    message="Coding tool failed",
                    data={
                        "tool_name": tool.name,
                        "tool_call_id": call.tool_call_id,
                        "error": str(error),
                        "error_type": type(error).__name__,
                    },
                )
            )
            if isinstance(error, ToolExecutionException) and error.emit_error_packet:
                await asyncio.to_thread(
                    tool.emitter.report,
                    placement=call.placement,
                    obj=PacketException(exception=error),
                )
    await asyncio.to_thread(
        tool.emitter.report, placement=call.placement, obj=SectionEnd()
    )
    response.tool_call = call
    return response
