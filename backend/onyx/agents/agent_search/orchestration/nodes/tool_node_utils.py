from typing import Any

from langchain_core.messages import AIMessage, ToolMessage
from langchain_core.messages.tool import ToolCall
from langgraph.types import StreamWriter

from onyx.agents.agent_search.models import GraphConfig
from onyx.agents.agent_search.shared_graph_utils.utils import write_custom_event
from onyx.chat.models import AnswerPacket
from onyx.chat.prompt_builder.answer_prompt_builder import AnswerPromptBuilder
from onyx.configs.constants import MessageType
from onyx.db.chat import create_new_chat_message, get_chat_messages_by_session
from onyx.db.models import ChatMessage
from onyx.natural_language_processing.utils import get_tokenizer
from onyx.tools.tool_runner import ToolRunner
from onyx.utils.logger import setup_logger

logger = setup_logger()


def emit_packet(packet: AnswerPacket, writer: StreamWriter) -> None:
    """Emit an answer packet to the stream writer."""
    write_custom_event("basic_response", packet, writer)


def save_tool_call_message(
    tool_name: str,
    tool_call_request: ToolCall,
    agent_config: GraphConfig,
    tool_type: str = "",
) -> ChatMessage:
    """Save the tool call message to the database."""
    persistence = agent_config.persistence
    llm = agent_config.tooling.primary_llm

    # Get the current conversation messages
    chat_messages = get_chat_messages_by_session(
        chat_session_id=persistence.chat_session_id,
        user_id=None,
        db_session=persistence.db_session,
        skip_permission_check=True,
    )

    # Get the latest message to use as parent
    final_msg = chat_messages[-1]

    # Calculate token count for the tool call message
    tokenizer = get_tokenizer(
        model_name=llm.config.model_name, provider_type=llm.config.model_provider
    )

    tool_call_content = (
        f"Called {tool_type + ' ' if tool_type else ''}tool: {tool_name}"
    )
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


def execute_tool(
    selected_tool: Any, tool_call_request: ToolCall, writer: StreamWriter
) -> tuple[ToolRunner, list]:
    """Execute the selected tool and collect responses."""
    tool_runner = ToolRunner(
        selected_tool, tool_call_request["args"], override_kwargs=None
    )

    # Emit tool kickoff
    tool_kickoff = tool_runner.kickoff()
    emit_packet(tool_kickoff, writer)

    # Collect tool responses
    tool_responses = []
    for response in tool_runner.tool_responses():
        tool_responses.append(response)
        emit_packet(response, writer)

    # Get final result
    tool_final_result = tool_runner.tool_final_result()
    emit_packet(tool_final_result, writer)

    return tool_runner, tool_responses


def save_tool_result_message(
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
        parent_message=tool_call_db_message,
        message=tool_result_content,
        prompt_id=None,
        token_count=token_count,
        message_type=MessageType.USER,
        db_session=persistence.db_session,
        commit=True,
    )

    return tool_result_db_message


def update_prompt_builder_history(
    prompt_builder: AnswerPromptBuilder,
    tool_call_request: ToolCall,
    tool_runner: ToolRunner,
) -> None:
    """Add tool call and result messages to prompt builder history."""
    try:
        # Create AIMessage with tool call
        tool_call_message = AIMessage(
            content="",
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

        # Create ToolMessage
        tool_result_message = ToolMessage(
            content=tool_result_content, tool_call_id=tool_call_request["id"]
        )

        # Add both messages using the proper append_message method
        prompt_builder.append_message(tool_call_message)
        prompt_builder.append_message(tool_result_message)

    except Exception as e:
        logger.error(f"Error updating prompt builder history: {e}")
        logger.warning("Continuing without updating prompt builder history")
