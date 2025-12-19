import traceback
from collections import defaultdict
from typing import Any

import onyx.tracing.framework._error_tracing as _error_tracing
from onyx.chat.citation_processor import DynamicCitationProcessor
from onyx.chat.models import ChatMessageSimple
from onyx.configs.constants import MessageType
from onyx.context.search.models import SearchDocsResponse
from onyx.server.query_and_chat.streaming_models import Packet
from onyx.server.query_and_chat.streaming_models import Placement
from onyx.server.query_and_chat.streaming_models import SectionEnd
from onyx.tools.models import ChatMinimalTextMessage
from onyx.tools.models import OpenURLToolOverrideKwargs
from onyx.tools.models import SearchToolOverrideKwargs
from onyx.tools.models import ToolCallKickoff
from onyx.tools.models import ToolResponse
from onyx.tools.models import WebSearchToolOverrideKwargs
from onyx.tools.tool import Tool
from onyx.tools.tool_implementations.open_url.open_url_tool import OpenURLTool
from onyx.tools.tool_implementations.search.search_tool import SearchTool
from onyx.tools.tool_implementations.web_search.web_search_tool import WebSearchTool
from onyx.tracing.framework.create import function_span
from onyx.tracing.framework.spans import SpanError
from onyx.utils.logger import setup_logger
from onyx.utils.threadpool_concurrency import run_functions_tuples_in_parallel

logger = setup_logger()

QUERIES_FIELD = "queries"


def _merge_tool_calls(tool_calls: list[ToolCallKickoff]) -> list[ToolCallKickoff]:
    """Merge multiple tool calls for SearchTool or WebSearchTool into a single call.

    For SearchTool (internal_search) and WebSearchTool (web_search), if there are
    multiple calls, their queries are merged into a single tool call.
    Other tool calls are left unchanged.

    Args:
        tool_calls: List of tool calls to potentially merge

    Returns:
        List of merged tool calls
    """
    # Tool names that support query merging
    MERGEABLE_TOOLS = {SearchTool.NAME, WebSearchTool.NAME}

    # Group tool calls by tool name
    tool_calls_by_name: dict[str, list[ToolCallKickoff]] = defaultdict(list)
    merged_calls: list[ToolCallKickoff] = []

    for tool_call in tool_calls:
        tool_calls_by_name[tool_call.tool_name].append(tool_call)

    # Process each tool name group
    for tool_name, calls in tool_calls_by_name.items():
        if tool_name in MERGEABLE_TOOLS and len(calls) > 1:
            # Merge queries from all calls
            all_queries: list[str] = []
            for call in calls:
                queries = call.tool_args.get(QUERIES_FIELD, [])
                if isinstance(queries, list):
                    all_queries.extend(queries)
                elif queries:
                    # Handle case where it might be a single string
                    all_queries.append(str(queries))

            # Create a merged tool call using the first call's ID and merging queries
            merged_args = calls[0].tool_args.copy()
            merged_args[QUERIES_FIELD] = all_queries

            merged_call = ToolCallKickoff(
                tool_call_id=calls[0].tool_call_id,  # Use first call's ID
                tool_name=tool_name,
                tool_args=merged_args,
                turn_index=calls[0].turn_index,
                # Use first call's tab_index since merged calls become a single call
                tab_index=calls[0].tab_index,
            )
            merged_calls.append(merged_call)
        else:
            # No merging needed, add all calls as-is
            merged_calls.extend(calls)

    return merged_calls


def _run_single_tool(
    tool: Tool,
    tool_call: ToolCallKickoff,
    override_kwargs: Any,
) -> ToolResponse:
    """Execute a single tool and return its response.

    This function is designed to be run in parallel via run_functions_tuples_in_parallel.
    """
    turn_index = tool_call.turn_index
    tab_index = tool_call.tab_index

    with function_span(tool.name) as span_fn:
        span_fn.span_data.input = str(tool_call.tool_args)
        try:
            tool_response = tool.run(
                turn_index=turn_index,
                override_kwargs=override_kwargs,
                tab_index=tab_index,
                **tool_call.tool_args,
            )
            span_fn.span_data.output = tool_response.llm_facing_response
        except Exception as e:
            logger.error(f"Error running tool {tool.name}: {e}")
            tool_response = ToolResponse(
                rich_response=None,
                llm_facing_response=str(e),
            )
            _error_tracing.attach_error_to_current_span(
                SpanError(
                    message="Error running tool",
                    data={
                        "tool_name": tool.name,
                        "error": str(e),
                        "stack_trace": traceback.format_exc(),
                    },
                )
            )

    # Emit SectionEnd after tool completes (success or failure)
    tool.emitter.emit(
        Packet(
            placement=Placement(turn_index=turn_index, tab_index=tab_index),
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
    citation_processor: DynamicCitationProcessor,
    # Skip query expansion for repeat search tool calls
    skip_search_query_expansion: bool = False,
) -> tuple[list[ToolResponse], dict[int, str]]:
    """Run multiple tool calls in parallel and update citation mappings.

    Merges tool calls for SearchTool and WebSearchTool before execution.
    All tools are executed in parallel, and citation mappings are updated
    from search tool responses.

    Args:
        tool_calls: List of tool calls to execute
        tools: List of available tools
        message_history: Chat message history for context
        memories: User memories, if available
        user_info: User information string, if available
        citation_mapping: Current citation number to URL mapping
        citation_processor: Processor for managing citations
        skip_search_query_expansion: Whether to skip query expansion for search tools

    Returns:
        A tuple containing:
            - List of ToolResponse objects (each with tool_call set)
            - Updated citation mapping dictionary
    """
    # Merge tool calls for SearchTool and WebSearchTool
    merged_tool_calls = _merge_tool_calls(tool_calls)

    if not merged_tool_calls:
        return [], citation_mapping

    tools_by_name = {tool.name: tool for tool in tools}

    # Get starting citation number from citation processor to avoid conflicts with project files
    starting_citation_num = citation_processor.get_next_citation_number()

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

    for tool_call in merged_tool_calls:
        if tool_call.tool_name not in tools_by_name:
            logger.warning(f"Tool {tool_call.tool_name} not found in tools list")
            continue

        tool = tools_by_name[tool_call.tool_name]

        # Emit the tool start packet before running the tool
        tool.emit_start(turn_index=tool_call.turn_index, tab_index=tool_call.tab_index)

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
        (_run_single_tool, (tool, tool_call, override_kwargs))
        for tool, tool_call, override_kwargs in tool_run_params
    ]

    tool_responses: list[ToolResponse] = run_functions_tuples_in_parallel(
        functions_with_args,
        allow_failures=True,  # Continue even if some tools fail
    )

    # Process results and update citation_mapping
    for tool_response in tool_responses:
        if tool_response and isinstance(
            tool_response.rich_response, SearchDocsResponse
        ):
            new_citations = tool_response.rich_response.citation_mapping
            if new_citations:
                # Merge new citations into the existing mapping
                citation_mapping.update(new_citations)

    return tool_responses, citation_mapping
