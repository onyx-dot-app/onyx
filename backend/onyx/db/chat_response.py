import json
import mimetypes

from sqlalchemy.orm import Session

from onyx.agents.transcript import AgentTranscript
from onyx.chat.incognito_context import save_incognito_response
from onyx.chat.models import (
    ChatResponseSnapshot,
    MessagePresentation,
    ToolRecordReference,
)
from onyx.configs.constants import DocumentSource
from onyx.context.search.models import SearchDoc
from onyx.db.agent_transcript import (
    set_agent_transcript,
)
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
    tool_call_to_search_doc_ids: dict[tuple[str, str], list[int]],
) -> list[ToolRecordReference]:
    """Link message-scoped tool identities; the caller owns the transaction."""
    keys = {info.execution_key for info in tool_calls}
    if len(keys) != len(tool_calls):
        raise ValueError("Duplicate tool identity within one response")
    if any(
        info.parent_execution_key is not None and info.parent_execution_key not in keys
        for info in tool_calls
    ):
        raise ValueError("Child artifact has no parent operation")
    records: dict[tuple[str, str], ToolCall] = {}
    for info in tool_calls:
        record = create_tool_call_no_commit(
            chat_session_id=assistant_message.chat_session_id,
            parent_chat_message_id=assistant_message.id
            if info.parent_execution_key is None
            else None,
            turn_number=info.turn_index,
            tool_id=info.tool_id,
            tool_call_id=info.tool_call_id,
            tool_call_arguments=info.tool_call_arguments,
            tool_call_response=info.tool_call_response,
            tool_call_tokens=len(
                default_tokenizer.encode(json.dumps(info.tool_call_arguments))
            ),
            db_session=db_session,
            reasoning_tokens=info.reasoning_tokens,
            generated_images=[image.model_dump() for image in info.generated_images]
            if info.generated_images
            else None,
            tab_index=info.tab_index,
            add_only=True,
        )
        records[info.execution_key] = record
    db_session.flush()
    for info in tool_calls:
        record = records[info.execution_key]
        if info.parent_execution_key is not None:
            record.parent_tool_call_id = records[info.parent_execution_key].id
        search_doc_ids = tool_call_to_search_doc_ids.get(info.execution_key, [])
        if search_doc_ids:
            add_search_docs_to_tool_call(
                tool_call_id=record.id,
                search_doc_ids=search_doc_ids,
                db_session=db_session,
            )

    return [
        ToolRecordReference(message_id=key[0], tool_call_id=key[1], record_id=record.id)
        for key, record in records.items()
    ]


def save_chat_turn(
    message_text: str,
    reasoning_tokens: str | None,
    tool_calls: list[ToolCallInfo],
    citation_to_doc: dict[int, SearchDoc],
    all_search_docs: dict[str, SearchDoc],
    db_session: Session,
    assistant_message: ChatMessage,
    is_clarification: bool = False,
    emitted_citations: set[int] | None = None,
    pre_answer_processing_time: float | None = None,
    persist_content: bool = True,
    request_params: GenerationRequestParams | None = None,
    agent_transcript: AgentTranscript | None = None,
    presentation: list[MessagePresentation] | None = None,
) -> None:
    """Persist answer content, transcript, and tool records, then commit the session.

    Content retention applies to related records; request attribution remains stored.
    """
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
    search_doc_key_to_id: dict[str, int] = {}
    for key, search_doc_py in all_search_docs.items():
        db_search_doc = create_db_search_doc(
            server_search_doc=search_doc_py,
            db_session=db_session,
            commit=False,
        )
        search_doc_key_to_id[key] = db_search_doc.id

    # 3. Build tool_call -> search_doc mapping (for displayed docs in each tool call)
    tool_call_to_search_doc_ids: dict[tuple[str, str], list[int]] = {}
    for tool_call_info in tool_calls:
        if tool_call_info.search_docs:
            search_doc_ids_for_tool: list[int] = []
            for search_doc_py in tool_call_info.search_docs:
                key = search_doc_py.document_id
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
            tool_call_to_search_doc_ids[tool_call_info.execution_key] = list(
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
        search_doc_key = search_doc_py.document_id

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
    tool_records = _create_and_link_tool_calls(
        tool_calls=tool_calls,
        assistant_message=assistant_message,
        db_session=db_session,
        default_tokenizer=default_tokenizer,
        tool_call_to_search_doc_ids=tool_call_to_search_doc_ids,
    )

    set_agent_transcript(
        assistant_message,
        agent_transcript,
        db_session=db_session,
        persist_content=persist_content,
        presentation=presentation,
        tool_records=tool_records,
    )

    # 7. Build citations mapping - use the mapping we already built in step 4
    assistant_message.citations = citation_number_to_search_doc_id or None

    # Preserve referenced generated files for subsequent turns. Unreferenced
    # files remain intermediate artifacts.
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
    """Persist one terminal response and its accepted artifacts from a stable snapshot."""
    if response.error is not None:
        answer = response.answer or ""
    elif response.cancelled:
        answer = (
            (response.answer + " ... \n\n") if response.answer else ""
        ) + "Generation was stopped by the user."
    else:
        if response.answer is None:
            raise RuntimeError("Agent completed without an answer")
        answer = response.answer
    with get_session_with_current_tenant() as session:
        message = session.get(ChatMessage, message_id)
        if message is None:
            raise ValueError("Chat response is unavailable")
        chat_session_id = message.chat_session_id
        keeps_content = record_mode_persists_content(
            message.chat_session.incognito_record_mode
        )
        message.error = (
            (
                sanitize_string(response.error)
                if keeps_content
                else "The model encountered an error."
            )
            if response.error is not None
            else None
        )
        save_chat_turn(
            message_text=answer,
            reasoning_tokens=response.reasoning,
            request_params=response.request_params,
            citation_to_doc=response.citation_to_doc,
            tool_calls=response.tool_calls,
            all_search_docs=response.all_search_docs,
            db_session=session,
            assistant_message=message,
            is_clarification=response.is_clarification,
            emitted_citations={
                citation.citation_number for citation in response.citation_info
            },
            pre_answer_processing_time=response.pre_answer_processing_time,
            persist_content=keeps_content,
            agent_transcript=response.transcript,
            presentation=response.presentation,
        )
    if not keeps_content:
        messages = (
            list(response.transcript.messages)
            if response.transcript and response.transcript.messages
            else [AssistantMessage(content=[TextContent(text=answer)])]
        )
        sources_by_run: dict[str, dict[int, SearchDoc]] = {}
        if response.transcript is not None:
            documents = {
                **{doc.document_id: doc for doc in response.citation_to_doc.values()},
                **response.all_search_docs,
            }
            for item in response.presentation:
                sources = sources_by_run.setdefault(item.run_id, {})
                for number, document_id in item.citation_documents.items():
                    if document_id in documents:
                        sources[number] = documents[document_id]
        save_incognito_response(
            chat_session_id,
            response.transcript,
            sources_by_run,
            message_id=message_id,
            messages=messages,
        )
