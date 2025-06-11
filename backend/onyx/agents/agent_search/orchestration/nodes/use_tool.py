from typing import Any, cast

from langchain_core.messages import AIMessage, ToolMessage
from langchain_core.messages.tool import ToolCall
from langchain_core.runnables.config import RunnableConfig
from langgraph.types import StreamWriter

from onyx.agents.agent_search.basic.utils import process_llm_stream
from onyx.agents.agent_search.models import GraphConfig
from onyx.agents.agent_search.shared_graph_utils.utils import write_custom_event
from onyx.chat.models import AnswerPacket, LlmDoc
from onyx.chat.prompt_builder.answer_prompt_builder import AnswerPromptBuilder
from onyx.chat.tool_handling.tool_response_handler import get_tool_by_name
from onyx.configs.constants import MessageType
from onyx.context.search.utils import dedupe_documents
from onyx.db.chat import create_new_chat_message, get_chat_messages_by_session
from onyx.db.models import ChatMessage
from onyx.natural_language_processing.utils import get_tokenizer
from onyx.tools.tool_implementations.search.search_tool import (
    SEARCH_RESPONSE_SUMMARY_ID,
    SearchResponseSummary,
)
from onyx.tools.tool_implementations.search.search_utils import section_to_llm_doc
from onyx.tools.tool_implementations.search_like_tool_utils import (
    FINAL_CONTEXT_DOCUMENTS_ID,
)
from onyx.tools.tool_runner import ToolRunner
from onyx.utils.logger import setup_logger

logger = setup_logger()


def use_tool(
    state: Any, config: RunnableConfig, writer: StreamWriter = lambda _: None
) -> dict[str, Any]:
    """
    Tool execution workflow that:
    1. Asks LLM to choose a tool
    2. Calls the selected tool
    3. Saves tool messages to database and prompt builder
    Does NOT generate final response - that's handled by the respond node.
    """
    agent_config = cast(GraphConfig, config.get("metadata", {}).get("config"))

    llm = agent_config.tooling.primary_llm
    tools = agent_config.tooling.tools or []
    prompt_builder = agent_config.inputs.prompt_builder
    using_tool_calling_llm = agent_config.tooling.using_tool_calling_llm
    force_use_tool = agent_config.tooling.force_use_tool
    structured_response_format = agent_config.inputs.structured_response_format

    # Get persistence info for database operations
    persistence = agent_config.persistence
    if not persistence:
        raise ValueError("GraphPersistence is required for tool use workflow")

    built_prompt = (
        prompt_builder.build()
        if isinstance(prompt_builder, AnswerPromptBuilder)
        else prompt_builder.built_prompt
    )

    # Call LLM to choose tool
    stream = llm.stream(
        prompt=built_prompt,
        tools=(
            [tool.tool_definition() for tool in tools] or None
            if using_tool_calling_llm and tools
            else None
        ),
        tool_choice=(
            "required"
            if tools and force_use_tool.force_use and using_tool_calling_llm
            else None
        ),
        structured_response_format=structured_response_format,
    )

    tool_message = process_llm_stream(
        stream, should_stream_answer=False, writer=writer, return_text_content=False
    )

    # If no tool calls, return early - respond node will handle the response
    if not tool_message.tool_calls:
        return {"tool_used": False}

    # Get the first tool call
    tool_call_request = tool_message.tool_calls[0]
    selected_tool = get_tool_by_name(tools, tool_call_request["name"])

    if not selected_tool:
        logger.error(f"Unknown tool requested: {tool_call_request['name']}")
        return {
            "tool_used": False,
            "error": f"Unknown tool: {tool_call_request['name']}",
        }

    try:
        # Save tool call to database
        tool_call_db_message = _save_tool_call_message(
            selected_tool.name, tool_call_request, agent_config
        )

        # Execute tool
        tool_runner, tool_responses = _execute_tool(
            selected_tool, tool_call_request, writer
        )

        # Save tool result to database
        _save_tool_result_message(tool_runner, tool_call_db_message, agent_config)

        # Update prompt builder history
        _update_prompt_builder_history(prompt_builder, tool_call_request, tool_runner)

        # Extract search results for citations (for respond node to use)
        final_search_results, initial_search_results = _extract_search_results(
            tool_responses
        )

        return {
            "tool_used": True,
            "tool_name": selected_tool.name,
            "final_search_results": final_search_results,
            "initial_search_results": initial_search_results,
        }

    except Exception as e:
        logger.error(f"Error in tool execution workflow: {e}")
        return {"tool_used": False, "error": str(e)}


def _emit_packet(packet: AnswerPacket, writer: StreamWriter) -> None:
    write_custom_event("basic_response", packet, writer)


