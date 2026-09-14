import traceback
from collections.abc import Callable
from typing import Any

from pydantic import JsonValue

import onyx.tracing.framework._error_tracing as _error_tracing
from onyx.agents.tools import AgentTool, ToolExecutionMode, ToolUpdate
from onyx.chat.emitter import capture_tool_packets
from onyx.configs.constants import MessageType
from onyx.context.messages import prompt_metadata
from onyx.db.memory import UserMemoryContext
from onyx.llm.cancellation import CancellationSignal, check_cancelled
from onyx.llm.models import AssistantMessage, Message, ToolResult
from onyx.server.query_and_chat.placement import Placement
from onyx.server.query_and_chat.streaming_models import (
    Packet,
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
    WebSearchToolOverrideKwargs,
)
from onyx.tools.tool_implementations.coding_agent.coding_agent_tool import (
    CodingAgentTool,
    CodingAgentToolOverrideKwargs,
)
from onyx.tools.tool_implementations.memory.memory_tool import (
    MemoryTool,
    MemoryToolOverrideKwargs,
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
) -> ToolResult:
    """Convert tool errors into responses and emit completion packets.

    Cancellation propagates without a response or completion packet.
    """
    check_cancelled()
    tool_response: ToolResult

    with function_span(tool.name) as span_fn:
        span_fn.span_data.input = str(tool_call.tool_args)
        try:
            tool_response = tool.run(
                placement=tool_call.placement,
                override_kwargs=override_kwargs,
                **tool_call.tool_args,
            )
            span_fn.span_data.output = tool_response.text
        except ToolCallException as e:
            # Expected tool errors supply a message suitable for the LLM.
            logger.error("Tool call error for %s: %s", tool.name, e)
            tool_response = ToolResult(
                is_error=True,
                content=GENERIC_TOOL_ERROR_MESSAGE.format(error=e.llm_facing_message),
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
            logger.exception("Unexpected error running tool %s", tool.name)
            tool_response = ToolResult(
                is_error=True,
                content=GENERIC_TOOL_ERROR_MESSAGE.format(error=str(e)),
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
                tool.emitter.emit(
                    Packet(
                        placement=tool_call.placement,
                        obj=PacketException(exception=e),
                    )
                )
        except Exception as e:
            logger.exception("Unexpected error running tool %s", tool.name)
            tool_response = ToolResult(
                is_error=True,
                content=GENERIC_TOOL_ERROR_MESSAGE.format(error=str(e)),
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

    check_cancelled()
    tool.emitter.emit(
        Packet(
            placement=tool_call.placement,
            obj=SectionEnd(),
        )
    )

    return tool_response


def run_tool_call(
    tool_call: ToolCallKickoff,
    tool: Tool,
    message_history: list[Message],
    user_memory_context: UserMemoryContext | None,
    user_info: str | None,
    citation_mapping: dict[int, str],
    next_citation_num: int,
    skip_search_query_expansion: bool = False,
    chat_files: list[ChatFile] | None = None,
    url_snippet_map: dict[str, str] | None = None,
    inject_memories_in_prompt: bool = True,
) -> ToolResult:
    """Bind Onyx request context to one tool. Agent owns scheduling and history."""
    check_cancelled()
    starting_citation_num = next_citation_num
    url_snippet_map = url_snippet_map or {}
    message_types = {
        "user": MessageType.USER,
        "assistant": MessageType.ASSISTANT,
        "system": MessageType.SYSTEM,
        "tool_result": MessageType.TOOL_CALL_RESPONSE,
    }
    minimal_history = [
        ChatMinimalTextMessage(
            message=msg.text,
            message_type=MessageType.USER_REMINDER
            if prompt_metadata(msg).is_reminder
            else message_types[msg.role],
        )
        for msg in message_history
    ]
    last_user_message = None
    for i in range(len(minimal_history) - 1, -1, -1):
        if minimal_history[i].message_type == MessageType.USER:
            last_user_message = minimal_history[i].message
            break

    url_to_citation: dict[str, int] = {
        url: citation_num for citation_num, url in citation_mapping.items()
    }

    # Emit the tool start packet before running the tool
    tool.emit_start(placement=tool_call.placement)

    override_kwargs: (
        SearchToolOverrideKwargs
        | WebSearchToolOverrideKwargs
        | OpenURLToolOverrideKwargs
        | PythonToolOverrideKwargs
        | MemoryToolOverrideKwargs
        | CodingAgentToolOverrideKwargs
        | None
    ) = None

    if isinstance(tool, SearchTool):
        if last_user_message is None:
            raise ValueError("No user message found in message history")

        search_memory_context = (
            user_memory_context
            if inject_memories_in_prompt
            else (
                user_memory_context.without_memories() if user_memory_context else None
            )
        )
        override_kwargs = SearchToolOverrideKwargs(
            starting_citation_num=starting_citation_num,
            original_query=last_user_message,
            message_history=minimal_history,
            user_memory_context=search_memory_context,
            user_info=user_info,
            skip_query_expansion=skip_search_query_expansion,
        )

    elif isinstance(tool, WebSearchTool):
        override_kwargs = WebSearchToolOverrideKwargs(
            starting_citation_num=starting_citation_num,
        )

    elif isinstance(tool, OpenURLTool):
        override_kwargs = OpenURLToolOverrideKwargs(
            starting_citation_num=starting_citation_num,
            citation_mapping=url_to_citation,
            url_snippet_map=url_snippet_map,
        )

    elif isinstance(tool, PythonTool):
        override_kwargs = PythonToolOverrideKwargs(
            chat_files=chat_files or [],
        )
    elif isinstance(tool, CodingAgentTool):
        override_kwargs = CodingAgentToolOverrideKwargs()
    elif isinstance(tool, MemoryTool):
        override_kwargs = MemoryToolOverrideKwargs(
            user_id=user_memory_context.user_id if user_memory_context else None,
            user_name=(
                user_memory_context.user_info.name if user_memory_context else None
            ),
            user_email=(
                user_memory_context.user_info.email if user_memory_context else None
            ),
            user_role=(
                user_memory_context.user_info.role if user_memory_context else None
            ),
            existing_memories=(
                list(user_memory_context.memories) if user_memory_context else []
            ),
            chat_history=minimal_history,
        )

    return _safe_run_single_tool(tool, tool_call, override_kwargs)


class LegacyToolContext:
    """Expose canonical call identity to legacy Onyx tools."""

    def __init__(self, messages: Callable[[], list[Message]]) -> None:
        self.messages = messages

    def message(self) -> AssistantMessage:
        return next(
            message
            for message in reversed(self.messages())
            if isinstance(message, AssistantMessage)
        )

    def index(self, call_id: str) -> int:
        return next(
            index
            for index, call in enumerate(self.message().tool_calls)
            if call.id == call_id
        )

    def kickoff(
        self, call_id: str, name: str, arguments: dict[str, JsonValue]
    ) -> ToolCallKickoff:
        # Old Onyx tools require coordinates. Presentation resolves the call ID.
        return ToolCallKickoff(
            tool_call_id=call_id,
            tool_name=name,
            tool_args=arguments,
            placement=Placement(turn_index=0),
        )


def bind_tool(
    definition: dict[str, Any],
    execute: Callable[[ToolCallKickoff], ToolResult],
    context: LegacyToolContext | None = None,
    *,
    sequential: bool = False,
) -> AgentTool:
    function = definition["function"]
    name: str = function["name"]

    def run(
        call_id: str,
        arguments: dict[str, JsonValue],
        signal: CancellationSignal,
        update: ToolUpdate,
    ) -> ToolResult:
        signal.check()
        kickoff = (
            context.kickoff(call_id, name, arguments)
            if context
            else ToolCallKickoff(
                tool_call_id=call_id,
                tool_name=name,
                tool_args=arguments,
                placement=Placement(turn_index=0),
            )
        )
        with capture_tool_packets(
            lambda packet: update(ToolResult(content="", details=packet))
        ):
            return execute(kickoff)

    return AgentTool(
        name=name,
        description=function.get("description", ""),
        parameters=function.get("parameters", {}),
        execute=run,
        execution_mode=ToolExecutionMode.SEQUENTIAL
        if sequential
        else ToolExecutionMode.PARALLEL,
    )
