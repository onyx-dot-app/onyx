import json

from sqlalchemy.orm import Session

from onyx.chat.chat_state import ChatStateContainer
from onyx.chat.chat_state import SearchDocKey
from onyx.configs.constants import DocumentSource
from onyx.context.search.models import SearchDoc
from onyx.db.chat import add_search_docs_to_chat_message
from onyx.db.chat import add_search_docs_to_tool_call
from onyx.db.chat import create_db_search_doc
from onyx.db.models import ChatMessage
from onyx.db.models import ToolCall
from onyx.db.tools import create_tool_call_no_commit
from onyx.natural_language_processing.utils import BaseTokenizer
from onyx.natural_language_processing.utils import get_tokenizer
from onyx.tools.models import ToolCallInfo
from onyx.utils.logger import setup_logger

logger = setup_logger()


def _create_and_link_tool_calls(
    tool_calls: list[ToolCallInfo],
    assistant_message: ChatMessage,
    db_session: Session,
    default_tokenizer: BaseTokenizer,
    tool_call_to_search_doc_ids: dict[str, list[int]],
) -> None:
    """
    Create ToolCall entries and link parent references and SearchDocs.

    This function handles the logic of:
    1. Creating all ToolCall objects (with temporary parent references)
    2. Flushing to get DB IDs
    3. Building mappings and updating parent references
    4. Linking SearchDocs to ToolCalls


    Args:
        tool_calls: List of tool call information to create
        assistant_message: The ChatMessage these tool calls belong to
        db_session: Database session
        default_tokenizer: Tokenizer for calculating token counts
        tool_call_to_search_doc_ids: Mapping from tool_call_id to list of search_doc IDs
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
            generated_images=(
                [img.model_dump() for img in tool_call_info.generated_images]
                if tool_call_info.generated_images
                else None
            ),
            tab_index=tool_call_info.tab_index,
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
    # Filter out orphaned children (whose parents don't exist) - this can happen
    # when generation is stopped mid-execution and parent tool calls were cancelled
    valid_tool_calls: list[ToolCall] = []
    for tool_call_obj in tool_call_objects:
        tool_call_info = tool_call_info_map[tool_call_obj.tool_call_id]
        if tool_call_info.parent_tool_call_id is not None:
            parent_id = tool_call_map.get(tool_call_info.parent_tool_call_id)
            if parent_id is not None:
                tool_call_obj.parent_tool_call_id = parent_id
                valid_tool_calls.append(tool_call_obj)
            else:
                # Parent doesn't exist (likely cancelled) - skip this orphaned child
                logger.warning(
                    f"Skipping tool call '{tool_call_obj.tool_call_id}' with missing parent "
                    f"'{tool_call_info.parent_tool_call_id}' (likely cancelled during execution)"
                )
                # Remove from DB session to prevent saving
                db_session.delete(tool_call_obj)
        else:
            # Top-level tool call (no parent)
            valid_tool_calls.append(tool_call_obj)

    # Link SearchDocs only to valid ToolCalls
    for tool_call_obj in valid_tool_calls:
        search_doc_ids = tool_call_to_search_doc_ids.get(tool_call_obj.tool_call_id, [])
        if search_doc_ids:
            add_search_docs_to_tool_call(
                tool_call_id=tool_call_obj.id,
                search_doc_ids=search_doc_ids,
                db_session=db_session,
            )


def save_chat_turn(
    message_text: str,
    reasoning_tokens: str | None,
    tool_calls: list[ToolCallInfo],
    citation_to_doc: dict[int, SearchDoc],
    all_search_docs: dict[SearchDocKey, SearchDoc],
    db_session: Session,
    assistant_message: ChatMessage,
    is_clarification: bool = False,
    emitted_citations: set[int] | None = None,
    pre_answer_processing_time: float | None = None,
) -> None:
    """
    Save a chat turn by populating the assistant_message and creating related entities.

    This function:
    1. Updates the ChatMessage with text, reasoning tokens, and token count
    2. Creates DB SearchDoc entries from pre-deduplicated all_search_docs
    3. Builds tool_call -> search_doc mapping for displayed docs
    4. Builds citation mapping from citation_to_doc
    5. Links all unique SearchDocs to the ChatMessage
    6. Creates ToolCall entries and links SearchDocs to them
    7. Builds the citations mapping for the ChatMessage

    Args:
        message_text: The message content to save
        reasoning_tokens: Optional reasoning tokens for the message
        tool_calls: List of tool call information to create ToolCall entries (may include search_docs)
        citation_to_doc: Mapping from citation number to SearchDoc for building citations
        all_search_docs: Pre-deduplicated search docs from ChatStateContainer
        db_session: Database session for persistence
        assistant_message: The ChatMessage object to populate (should already exist in DB)
        is_clarification: Whether this assistant message is a clarification question (deep research flow)
        emitted_citations: Set of citation numbers that were actually emitted during streaming.
            If provided, only citations in this set will be saved; others are filtered out.
        pre_answer_processing_time: Duration of processing before answer starts (in seconds)
    """
    # 1. Update ChatMessage with message content, reasoning tokens, and token count
    assistant_message.message = message_text
    assistant_message.reasoning_tokens = reasoning_tokens
    assistant_message.is_clarification = is_clarification

    # Use pre-answer processing time (captured when MESSAGE_START was emitted)
    if pre_answer_processing_time is not None:
        assistant_message.processing_duration_seconds = pre_answer_processing_time

    # Calculate token count using default tokenizer, when storing, this should not use the LLM
    # specific one so we use a system default tokenizer here.
    default_tokenizer = get_tokenizer(None, None)
    if message_text:
        assistant_message.token_count = len(default_tokenizer.encode(message_text))
    else:
        assistant_message.token_count = 0

    # 2. Create DB SearchDoc entries from pre-deduplicated all_search_docs
    search_doc_key_to_id: dict[SearchDocKey, int] = {}
    for key, search_doc_py in all_search_docs.items():
        db_search_doc = create_db_search_doc(
            server_search_doc=search_doc_py,
            db_session=db_session,
            commit=False,
        )
        search_doc_key_to_id[key] = db_search_doc.id

    # 3. Build tool_call -> search_doc mapping (for displayed docs in each tool call)
    tool_call_to_search_doc_ids: dict[str, list[int]] = {}
    for tool_call_info in tool_calls:
        if tool_call_info.search_docs:
            search_doc_ids_for_tool: list[int] = []
            for search_doc_py in tool_call_info.search_docs:
                key = ChatStateContainer.create_search_doc_key(search_doc_py)
                if key in search_doc_key_to_id:
                    search_doc_ids_for_tool.append(search_doc_key_to_id[key])
                else:
                    # Displayed doc not in all_search_docs - create it
                    # This can happen if displayed_docs contains docs not in search_docs
                    db_search_doc = create_db_search_doc(
                        server_search_doc=search_doc_py,
                        db_session=db_session,
                        commit=False,
                    )
                    search_doc_key_to_id[key] = db_search_doc.id
                    search_doc_ids_for_tool.append(db_search_doc.id)
            tool_call_to_search_doc_ids[tool_call_info.tool_call_id] = list(
                set(search_doc_ids_for_tool)
            )

    # Collect all search doc IDs for ChatMessage linking
    all_search_doc_ids_set: set[int] = set(search_doc_key_to_id.values())

    # 4. Build a citation mapping from the citation number to the saved DB SearchDoc ID
    # Only include citations that were actually emitted during streaming
    citation_number_to_search_doc_id: dict[int, int] = {}

    for citation_num, search_doc_py in citation_to_doc.items():
        # Skip citations that weren't actually emitted (if emitted_citations is provided)
        if emitted_citations is not None and citation_num not in emitted_citations:
            continue

        # Create the unique key for this SearchDoc version
        search_doc_key = ChatStateContainer.create_search_doc_key(search_doc_py)

        # Get the search doc ID (should already exist from processing tool_calls)
        if search_doc_key in search_doc_key_to_id:
            db_search_doc_id = search_doc_key_to_id[search_doc_key]
        else:
            # Citation doc not found in tool call search_docs
            # Expected case: Project files (source_type=FILE) are cited but don't come from tool calls
            # Unexpected case: Other citation-only docs (indicates a potential issue upstream)
            is_project_file = search_doc_py.source_type == DocumentSource.FILE

            if is_project_file:
                logger.info(
                    f"Project file citation {search_doc_py.document_id} not in tool calls, creating it"
                )
            else:
                logger.warning(
                    f"Citation doc {search_doc_py.document_id} not found in tool call search_docs, creating it"
                )

            # Create the SearchDoc in the database
            # NOTE: It's important that this maps to the saved DB Document ID, because
            # the match-highlights are specific to this saved version, not any document that has
            # the same document_id.
            db_search_doc = create_db_search_doc(
                server_search_doc=search_doc_py,
                db_session=db_session,
                commit=False,
            )
            db_search_doc_id = db_search_doc.id
            search_doc_key_to_id[search_doc_key] = db_search_doc_id

            # Link project files to ChatMessage to enable frontend preview
            if is_project_file:
                all_search_doc_ids_set.add(db_search_doc_id)

        # Build mapping from citation number to search doc ID
        citation_number_to_search_doc_id[citation_num] = db_search_doc_id

    # 5. Link all unique SearchDocs (from both tool calls and citations) to ChatMessage
    final_search_doc_ids: list[int] = list(all_search_doc_ids_set)
    if final_search_doc_ids:
        add_search_docs_to_chat_message(
            chat_message_id=assistant_message.id,
            search_doc_ids=final_search_doc_ids,
            db_session=db_session,
        )

    # 6. Create ToolCall entries and link SearchDocs to them
    _create_and_link_tool_calls(
        tool_calls=tool_calls,
        assistant_message=assistant_message,
        db_session=db_session,
        default_tokenizer=default_tokenizer,
        tool_call_to_search_doc_ids=tool_call_to_search_doc_ids,
    )

    # 7. Build citations mapping - use the mapping we already built in step 4
    assistant_message.citations = (
        citation_number_to_search_doc_id if citation_number_to_search_doc_id else None
    )

    # Finally save the messages, tool calls, and docs
    db_session.commit()
