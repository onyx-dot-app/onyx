# TODO: Figure out a way to persist information is robust to cancellation,
# modular so easily testable in unit tests and evals [likely injecting some higher
# level session manager and span sink], potentially has some robustness off the critical path,
# and promotes clean separation of concerns.
import logging
import re
from uuid import UUID

from sqlalchemy.orm import Session

from onyx.agents.agent_sdk.message_types import AgentSDKMessage
from onyx.chat.turn.models import FetchedDocumentCacheEntry
from onyx.configs.constants import DocumentSource
from onyx.context.search.models import CitationDocInfo
from onyx.db.chat import create_search_doc_from_inference_section
from onyx.db.chat import update_db_session_with_messages
from onyx.db.models import ChatMessage
from onyx.db.models import ChatMessage__SearchDoc
from onyx.natural_language_processing.utils import get_tokenizer
from onyx.server.query_and_chat.streaming_models import MessageDelta
from onyx.server.query_and_chat.streaming_models import MessageStart
from onyx.server.query_and_chat.streaming_models import Packet
from onyx.tools.models import ToolCallInfo

logger = logging.getLogger(__name__)


def save_chat_turn(
    message_text: str,
    reasoning_tokens: str | None,
    tool_calls: list[ToolCallInfo],
    citation_docs_info: list[CitationDocInfo],
    db_session: Session,
    assistant_message: ChatMessage,
) -> None:
    raise NotImplementedError("Not implemented")


def save_turn(
    db_session: Session,
    message_id: int,
    chat_session_id: UUID,
    final_answer: str,
    fetched_documents_cache: dict[str, FetchedDocumentCacheEntry],
    agent_turn_messages: list[AgentSDKMessage],
    model_name: str,
    model_provider: str,
) -> None:
    """
    Save the complete chat turn including:
    - Update assistant ChatMessage with final answer
    - Create ToolCall entries for all tool invocations
    - Link SearchDocs to the assistant message
    """
    # 1. Create search docs from inference sections and build mapping
    citation_number_to_search_doc_id: dict[int, int] = {}
    search_docs = []
    for cache_entry in fetched_documents_cache.values():
        search_doc = create_search_doc_from_inference_section(
            inference_section=cache_entry.inference_section,
            is_internet=cache_entry.inference_section.center_chunk.source_type
            == DocumentSource.WEB,
            db_session=db_session,
            commit=False,
        )
        search_docs.append(search_doc)
        citation_number_to_search_doc_id[cache_entry.document_citation_number] = (
            search_doc.id
        )

    # 2. Link search docs to message
    _insert_chat_message_search_doc_pair(
        message_id, [doc.id for doc in search_docs], db_session
    )

    # 3. Calculate token count for final answer
    llm_tokenizer = get_tokenizer(
        model_name=model_name,
        provider_type=model_provider,
    )
    num_tokens = len(llm_tokenizer.encode(final_answer or ""))

    # 4. Update the assistant ChatMessage with final answer
    update_db_session_with_messages(
        db_session=db_session,
        chat_message_id=message_id,
        chat_session_id=chat_session_id,
        message=final_answer,
        token_count=num_tokens,
        update_parent_message=True,
        commit=False,
    )

    # 5. Parse agent_turn_messages to create ToolCall entries
    _save_tool_calls_from_messages(
        db_session=db_session,
        chat_session_id=chat_session_id,
        parent_chat_message_id=message_id,
        agent_turn_messages=agent_turn_messages,
        model_name=model_name,
        model_provider=model_provider,
    )

    db_session.commit()


def _insert_chat_message_search_doc_pair(
    message_id: int, search_doc_ids: list[int], db_session: Session
) -> None:
    """
    Insert a pair of message_id and search_doc_id into the chat_message__search_doc table.

    Args:
        message_id: The ID of the chat message
        search_doc_id: The ID of the search document
        db_session: The database session
    """
    for search_doc_id in search_doc_ids:
        chat_message_search_doc = ChatMessage__SearchDoc(
            chat_message_id=message_id, search_doc_id=search_doc_id
        )
        db_session.add(chat_message_search_doc)


def _extract_citation_numbers(text: str) -> list[int]:
    """
    Extract all citation numbers from text in the format [[<number>]] or [[<number_1>, <number_2>, ...]].
    Returns a list of all unique citation numbers found.
    """
    # Pattern to match [[number]] or [[number1, number2, ...]]
    pattern = r"\[\[(\d+(?:,\s*\d+)*)\]\]"
    matches = re.findall(pattern, text)

    cited_numbers = []
    for match in matches:
        # Split by comma and extract all numbers
        numbers = [int(num.strip()) for num in match.split(",")]
        cited_numbers.extend(numbers)

    return list(set(cited_numbers))  # Return unique numbers


