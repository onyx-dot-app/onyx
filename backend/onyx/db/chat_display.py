"""Display persistence shared by the production and canonical response writers."""

from collections.abc import Callable, Hashable, Mapping, Sequence
from typing import Any

from sqlalchemy.orm import Session

from onyx.configs.constants import DocumentSource
from onyx.context.search.models import SearchDoc
from onyx.db.chat import add_search_docs_to_chat_message, create_db_search_doc
from onyx.db.models import ChatMessage
from onyx.file_processing.file_types import guess_mime_type
from onyx.file_store.models import FileDescriptor
from onyx.natural_language_processing.utils import BaseTokenizer
from onyx.server.query_and_chat.chat_utils import mime_type_to_chat_file_type
from onyx.tools.records import ToolCallInfo
from onyx.utils.postgres_sanitization import sanitize_string


def extract_referenced_file_descriptors(
    tool_calls: Sequence[ToolCallInfo],
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
                mime_type = guess_mime_type(gen_file.filename)
                descriptors.append(
                    FileDescriptor(
                        id=file_id,
                        type=mime_type_to_chat_file_type(mime_type),
                        name=gen_file.filename,
                    )
                )
    return descriptors


def save_chat_display__no_commit[Key: Hashable](
    *,
    message_text: str,
    reasoning_tokens: str | None,
    tool_calls: Sequence[ToolCallInfo],
    citation_to_doc: dict[int, SearchDoc],
    all_search_docs: Mapping[Key, SearchDoc],
    document_key: Callable[[SearchDoc], Key],
    db_session: Session,
    assistant_message: ChatMessage,
    tokenizer: BaseTokenizer,
    is_clarification: bool,
    emitted_citations: set[int] | None,
    pre_answer_processing_time: float | None,
    persist_content: bool,
    request_params: dict[str, Any] | None,
) -> list[list[int]]:
    """Write display fields and source links; return source IDs in tool order."""
    text = sanitize_string(message_text)
    assistant_message.message = text if persist_content else ""
    assistant_message.reasoning_tokens = (
        (sanitize_string(reasoning_tokens) if reasoning_tokens else reasoning_tokens)
        if persist_content
        else None
    )
    assistant_message.token_count = len(tokenizer.encode(text)) if text else 0
    assistant_message.is_clarification = is_clarification
    assistant_message.request_params = request_params
    if pre_answer_processing_time is not None:
        assistant_message.processing_duration_seconds = pre_answer_processing_time
    if not persist_content:
        assistant_message.citations = None
        return []

    source_ids: dict[Key, int] = {}

    def save_source(document: SearchDoc) -> int:
        key = document_key(document)
        if key not in source_ids:
            source_ids[key] = create_db_search_doc(
                server_search_doc=document, db_session=db_session, commit=False
            ).id
        return source_ids[key]

    for key, document in all_search_docs.items():
        source_ids[key] = create_db_search_doc(
            server_search_doc=document, db_session=db_session, commit=False
        ).id
    tool_sources = [
        list(
            dict.fromkeys(save_source(document) for document in tool.search_docs or [])
        )
        for tool in tool_calls
    ]
    linked_source_ids = set(source_ids.values())
    citations: dict[int, int] = {}
    for number, document in citation_to_doc.items():
        if emitted_citations is not None and number not in emitted_citations:
            continue
        citations[number] = save_source(document)
        # Project files can be cited without appearing in a tool's source list.
        if document.source_type == DocumentSource.FILE:
            linked_source_ids.add(citations[number])
    if linked_source_ids:
        add_search_docs_to_chat_message(
            chat_message_id=assistant_message.id,
            search_doc_ids=list(linked_source_ids),
            db_session=db_session,
        )
    assistant_message.citations = citations or None
    if text:
        referenced = extract_referenced_file_descriptors(tool_calls, text)
        if referenced:
            assistant_message.files = (assistant_message.files or []) + referenced
    return tool_sources
