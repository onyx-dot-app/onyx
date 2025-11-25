from collections import defaultdict

from onyx.chat.infra import Emitter
from onyx.chat.models import ChatMessageSimple
from onyx.configs.constants import MessageType
from onyx.context.search.models import SearchDocsResponse
from onyx.tools.models import ChatMinimalTextMessage
from onyx.tools.models import SearchToolOverrideKwargs
from onyx.tools.models import SearchToolRunContext
from onyx.tools.models import ToolCallKickoff
from onyx.tools.models import ToolResponse
from onyx.tools.models import WebSearchToolOverrideKwargs
from onyx.tools.tool import Tool
from onyx.tools.tool_implementations.search.search_tool import SearchTool
from onyx.tools.tool_implementations.web_search.web_search_tool import WebSearchTool
from onyx.utils.logger import setup_logger

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
            )
            merged_calls.append(merged_call)
        else:
            # No merging needed, add all calls as-is
            merged_calls.extend(calls)

    return merged_calls


def run_tool_calls(
    tool_calls: list[ToolCallKickoff],
    tools: list[Tool],
    turn_index: int,
    # The stuff below is needed for the different individual built-in tools
    emitter: Emitter,
    message_history: list[ChatMessageSimple],
    memories: list[str] | None,
    user_info: str | None,
    starting_citation_num: int,
) -> tuple[list[ToolResponse], int]:  # return also the new starting citation num
    # Merge tool calls for SearchTool and WebSearchTool
    merged_tool_calls = _merge_tool_calls(tool_calls)

    tools_by_name = {tool.name: tool for tool in tools}
    tool_responses: list[ToolResponse] = []

    # TODO needs to handle parallel tool calls
    for tool_call in merged_tool_calls:
        tool = tools_by_name[tool_call.tool_name]

        # Emit the tool start packet before running the tool
        tool.emit_start(turn_index=turn_index)

        run_context = SearchToolRunContext(emitter=emitter)
        override_kwargs = None

        if isinstance(tool, SearchTool):
            minimal_history = [
                ChatMinimalTextMessage(
                    message=msg.message, message_type=msg.message_type
                )
                for msg in message_history
            ]
            last_user_message = None
            for i in range(len(minimal_history) - 1, -1, -1):
                if minimal_history[i].message_type == MessageType.USER:
                    last_user_message = minimal_history[i].message
                    break

            if last_user_message is None:
                raise ValueError("No user message found in message history")

            override_kwargs = SearchToolOverrideKwargs(
                starting_citation_num=starting_citation_num,
                original_query=last_user_message,
                message_history=minimal_history,
                memories=memories,
                user_info=user_info,
            )

        elif isinstance(tool, WebSearchTool):
            override_kwargs = WebSearchToolOverrideKwargs(
                starting_citation_num=starting_citation_num,
            )

        try:
            tool_response = tool.run(
                run_context=run_context,
                turn_index=turn_index,
                override_kwargs=override_kwargs,
                **tool_call.tool_args,
            )
        except Exception as e:
            logger.error(f"Error running tool {tool.name}: {e}")
            tool_response = ToolResponse(
                rich_response=None,
                llm_facing_response=str(e),
            )

        if isinstance(tool_response.rich_response, SearchDocsResponse):
            citation_mapping = tool_response.rich_response.citation_mapping
            starting_citation_num = (
                max(citation_mapping.keys()) + 1
                if citation_mapping
                else starting_citation_num + 1
            )

        tool_responses.append(tool_response)

    return tool_responses, starting_citation_num