def _save_tool_calls_from_messages(
    db_session: Session,
    chat_session_id: UUID,
    parent_chat_message_id: int,
    agent_turn_messages: list[AgentSDKMessage],
    model_name: str,
    model_provider: str,
) -> None:
    """
    Parse agent_turn_messages to extract tool calls and responses,
    then create ToolCall DB entries.

    Matches FunctionCallMessage with FunctionCallOutputMessage by call_id
    and creates a ToolCall database entry for each matched pair.

    Args:
        db_session: Database session for persistence
        chat_session_id: ID of the chat session
        parent_chat_message_id: ID of the parent chat message (assistant message)
        agent_turn_messages: List of agent SDK messages containing tool calls
        model_name: Name of the LLM model used
        model_provider: Provider of the LLM model

    Note:
        - All tool calls created here are top-level (depth=0, parent_tool_call_id=None)
        - Nested tool calls are not yet supported
        - Reasoning tokens are not yet implemented
    """
    # TODO delete this when new implementation is out
    # Build a mapping of call_id -> (call_msg, output_msg)
    # tool_call_map: dict[str, dict] = {}

    # for msg in agent_turn_messages:
    #     msg_type = msg.get("type")

    #     if msg_type == "function_call":
    #         call_id = msg["call_id"]
    #         if call_id not in tool_call_map:
    #             tool_call_map[call_id] = {}
    #         tool_call_map[call_id]["call"] = msg

    #     elif msg_type == "function_call_output":
    #         call_id = msg["call_id"]
    #         if call_id not in tool_call_map:
    #             tool_call_map[call_id] = {}
    #         tool_call_map[call_id]["output"] = msg

    # # Create ToolCall entries
    # llm_tokenizer = get_tokenizer(
    #     model_name=model_name,
    #     provider_type=model_provider,
    # )

    # # TODO: Fix turn_number logic to properly distinguish parallel vs sequential tool calls.
    # # Currently using sequential numbering (0, 1, 2...) but this is incorrect:
    # # - Parallel tool calls should have the SAME turn_number
    # # - Sequential tool calls should have DIFFERENT turn_numbers
    # # For now, treating all as sequential until we have better metadata to distinguish them.
    # turn_number = 0

    # for call_id, call_data in tool_call_map.items():
    #     # Validate we have both call and output
    #     if "call" not in call_data:
    #         logger.warning(
    #             f"Tool call {call_id} missing function_call message - skipping"
    #         )
    #         continue

    #     if "output" not in call_data:
    #         logger.warning(
    #             f"Tool call {call_id} missing function_call_output message - skipping"
    #         )
    #         continue

    #     call_msg = call_data["call"]
    #     output_msg = call_data["output"]

    #     # Parse arguments
    #     try:
    #         tool_arguments = json.loads(call_msg["arguments"])
    #     except json.JSONDecodeError as e:
    #         logger.warning(
    #             f"Failed to parse tool call arguments for {call_id}: {e}. "
    #             f"Storing as raw string."
    #         )
    #         tool_arguments = {"raw": call_msg["arguments"]}

    #     # Parse response
    #     try:
    #         tool_response = json.loads(output_msg["output"])
    #     except json.JSONDecodeError as e:
    #         logger.warning(
    #             f"Failed to parse tool call output for {call_id}: {e}. "
    #             f"Storing as raw string."
    #         )
    #         tool_response = {"raw": output_msg["output"]}

    #     # Look up tool_id by name
    #     tool_name = call_msg["name"]
    #     tool = db_session.query(Tool).filter(Tool.name == tool_name).first()

    #     if tool is None:
    #         logger.warning(
    #             f"Tool '{tool_name}' not found in database for call_id {call_id}. "
    #             f"Using tool_id=0."
    #         )
    #         tool_id = 0
    #     else:
    #         tool_id = tool.id

    #     # Calculate token count for the arguments
    #     try:
    #         token_count = len(llm_tokenizer.encode(call_msg["arguments"]))
    #     except Exception as e:
    #         logger.warning(
    #             f"Failed to tokenize arguments for {call_id}: {e}. Using length as estimate."
    #         )
    #         token_count = len(call_msg["arguments"])

    #     # Create ToolCall entry
    #     tool_call = ToolCall(
    #         chat_session_id=chat_session_id,
    #         parent_chat_message_id=parent_chat_message_id,
    #         parent_tool_call_id=None,  # Top-level tool call (nested not yet supported)
    #         turn_number=turn_number,
    #         depth=0,  # Top-level depth (nested not yet supported)
    #         tool_id=tool_id,
    #         tool_call_id=call_id,  # Now correctly stored as string
    #         tool_call_arguments=tool_arguments,
    #         tool_call_response=tool_response,
    #         tool_call_tokens=token_count,
    #         reasoning_tokens=None,  # Not yet implemented
    #     )

    #     db_session.add(tool_call)
    #     turn_number += 1

    # logger.info(
    #     f"Saved {turn_number} tool calls for chat session {chat_session_id}, "
    #     f"message {parent_chat_message_id}"
    # )


def extract_final_answer_from_packets(packet_history: list[Packet]) -> str:
    """Extract the final answer by concatenating all MessageDelta content."""
    final_answer = ""
    for packet in packet_history:
        if isinstance(packet.obj, MessageDelta) or isinstance(packet.obj, MessageStart):
            final_answer += packet.obj.content
    return final_answer
