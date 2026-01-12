import traceback
from collections import defaultdict
from typing import Any

import onyx.tracing.framework._error_tracing as _error_tracing
from onyx.chat.models import ChatMessageSimple
from onyx.configs.constants import MessageType
from onyx.context.search.models import SearchDocsResponse
from onyx.server.query_and_chat.streaming_models import Packet
from onyx.server.query_and_chat.streaming_models import SectionEnd
from onyx.tools.interface import Tool
from onyx.tools.models import ChatMinimalTextMessage
from onyx.tools.models import OpenURLToolOverrideKwargs
from onyx.tools.models import ParallelToolCallResponse
from onyx.tools.models import SearchToolOverrideKwargs
from onyx.tools.models import ToolCallException
from onyx.tools.models import ToolCallKickoff
from onyx.tools.models import ToolResponse
from onyx.tools.models import WebSearchToolOverrideKwargs
from onyx.tools.tool_implementations.open_url.open_url_tool import OpenURLTool
from onyx.tools.tool_implementations.search.search_tool import SearchTool
from onyx.tools.tool_implementations.web_search.web_search_tool import WebSearchTool
from onyx.tracing.framework.create import function_span
from onyx.tracing.framework.spans import SpanError
from onyx.utils.logger import setup_logger
from onyx.utils.threadpool_concurrency import run_functions_tuples_in_parallel

logger = setup_logger()

QUERIES_FIELD = "queries"
URLS_FIELD = "urls"
GENERIC_TOOL_ERROR_MESSAGE = "Tool failed with error: {error}"

# Mapping of tool name to the field that should be merged when multiple calls exist
MERGEABLE_TOOL_FIELDS: dict[str, str] = {
    SearchTool.NAME: QUERIES_FIELD,
    WebSearchTool.NAME: QUERIES_FIELD,
    OpenURLTool.NAME: URLS_FIELD,
}


def _merge_tool_calls(tool_calls: list[ToolCallKickoff]) -> list[ToolCallKickoff]:
    """Merge multiple tool calls for SearchTool, WebSearchTool, or OpenURLTool into a single call.

    For SearchTool (internal_search) and WebSearchTool (web_search), if there are
    multiple calls, their queries are merged into a single tool call.
    For OpenURLTool (open_url), multiple calls have their urls merged.
    Other tool calls are left unchanged.

    Args:
        tool_calls: List of tool calls to potentially merge

    Returns:
        List of merged tool calls
    """
    # Group tool calls by tool name
    tool_calls_by_name: dict[str, list[ToolCallKickoff]] = defaultdict(list)
    merged_calls: list[ToolCallKickoff] = []

    for tool_call in tool_calls:
        tool_calls_by_name[tool_call.tool_name].append(tool_call)

    # Process each tool name group
    for tool_name, calls in tool_calls_by_name.items():
        if tool_name in MERGEABLE_TOOL_FIELDS and len(calls) > 1:
            merge_field = MERGEABLE_TOOL_FIELDS[tool_name]

            # Merge field values from all calls
            all_values: list[str] = []
            for call in calls:
                values = call.tool_args.get(merge_field, [])
                if isinstance(values, list):
                    all_values.extend(values)
                elif values:
                    # Handle case where it might be a single string
                    all_values.append(str(values))

            # Create a merged tool call using the first call's ID and merging the field
            merged_args = calls[0].tool_args.copy()
            merged_args[merge_field] = all_values

            merged_call = ToolCallKickoff(
                tool_call_id=calls[0].tool_call_id,  # Use first call's ID
                tool_name=tool_name,
                tool_args=merged_args,
                # Use first call's placement since merged calls become a single call
                placement=calls[0].placement,
            )
            merged_calls.append(merged_call)
        else:
            # No merging needed, add all calls as-is
            merged_calls.extend(calls)

    return merged_calls


