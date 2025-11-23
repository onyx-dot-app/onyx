# TODO: Figure out a way to persist information is robust to cancellation,
# modular so easily testable in unit tests and evals [likely injecting some higher
# level session manager and span sink], potentially has some robustness off the critical path,
# and promotes clean separation of concerns.
import json
import logging

from sqlalchemy.orm import Session

from onyx.context.search.models import CitationDocInfo
from onyx.db.chat import add_search_docs_to_chat_message
from onyx.db.chat import create_db_search_doc
from onyx.db.models import ChatMessage
from onyx.db.models import ToolCall
from onyx.db.tools import create_tool_call_no_commit
from onyx.natural_language_processing.utils import BaseTokenizer
from onyx.natural_language_processing.utils import get_tokenizer
from onyx.tools.models import ToolCallInfo

logger = logging.getLogger(__name__)


def _create_and_link_tool_calls(
    tool_calls: list[ToolCallInfo],
    assistant_message: ChatMessage,
    db_session: Session,
    default_tokenizer: BaseTokenizer,
) -> None:
    """
    Create ToolCall entries and link parent references.

    This function handles the logic of:
    1. Creating all ToolCall objects (with temporary parent references)
    2. Flushing to get DB IDs
    3. Building mappings and updating parent references

    Args:
        tool_calls: List of tool call information to create
        assistant_message: The ChatMessage these tool calls belong to
        db_session: Database session
        default_tokenizer: Tokenizer for calculating token counts
    """
    # Create all ToolCall objects first (without parent_tool_call_id set)
    # We'll update parent references after flushing to get IDs
    tool_call_objects: list[ToolCall] = []
    tool_call_info_map: dict[str, ToolCallInfo] = {}

    for tool_call_info in tool_calls:
        tool_call_info_map[tool_call_info.tool_call_id] = tool_call_info

        # Calculate tool_call_tokens from arguments
        try:
            arguments_json_str = json.dumps(tool_call_info.tool_call_arguments)
            tool_call_tokens = len(default_tokenizer.encode(arguments_json_str))
        except Exception as e:
            logger.warning(
                f"Failed to tokenize tool call arguments for {tool_call_info.tool_call_id}: {e}. "
                f"Using length as (over) estimate."
            )
            arguments_json_str = json.dumps(tool_call_info.tool_call_arguments)
            tool_call_tokens = len(arguments_json_str)

        parent_message_id = (
            assistant_message.id if tool_call_info.parent_tool_call_id is None else None
        )

        # Create ToolCall DB entry (parent_tool_call_id will be set after flush)
        # This is needed to get the IDs for the parent pointers
        tool_call = create_tool_call_no_commit(
            chat_session_id=assistant_message.chat_session_id,
            parent_chat_message_id=parent_message_id,
            turn_number=tool_call_info.turn_index,
            tool_id=tool_call_info.tool_id,
            tool_call_id=tool_call_info.tool_call_id,
            tool_call_arguments=tool_call_info.tool_call_arguments,
            tool_call_response=tool_call_info.tool_call_response,
            tool_call_tokens=tool_call_tokens,
            db_session=db_session,
            parent_tool_call_id=None,  # Will be updated after flush
            reasoning_tokens=tool_call_info.reasoning_tokens,
            add_only=True,
        )

        # Flush to get all of the IDs
        db_session.flush()

        tool_call_objects.append(tool_call)

    # Build mapping of tool calls (tool_call_id string -> DB id int)
    tool_call_map: dict[str, int] = {}
    for tool_call_obj in tool_call_objects:
        tool_call_map[tool_call_obj.tool_call_id] = tool_call_obj.id

    # Update parent_tool_call_id for all tool calls
    for tool_call_obj in tool_call_objects:
        tool_call_info = tool_call_info_map[tool_call_obj.tool_call_id]
        if tool_call_info.parent_tool_call_id is not None:
            parent_id = tool_call_map.get(tool_call_info.parent_tool_call_id)
            if parent_id is not None:
                tool_call_obj.parent_tool_call_id = parent_id
            else:
                # This would cause chat sessions to fail if this function is miscalled with
                # tool calls that have bad parent pointers but this falls under "fail loudly"
                raise ValueError(
                    f"Parent tool call with tool_call_id '{tool_call_info.parent_tool_call_id}' "
                    f"not found for tool call '{tool_call_obj.tool_call_id}'"
                )


def save_chat_turn(
    message_text: str,
    reasoning_tokens: str | None,
    tool_calls: list[ToolCallInfo],
    citation_docs_info: list[CitationDocInfo],
    db_session: Session,
    assistant_message: ChatMessage,
) -> None:
    """
    Save a chat turn by populating the assistant_message and creating related entities.

    Args:
        message_text: The message content to save
        reasoning_tokens: Optional reasoning tokens for the message
        tool_calls: List of tool call information to create ToolCall entries
        citation_docs_info: List of citation document information to create SearchDoc entries
        db_session: Database session for persistence
        assistant_message: The ChatMessage object to populate (should already exist in DB)
    """
    # 1. Update ChatMessage with message content, reasoning tokens, and token count
    assistant_message.message = message_text
    assistant_message.reasoning_tokens = reasoning_tokens

    # Calculate token count using default tokenizer
    default_tokenizer = get_tokenizer(None, None)
    if message_text:
        assistant_message.token_count = len(default_tokenizer.encode(message_text))
    else:
        assistant_message.token_count = 0

    # 2. Create SearchDoc entries from citation_docs_info
    citation_number_to_search_doc_id: dict[int, int] = {}
    search_doc_ids: list[int] = []

    for citation_doc_info in citation_docs_info:
        # Extract SearchDoc pydantic model
        search_doc_py = citation_doc_info.search_doc

        # Create DB SearchDoc entry using db function
        db_search_doc = create_db_search_doc(
            server_search_doc=search_doc_py,
            db_session=db_session,
            commit=False,
        )

        search_doc_ids.append(db_search_doc.id)

        # Build mapping from citation number to search doc ID
        if citation_doc_info.citation_number is not None:
            citation_number_to_search_doc_id[citation_doc_info.citation_number] = (
                db_search_doc.id
            )

    # 3. Link SearchDocs to ChatMessage
    if search_doc_ids:
        add_search_docs_to_chat_message(
            chat_message_id=assistant_message.id,
            search_doc_ids=search_doc_ids,
            db_session=db_session,
        )

    # 4. Create ToolCall entries
    _create_and_link_tool_calls(
        tool_calls=tool_calls,
        assistant_message=assistant_message,
        db_session=db_session,
        default_tokenizer=default_tokenizer,
    )

    # 5. Build citations mapping from citation_docs_info
    # Any citation_doc_info with a citation_number appeared in the text and should be mapped
    citations: dict[int, int] = {}
    for citation_doc_info in citation_docs_info:
        if citation_doc_info.citation_number is not None:
            search_doc_id = citation_number_to_search_doc_id.get(
                citation_doc_info.citation_number
            )
            if search_doc_id is not None:
                citations[citation_doc_info.citation_number] = search_doc_id
            else:
                logger.warning(
                    f"Citation number {citation_doc_info.citation_number} found in citation_docs_info "
                    f"but no matching search doc ID in mapping"
                )

    assistant_message.citations = citations if citations else None

    # Finally save the messages, tool calls, and docs
    db_session.commit()
