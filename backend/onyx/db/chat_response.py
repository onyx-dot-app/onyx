import json
import mimetypes

from sqlalchemy.orm import Session

from onyx.agents.transcript import AgentTranscript
from onyx.chat.chat_state import ChatResponseSnapshot, ChatStateContainer, SearchDocKey
from onyx.chat.incognito_context import append_incognito_messages
from onyx.configs.constants import DocumentSource
from onyx.context.search.models import SearchDoc
from onyx.db.agent_transcript import set_agent_transcript
from onyx.db.chat import (
    add_search_docs_to_chat_message,
    add_search_docs_to_tool_call,
    create_db_search_doc,
)
from onyx.db.engine.sql_engine import get_session_with_current_tenant
from onyx.db.enums import record_mode_persists_content
from onyx.db.models import ChatMessage, ToolCall
from onyx.db.tools import create_tool_call_no_commit
from onyx.file_store.models import FileDescriptor
from onyx.llm.models import AssistantMessage, GenerationRequestParams, TextContent
from onyx.natural_language_processing.utils import BaseTokenizer, get_tokenizer
from onyx.server.query_and_chat.chat_utils import mime_type_to_chat_file_type
from onyx.tools.models import ToolCallInfo
from onyx.utils.logger import setup_logger
from onyx.utils.postgres_sanitization import sanitize_string

logger = setup_logger()


def _extract_referenced_file_descriptors(
    tool_calls: list[ToolCallInfo],
    message_text: str,
) -> list[FileDescriptor]:
    """Extract FileDescriptors for code interpreter files referenced in the message text."""
    descriptors: list[FileDescriptor] = []
    for tool_call_info in tool_calls:
        if not tool_call_info.generated_files:
            continue
        for gen_file in tool_call_info.generated_files:
            file_id = (
                gen_file.file_link.rsplit("/", 1)[-1] if gen_file.file_link else ""
            )
            if file_id and file_id in message_text:
                mime_type, _ = mimetypes.guess_type(gen_file.filename)
                descriptors.append(
                    FileDescriptor(
                        id=file_id,
                        type=mime_type_to_chat_file_type(mime_type),
                        name=gen_file.filename,
                    )
                )
    return descriptors


def _create_and_link_tool_calls(
    tool_calls: list[ToolCallInfo],
    assistant_message: ChatMessage,
    db_session: Session,
    default_tokenizer: BaseTokenizer,
    tool_call_to_search_doc_ids: dict[str, list[int]],
) -> None:
    """Link tool calls after IDs exist; the caller owns the transaction."""
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
                exc_info=True,
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
    request_params: GenerationRequestParams | None = None,
    agent_transcript: AgentTranscript | None = None,
) -> None:
    """Persist answer content and its tool/citation records; the caller owns the transaction.

    Content retention applies to transcripts and related records. Request attribution remains stored.
    """
    set_agent_transcript(
        assistant_message, agent_transcript, persist_content=persist_content
    )
    sanitized_message_text = (
        sanitize_string(message_text) if message_text else message_text
    )
    # A content-free turn keeps the row and its token count, which comes from
    # the real answer, but none of the conversation-derived parts.
    if persist_content:
        assistant_message.message = sanitized_message_text
        assistant_message.reasoning_tokens = (
            sanitize_string(reasoning_tokens) if reasoning_tokens else reasoning_tokens
        )
    else:
        assistant_message.message = ""
        assistant_message.reasoning_tokens = None
        tool_calls = []
        citation_to_doc = {}
        all_search_docs = {}
        emitted_citations = set()
    assistant_message.is_clarification = is_clarification
    # Attribution, not content, so incognito keeps it.
    assistant_message.request_params = (
        request_params.model_dump(mode="json") if request_params is not None else None
    )

    if pre_answer_processing_time is not None:
        assistant_message.processing_duration_seconds = pre_answer_processing_time

    # Stored token counts use a stable tokenizer across model changes.
    default_tokenizer = get_tokenizer(None, None)
    if sanitized_message_text:
        assistant_message.token_count = len(
            default_tokenizer.encode(sanitized_message_text)
        )
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
                    "Project file citation %s not in tool calls, creating it",
                    search_doc_py.document_id,
                )
            else:
                logger.warning(
                    "Citation doc %s not found in tool call search_docs, creating it",
                    search_doc_py.document_id,
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
    assistant_message.citations = citation_number_to_search_doc_id or None

    # 8. Attach code interpreter generated files that the assistant actually
    # referenced in its response, so they are available via load_all_chat_files
    # on subsequent turns. Files not mentioned are intermediate artifacts.
    if sanitized_message_text:
        referenced = _extract_referenced_file_descriptors(
            tool_calls, sanitized_message_text
        )
        if referenced:
            existing_files = assistant_message.files or []
            assistant_message.files = existing_files + referenced

    # Finally save the messages, tool calls, and docs
    db_session.commit()


def save_chat_response(*, message_id: int, response: ChatResponseSnapshot) -> None:
    """Save one complete or cancelled response from a stable snapshot."""
    if response.cancelled:
        answer = (
            (response.answer_tokens + " ... \n\n") if response.answer_tokens else ""
        ) + "Generation was stopped by the user."
    else:
        if response.answer_tokens is None:
            raise RuntimeError("Agent completed without an answer")
        answer = response.answer_tokens
    with get_session_with_current_tenant() as session:
        message = session.get(ChatMessage, message_id)
        if message is None:
            raise RuntimeError(f"ChatMessage {message_id} not found during completion")
        keeps_content = record_mode_persists_content(
            message.chat_session.incognito_record_mode
        )
        save_chat_turn(
            message_text=answer,
            reasoning_tokens=response.reasoning_tokens,
            request_params=response.request_params,
            citation_to_doc=response.citation_to_doc,
            tool_calls=response.tool_calls,
            all_search_docs=response.all_search_docs,
            db_session=session,
            assistant_message=message,
            is_clarification=response.is_clarification,
            emitted_citations=response.emitted_citations,
            pre_answer_processing_time=response.pre_answer_processing_time,
            persist_content=keeps_content,
            agent_transcript=response.transcript,
        )
        if not keeps_content:
            messages = (
                list(response.transcript.messages)
                if response.transcript and response.transcript.messages
                else [AssistantMessage(content=[TextContent(text=answer)])]
            )
            append_incognito_messages(message.chat_session_id, messages)
