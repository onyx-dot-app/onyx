import json
from typing import Any

from sqlalchemy.orm import Session

from onyx.chat.chat_state import ChatStateContainer, SearchDocKey
from onyx.context.search.models import SearchDoc
from onyx.db.chat import (
    add_search_docs_to_tool_call,
)
from onyx.db.chat_display import save_chat_display__no_commit
from onyx.db.models import ChatMessage, ToolCall
from onyx.db.tools import create_tool_call_no_commit
from onyx.natural_language_processing.utils import BaseTokenizer, get_tokenizer
from onyx.tools.records import ToolCallInfo
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
                "Failed to tokenize tool call arguments for %s: %s. Using length as (over) estimate.",
                tool_call_info.tool_call_id,
                e,
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
                    "Skipping tool call '%s' with missing parent '%s' (likely cancelled during execution)",
                    tool_call_obj.tool_call_id,
                    tool_call_info.parent_tool_call_id,
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
    persist_content: bool = True,
    request_params: dict[str, Any] | None = None,
) -> None:
    """Save displayed content and legacy tool rows in one transaction."""
    tokenizer = get_tokenizer(None, None)
    tool_sources = save_chat_display__no_commit(
        message_text=message_text,
        reasoning_tokens=reasoning_tokens,
        tool_calls=tool_calls,
        citation_to_doc=citation_to_doc,
        all_search_docs=all_search_docs,
        document_key=ChatStateContainer.create_search_doc_key,
        db_session=db_session,
        assistant_message=assistant_message,
        tokenizer=tokenizer,
        is_clarification=is_clarification,
        emitted_citations=emitted_citations,
        pre_answer_processing_time=pre_answer_processing_time,
        persist_content=persist_content,
        request_params=request_params,
    )
    if persist_content:
        _create_and_link_tool_calls(
            tool_calls=tool_calls,
            assistant_message=assistant_message,
            db_session=db_session,
            default_tokenizer=tokenizer,
            tool_call_to_search_doc_ids={
                info.tool_call_id: sources
                for info, sources in zip(tool_calls, tool_sources, strict=True)
            },
        )
    db_session.commit()