def _save_tool_call_message(
    tool_name: str, tool_call_request: ToolCall, agent_config: GraphConfig
) -> ChatMessage:
    """Save the tool call message to the database."""
    persistence = agent_config.persistence
    llm = agent_config.tooling.primary_llm

    # Get the current conversation messages
    chat_messages = get_chat_messages_by_session(
        chat_session_id=persistence.chat_session_id,
        user_id=None,  # We're in an authorized context
        db_session=persistence.db_session,
        skip_permission_check=True,
    )

    # Get the latest message to use as parent
    final_msg = chat_messages[-1]

    # Calculate token count for the tool call message
    tokenizer = get_tokenizer(
        model_name=llm.config.model_name, provider_type=llm.config.model_provider
    )

    tool_call_content = f"Called tool: {tool_name}"
    token_count = len(tokenizer.encode(tool_call_content))

    # Create the tool call message in database
    tool_call_db_message = create_new_chat_message(
        chat_session_id=persistence.chat_session_id,
        parent_message=final_msg,
        message=tool_call_content,
        prompt_id=None,
        token_count=token_count,
        message_type=MessageType.ASSISTANT,
        db_session=persistence.db_session,
        commit=True,
    )

    return tool_call_db_message


def _execute_tool(
    selected_tool, tool_call_request: ToolCall, writer: StreamWriter
) -> tuple[ToolRunner, list]:
    """Execute the selected tool and collect responses."""
    tool_runner = ToolRunner(
        selected_tool,
        tool_call_request["args"],
        override_kwargs=None,  # Simplified - no override kwargs
    )

    # Emit tool kickoff
    tool_kickoff = tool_runner.kickoff()
    _emit_packet(tool_kickoff, writer)

    # Collect tool responses
    tool_responses = []
    for response in tool_runner.tool_responses():
        tool_responses.append(response)
        _emit_packet(response, writer)

    # Get final result
    tool_final_result = tool_runner.tool_final_result()
    _emit_packet(tool_final_result, writer)

    return tool_runner, tool_responses


def _save_tool_result_message(
    tool_runner: ToolRunner,
    tool_call_db_message: ChatMessage,
    agent_config: GraphConfig,
) -> ChatMessage:
    """Save the tool result message to the database."""
    persistence = agent_config.persistence
    llm = agent_config.tooling.primary_llm

    # Get tool result content and ensure it's a string
    tool_result_content = tool_runner.tool_message_content()
    if isinstance(tool_result_content, list):
        # Convert list to string representation
        tool_result_content = str(tool_result_content)
    elif not isinstance(tool_result_content, str):
        tool_result_content = str(tool_result_content)

    # Calculate token count for the tool result
    tokenizer = get_tokenizer(
        model_name=llm.config.model_name, provider_type=llm.config.model_provider
    )
    token_count = len(tokenizer.encode(tool_result_content))

    # Create the tool result message in database
    tool_result_db_message = create_new_chat_message(
        chat_session_id=persistence.chat_session_id,
        parent_message=tool_call_db_message,  # Tool result is a response to the tool call
        message=tool_result_content,
        prompt_id=None,
        token_count=token_count,
        message_type=MessageType.USER,  # Tool results are user messages
        db_session=persistence.db_session,
        commit=True,
    )

    return tool_result_db_message


def _update_prompt_builder_history(
    prompt_builder: AnswerPromptBuilder,
    tool_call_request: ToolCall,
    tool_runner: ToolRunner,
) -> None:
    """Add tool call and result messages to prompt builder history directly as BaseMessage objects."""
    try:
        # Create AIMessage with tool call directly
        tool_call_message = AIMessage(
            content="",  # Empty content for tool call messages
            tool_calls=[
                {
                    "name": tool_call_request["name"],
                    "args": tool_call_request["args"],
                    "id": tool_call_request["id"],
                }
            ],
        )

        # Get tool result content and ensure it's a string
        tool_result_content = tool_runner.tool_message_content()
        if isinstance(tool_result_content, list):
            tool_result_content = str(tool_result_content)
        elif not isinstance(tool_result_content, str):
            tool_result_content = str(tool_result_content)

        # Create ToolMessage directly
        tool_result_message = ToolMessage(
            content=tool_result_content, tool_call_id=tool_call_request["id"]
        )

        # Add both messages using the proper append_message method
        prompt_builder.append_message(tool_call_message)
        prompt_builder.append_message(tool_result_message)

    except Exception as e:
        logger.error(f"Error updating prompt builder history: {e}")
        # Don't raise - we can continue without updating prompt history
        # The database persistence still works
        logger.warning("Continuing without updating prompt builder history")


def _extract_search_results(tool_responses: list) -> tuple[list[LlmDoc], list[LlmDoc]]:
    """Extract search results from tool responses for citation handling."""
    final_search_results = []
    initial_search_results = []

    for yield_item in tool_responses:
        if yield_item.id == FINAL_CONTEXT_DOCUMENTS_ID:
            final_search_results = cast(list[LlmDoc], yield_item.response)
        elif yield_item.id == SEARCH_RESPONSE_SUMMARY_ID:
            search_response_summary = cast(SearchResponseSummary, yield_item.response)
            try:
                deduped_results = dedupe_documents(search_response_summary.top_sections)
                if deduped_results and len(deduped_results) > 0 and deduped_results[0]:
                    initial_search_results = [
                        section_to_llm_doc(section) for section in deduped_results[0]
                    ]
                else:
                    initial_search_results = []
            except (IndexError, TypeError) as e:
                logger.error(f"Error extracting search results: {e}")
                initial_search_results = []

    return final_search_results, initial_search_results