def _safe_run_single_tool(
    tool: Tool,
    tool_call: ToolCallKickoff,
    override_kwargs: Any,
) -> ToolResponse:
    """Execute a single tool and return its response.

    This function is designed to be run in parallel via run_functions_tuples_in_parallel.

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
            logger.error(f"Tool call error for {tool.name}: {e}")
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
        except Exception as e:
            # Unexpected error during tool execution
            logger.error(f"Unexpected error running tool {tool.name}: {e}")
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
    tool.emitter.emit(
        Packet(
            placement=tool_call.placement,
            obj=SectionEnd(),
        )
    )

    # Set tool_call on the response for downstream processing
    tool_response.tool_call = tool_call
    return tool_response


def run_tool_calls(
    tool_calls: list[ToolCallKickoff],
    tools: list[Tool],
    # The stuff below is needed for the different individual built-in tools
    message_history: list[ChatMessageSimple],
    memories: list[str] | None,
    user_info: str | None,
    citation_mapping: dict[int, str],
    next_citation_num: int,
    # Max number of tools to run concurrently (and overall) in this batch.
    # If set, tool calls beyond this limit are dropped.
    max_concurrent_tools: int | None = None,
    # Skip query expansion for repeat search tool calls
    skip_search_query_expansion: bool = False,
) -> ParallelToolCallResponse:
    """Run (optionally merged) tool calls in parallel and update citation mappings.

    Before execution, tool calls for `SearchTool`, `WebSearchTool`, and `OpenURLTool`
    are merged so repeated calls are collapsed into a single call per tool:
    - `SearchTool` / `WebSearchTool`: merge the `queries` list
    - `OpenURLTool`: merge the `urls` list

    Tools are executed in parallel (threadpool). For tools that generate citations,
    each tool call is assigned a **distinct** `starting_citation_num` range to avoid
    citation number collisions when running concurrently (the range is advanced by
    100 per tool call).

    The provided `citation_mapping` may be mutated in-place: any new
    `SearchDocsResponse.citation_mapping` entries are merged into it.

    Args:
        tool_calls: List of tool calls to execute.
        tools: List of available tool instances.
        message_history: Chat message history (used to find the most recent user query
            for `SearchTool` override kwargs).
        memories: User memories, if available (passed through to `SearchTool`).
        user_info: User information string, if available (passed through to `SearchTool`).
        citation_mapping: Current citation number to URL mapping. May be updated with
            new citations produced by search tools.
        next_citation_num: The next citation number to allocate from.
        max_concurrent_tools: Max number of tools to run in this batch. If set, any
            tool calls after this limit are dropped (not queued).
        skip_search_query_expansion: Whether to skip query expansion for `SearchTool`
            (intended for repeated search calls within the same chat turn).

    Returns:
        A `ParallelToolCallResponse` containing:
        - `tool_responses`: `ToolResponse` objects for successfully dispatched tool calls
          (each has `tool_call` set). If a tool execution fails at the threadpool layer,
          its entry will be omitted.
        - `updated_citation_mapping`: The updated citation mapping dictionary.
    """
    # Merge tool calls for SearchTool, WebSearchTool, and OpenURLTool
    merged_tool_calls = _merge_tool_calls(tool_calls)

    if not merged_tool_calls:
        return ParallelToolCallResponse(
            tool_responses=[],
            updated_citation_mapping=citation_mapping,
        )

    tools_by_name = {tool.name: tool for tool in tools}

    # Drop unknown tools (and don't let them count against the cap)
    filtered_tool_calls: list[ToolCallKickoff] = []
    for tool_call in merged_tool_calls:
        if tool_call.tool_name not in tools_by_name:
            logger.warning(f"Tool {tool_call.tool_name} not found in tools list")
            continue
        filtered_tool_calls.append(tool_call)

    # Apply safety cap (drop tool calls beyond the cap)
    if max_concurrent_tools is not None:
        if max_concurrent_tools <= 0:
            return ParallelToolCallResponse(
                tool_responses=[],
                updated_citation_mapping=citation_mapping,
            )
        filtered_tool_calls = filtered_tool_calls[:max_concurrent_tools]

    # Get starting citation number from citation processor to avoid conflicts with project files
    starting_citation_num = next_citation_num

    # Prepare minimal history for SearchTool (computed once, shared by all)
    minimal_history = [
        ChatMinimalTextMessage(message=msg.message, message_type=msg.message_type)
        for msg in message_history
    ]
    last_user_message = None
    for i in range(len(minimal_history) - 1, -1, -1):
        if minimal_history[i].message_type == MessageType.USER:
            last_user_message = minimal_history[i].message
            break

    # Convert citation_mapping for OpenURLTool (computed once, shared by all)
    url_to_citation: dict[str, int] = {
        url: citation_num for citation_num, url in citation_mapping.items()
    }

    # Prepare all tool calls with their override_kwargs
    # Each tool gets a unique starting citation number to avoid conflicts when running in parallel
    tool_run_params: list[tuple[Tool, ToolCallKickoff, Any]] = []

    for tool_call in filtered_tool_calls:
        tool = tools_by_name[tool_call.tool_name]

        # Emit the tool start packet before running the tool
        tool.emit_start(placement=tool_call.placement)

        override_kwargs: (
            SearchToolOverrideKwargs
            | WebSearchToolOverrideKwargs
            | OpenURLToolOverrideKwargs
            | None
        ) = None

        if isinstance(tool, SearchTool):
            if last_user_message is None:
                raise ValueError("No user message found in message history")

            override_kwargs = SearchToolOverrideKwargs(
                starting_citation_num=starting_citation_num,
                original_query=last_user_message,
                message_history=minimal_history,
                memories=memories,
                user_info=user_info,
                skip_query_expansion=skip_search_query_expansion,
            )
            # Increment citation number for next search tool to avoid conflicts
            # Estimate: reserve 100 citation slots per search tool
            starting_citation_num += 100

        elif isinstance(tool, WebSearchTool):
            override_kwargs = WebSearchToolOverrideKwargs(
                starting_citation_num=starting_citation_num,
            )
            # Increment citation number for next search tool to avoid conflicts
            starting_citation_num += 100

        elif isinstance(tool, OpenURLTool):
            override_kwargs = OpenURLToolOverrideKwargs(
                starting_citation_num=starting_citation_num,
                citation_mapping=url_to_citation,
            )
            starting_citation_num += 100

        tool_run_params.append((tool, tool_call, override_kwargs))

    # Run all tools in parallel
    functions_with_args = [
        (_safe_run_single_tool, (tool, tool_call, override_kwargs))
        for tool, tool_call, override_kwargs in tool_run_params
    ]

    tool_run_results: list[ToolResponse | None] = run_functions_tuples_in_parallel(
        functions_with_args,
        allow_failures=True,  # Continue even if some tools fail
        max_workers=max_concurrent_tools,
    )

    # Process results and update citation_mapping
    for result in tool_run_results:
        if result is None:
            continue

        if result and isinstance(result.rich_response, SearchDocsResponse):
            new_citations = result.rich_response.citation_mapping
            if new_citations:
                # Merge new citations into the existing mapping
                citation_mapping.update(new_citations)

    tool_responses = [result for result in tool_run_results if result is not None]
    return ParallelToolCallResponse(
        tool_responses=tool_responses,
        updated_citation_mapping=citation_mapping,
    )
