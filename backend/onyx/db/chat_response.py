import mimetypes
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session, aliased, joinedload, object_session, selectinload

from onyx.agents.compaction import count_tokens
from onyx.chat.incognito_context import save_incognito_response
from onyx.chat.models import (
    ChatExecutionRecord,
    ChatResponseSnapshot,
    MessageRendering,
    ResponseRecord,
    ToolRecordReference,
)
from onyx.chat.response_items import (
    ResponseItemKind,
    ResponseText,
    TextPurpose,
    messages_from_items,
)
from onyx.configs.constants import DocumentSource, MessageType
from onyx.context.search.models import SearchDoc
from onyx.db.chat import (
    add_search_docs_to_chat_message,
    add_search_docs_to_tool_call,
    create_db_search_doc,
)
from onyx.db.chat_history import checkpoint_from_summary, find_summary_for_ancestry
from onyx.db.chat_response_items import (
    finish_checkpoint__no_commit,
    read_response_record,
    write_response_items,
)
from onyx.db.chat_subagents import (
    MAX_AGENT_DEPTH,
    MAX_AGENT_HISTORY_RUNS,
    MAX_CONVERSATION_MESSAGES,
    agent_session_path,
    root_response_id,
    visible_message_ids,
)
from onyx.db.engine.sql_engine import get_session_with_current_tenant
from onyx.db.enums import record_mode_persists_content
from onyx.db.models import (
    ChatMessage,
    ChatResponseItem,
    ChatSession,
    ToolCall,
)
from onyx.file_store.models import FileDescriptor
from onyx.llm.models import (
    AssistantMessage,
    GenerationRequestParams,
    TextContent,
    UserMessage,
)
from onyx.natural_language_processing.utils import get_tokenizer
from onyx.server.query_and_chat.chat_utils import mime_type_to_chat_file_type
from onyx.tools.models import ToolCallInfo
from onyx.utils.logger import setup_logger
from onyx.utils.postgres_sanitization import sanitize_json_like, sanitize_string

logger = setup_logger()

CHAT_RESPONSE_STATEMENT_TIMEOUT_MS = 30_000
CHAT_RESPONSE_LOCK_TIMEOUT_MS = 5_000


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


def _attach_tool_artifacts(
    tool_calls: list[ToolCallInfo],
    tool_records: list[ToolRecordReference],
    db_session: Session,
    tool_call_to_search_doc_ids: dict[tuple[str, str], list[int]],
) -> None:
    """Attach display metadata to canonical tools; the caller owns the transaction."""
    references = {
        (ref.message_id, ref.tool_call_id): ref.record_id for ref in tool_records
    }
    records: dict[tuple[str, str], ToolCall] = {}
    for info in tool_calls:
        record_id = references.get(info.execution_key)
        if record_id is None:
            raise ValueError("Tool display metadata has no accepted tool call")
        record = db_session.get(ToolCall, record_id)
        if record is None:
            raise ValueError("Accepted tool call is unavailable")
        record.legacy_response = (
            info.result_metadata.model_dump_json()
            if info.result_metadata is not None
            else ""
        )
        record.tool_id = info.tool_id
        record.turn_number = info.turn_index
        record.tab_index = info.tab_index
        record.generated_images = [
            image.model_dump() for image in info.generated_images or []
        ] or None
        records[info.execution_key] = record
    for info in tool_calls:
        record = records[info.execution_key]
        if info.parent_execution_key is not None:
            parent = records.get(info.parent_execution_key)
            if parent is None:
                raise ValueError("Child artifact has no parent operation")
            record.parent_tool_call_id = parent.id
        search_doc_ids = tool_call_to_search_doc_ids.get(info.execution_key, [])
        if search_doc_ids:
            add_search_docs_to_tool_call(
                tool_call_id=record.id,
                search_doc_ids=search_doc_ids,
                db_session=db_session,
            )


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
    response_record: ResponseRecord | None = None,
    presentation: dict[str, MessageRendering] | None = None,
) -> None:
    """Persist accepted output, display content, and tool artifacts, then commit the session.

    Content retention applies to related records; request attribution remains stored.
    """
    tool_records = save_response_content(
        assistant_message,
        response_record,
        db_session=db_session,
        persist_content=persist_content,
        presentation=presentation,
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

    search_doc_key_to_id: dict[str, int] = {}
    for key, search_doc_py in all_search_docs.items():
        db_search_doc = create_db_search_doc(
            server_search_doc=search_doc_py,
            db_session=db_session,
            commit=False,
        )
        search_doc_key_to_id[key] = db_search_doc.id

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

    all_search_doc_ids_set: set[int] = set(search_doc_key_to_id.values())

    citation_number_to_search_doc_id: dict[int, int] = {}

    for citation_num, search_doc_py in citation_to_doc.items():
        # Skip citations that weren't actually emitted (if emitted_citations is provided)
        if emitted_citations is not None and citation_num not in emitted_citations:
            continue

        search_doc_key = search_doc_py.document_id

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

    final_search_doc_ids: list[int] = list(all_search_doc_ids_set)
    if final_search_doc_ids:
        add_search_docs_to_chat_message(
            chat_message_id=assistant_message.id,
            search_doc_ids=final_search_doc_ids,
            db_session=db_session,
        )

    _attach_tool_artifacts(
        tool_calls, tool_records, db_session, tool_call_to_search_doc_ids
    )

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

    db_session.commit()


def configure_response_transaction__no_commit(session: Session) -> None:
    """Bound database waits while a response holds its execution lease."""
    session.execute(
        select(
            func.set_config(
                "statement_timeout",
                str(CHAT_RESPONSE_STATEMENT_TIMEOUT_MS),
                True,
            )
        )
    )
    session.execute(
        select(
            func.set_config(
                "lock_timeout",
                str(CHAT_RESPONSE_LOCK_TIMEOUT_MS),
                True,
            )
        )
    )


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
        configure_response_transaction__no_commit(session)
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
        finish_checkpoint__no_commit(session, message_id)
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
            response_record=response.response,
            presentation=response.presentation,
        )
    if not keeps_content:
        messages = (
            messages_from_items(response.response.items)
            if response.response and response.response.items
            else [AssistantMessage(content=[TextContent(text=answer)])]
        )
        sources_by_run: dict[str, dict[int, SearchDoc]] = {}
        if response.response is not None:
            documents = {
                **{doc.document_id: doc for doc in response.citation_to_doc.values()},
                **response.all_search_docs,
            }
            pending = list(response.response.child_runs)
            while pending:
                record = pending.pop()
                sources = sources_by_run.setdefault(record.run_id, {})
                for item in record.items:
                    setting = response.presentation.get(item.id)
                    if setting is None:
                        continue
                    for number, document_id in setting.citation_documents.items():
                        if document_id in documents:
                            sources[number] = documents[document_id]
                pending.extend(record.child_runs)
        save_incognito_response(
            chat_session_id,
            response.response,
            sources_by_run,
            message_id=message_id,
            messages=messages,
        )


def _child_responses(db_session: Session, response_ids: list[int]) -> list[ChatMessage]:
    question = aliased(ChatMessage)
    return list(
        db_session.scalars(
            select(ChatMessage)
            .join(question, ChatMessage.parent_message_id == question.id)
            .join(ToolCall, question.invoking_tool_call_id == ToolCall.id)
            .join(ChatResponseItem, ChatResponseItem.tool_call_id == ToolCall.id)
            .where(
                ChatResponseItem.kind == ResponseItemKind.TOOL_CALL,
                ToolCall.parent_chat_message_id.in_(response_ids),
                ChatMessage.response_status.is_not(None),
            )
            .options(
                joinedload(ChatMessage.chat_session),
                joinedload(ChatMessage.parent_message).joinedload(
                    ChatMessage.invoking_tool_call
                ),
                joinedload(ChatMessage.parent_message).joinedload(
                    ChatMessage.parent_message
                ),
                selectinload(ChatMessage.response_items),
            )
            # Stable display order; predecessor links determine child history.
            .order_by(ChatResponseItem.position, ChatMessage.id)
            .limit(MAX_AGENT_HISTORY_RUNS + 1)
        )
    )


def _load_child_responses(
    db_session: Session, response_id: int
) -> dict[int, list[ChatMessage]]:
    """Load each hierarchy level together before assembling the response tree."""
    children: dict[int, list[ChatMessage]] = {}
    parents = [response_id]
    visited = {response_id}
    for depth in range(MAX_AGENT_DEPTH + 1):
        rows = _child_responses(db_session, parents)
        if not rows:
            return children
        parents = []
        for row in rows:
            if (
                depth == MAX_AGENT_DEPTH
                or len(visited) >= MAX_AGENT_HISTORY_RUNS
                or row.id in visited
            ):
                raise ValueError(
                    "Response hierarchy exceeds its limit or contains a cycle"
                )
            question = row.parent_message
            invocation = question.invoking_tool_call if question else None
            if invocation is None or invocation.parent_chat_message_id is None:
                raise ValueError("Child response has no parent invocation")
            children.setdefault(invocation.parent_chat_message_id, []).append(row)
            visited.add(row.id)
            parents.append(row.id)
    return children


def read_chat_execution(message: ChatMessage) -> ChatExecutionRecord | None:
    if message.response_status is None or not record_mode_persists_content(
        message.chat_session.incognito_record_mode
    ):
        return None
    db_session = object_session(message)
    if db_session is None:
        raise ValueError("Response content must be loaded inside its database session")
    presentation: dict[str, MessageRendering] = {}
    tool_records: list[ToolRecordReference] = []
    children = _load_child_responses(db_session, message.id)

    def read(
        response: ChatMessage,
        agent_path: str,
        invoking_generation_id: str | None = None,
    ) -> ResponseRecord:
        record = read_response_record(
            response, agent_path, invoking_generation_id=invoking_generation_id
        )
        generation_ids = {
            item.step_index: item.id
            for item in response.response_items
            if item.kind == ResponseItemKind.GENERATION
        }
        generation_by_tool: dict[int, str] = {}
        for item in response.response_items:
            if item.rendering:
                presentation[item.id] = MessageRendering.model_validate(item.rendering)
            if item.kind == ResponseItemKind.TOOL_CALL and item.tool_call is not None:
                generation_by_tool[item.tool_call.id] = generation_ids[item.step_index]
                tool_records.append(
                    ToolRecordReference(
                        message_id=generation_ids[item.step_index],
                        tool_call_id=item.tool_call.tool_call_id,
                        record_id=item.tool_call.id,
                    )
                )
        for child in children.get(response.id, []):
            question = child.parent_message
            name = child.chat_session.agent_name
            if (
                question is None
                or question.invoking_tool_call_id is None
                or name is None
            ):
                raise ValueError("Child response has no invocation or agent name")
            record.child_runs.append(
                read(
                    child,
                    f"{agent_path}/{name}",
                    generation_by_tool[question.invoking_tool_call_id],
                )
            )
        return record

    root = read(message, agent_session_path(db_session, message.chat_session))
    return ChatExecutionRecord(
        response=root, presentation=presentation, tool_records=tool_records
    )


def _require_terminal_records(record: ResponseRecord) -> None:
    pending = [record]
    while pending:
        pending_record = pending.pop()
        if not pending_record.status.is_terminal:
            raise ValueError("Saving a response requires terminal execution records")
        pending.extend(pending_record.child_runs)


def save_response_content(
    message: ChatMessage,
    record: ResponseRecord | None,
    *,
    db_session: Session,
    persist_content: bool,
    presentation: dict[str, MessageRendering] | None = None,
) -> list[ToolRecordReference]:
    """Save accepted response content; the caller owns the transaction."""
    if record is None:
        return []
    _require_terminal_records(record)
    if not persist_content:
        message.response_status = record.status
        return []
    if (
        message.response_status is not None
        and message.response_status.is_terminal
        and message.run_id != record.run_id
    ):
        raise ValueError("Response content has already been saved")
    if record.agent_id != str(message.chat_session_id):
        raise ValueError("Root response must use its session identity")
    record = ResponseRecord.model_validate(
        sanitize_json_like(record.model_dump(mode="json"))
    )
    writer = _ResponseWriter(db_session, message, presentation or {})
    writer.store(record, None)
    if writer.presentation:
        raise ValueError("Display settings do not match response generations")
    db_session.flush()
    return [
        ToolRecordReference(message_id=key[0], tool_call_id=key[1], record_id=tool.id)
        for key, tool in writer.tools.items()
    ]


class _ResponseWriter:
    def __init__(
        self,
        db_session: Session,
        response: ChatMessage,
        presentation: dict[str, MessageRendering],
    ) -> None:
        self.db_session = db_session
        self.response = response
        self.branch_ids = visible_message_ids(db_session, response)
        self.sessions = {response.chat_session_id: response.chat_session}
        self.tools: dict[tuple[str, str], ToolCall] = {}
        self.presentation = dict(presentation)
        self.responses: dict[str, ChatMessage] = {}

    def store(
        self, record: ResponseRecord, parent: ChatMessage | None, depth: int = 0
    ) -> None:
        if depth > MAX_AGENT_DEPTH or len(self.responses) >= MAX_AGENT_HISTORY_RUNS:
            raise ValueError("Response hierarchy exceeds its limit")
        if record.agent_id is None or record.run_id in self.responses:
            raise ValueError("Execution identity is missing or repeated")
        if len(record.items) > MAX_CONVERSATION_MESSAGES:
            raise ValueError("Response exceeds its content limit")
        if len(record.input_messages) != 1 or not isinstance(
            record.input_messages[0], UserMessage
        ):
            raise ValueError("A saved chat response requires one user instruction")
        instruction = record.input_messages[0]
        if parent is None:
            response = self.response
            question = response.parent_message
            if question is None or question.message_type != MessageType.USER:
                raise ValueError("Root response has no question")
        else:
            response = self._child_response(record, parent, instruction)
        if response.run_id is not None and response.run_id != record.run_id:
            raise ValueError("Response belongs to another SDK run")
        response.run_id = record.run_id
        response.response_status = record.status
        response.response_failure = record.failure
        self.responses[record.run_id] = response
        self.tools.update(
            write_response_items(
                self.db_session,
                response,
                record.items,
                self.presentation,
            )
        )
        if parent is not None:
            response.message = "".join(
                item.content.value.text
                for item in response.response_items
                if item.content is not None
                and isinstance(item.content.value, ResponseText)
                and item.content.value.purpose == TextPurpose.ANSWER
            )
            response.token_count = count_tokens(response.message)
        if record.checkpoint is not None:
            previous_summary = find_summary_for_ancestry(
                self.db_session,
                response.chat_session_id,
                visible_message_ids(self.db_session, response),
            )
            if record.checkpoint != checkpoint_from_summary(previous_summary):
                checkpoint = record.checkpoint
                summary = ChatMessage(
                    chat_session_id=response.chat_session_id,
                    parent_message_id=response.id,
                    message_type=MessageType.SUMMARY,
                    message=checkpoint.summary,
                    token_count=count_tokens(checkpoint.summary),
                    summary_covered_count=checkpoint.covered_count,
                    summary_covered_digest=checkpoint.covered_digest,
                )
                self.db_session.add(summary)
                self.db_session.flush()
        for child in record.child_runs:
            self.store(child, response, depth + 1)

    def _child_response(
        self, record: ResponseRecord, parent: ChatMessage, instruction: UserMessage
    ) -> ChatMessage:
        if record.agent_id is None:
            raise ValueError("Child response has no agent identity")
        if not isinstance(instruction.content, str):
            raise ValueError("Saved child instructions must contain text only")
        invocation = self.tools.get(
            (record.parent_message_id or "", record.parent_tool_call_id or "")
        )
        if invocation is None or invocation.parent_chat_message_id != parent.id:
            raise ValueError("Child instruction has no parent invocation")
        session_id = UUID(record.agent_id)
        session = self.sessions.get(session_id) or self.db_session.get(
            ChatSession, session_id
        )
        if session is None:
            session = ChatSession(
                id=session_id,
                spawned_by_message_id=parent.id,
                agent_name=record.agent_path.rsplit("/", 1)[-1],
                description=record.agent_description,
                restoration_config=record.restoration_config,
            )
            self.db_session.add(session)
            self.db_session.flush()
        creation_response = (
            self.db_session.get(ChatMessage, session.spawned_by_message_id)
            if session.spawned_by_message_id is not None
            else None
        )
        if (
            creation_response is None
            or creation_response.chat_session_id != parent.chat_session_id
            or root_response_id(self.db_session, creation_response)
            not in self.branch_ids
        ):
            raise ValueError("Child session is unavailable on this branch")
        self.sessions[session.id] = session
        predecessor = self.responses.get(record.previous_run_id or "")
        if predecessor is None and record.previous_run_id:
            if record.previous_run_id.isdecimal():
                predecessor_id = int(record.previous_run_id)
            else:
                predecessor_id = self.db_session.scalar(
                    select(ChatMessage.id).where(
                        ChatMessage.run_id == record.previous_run_id
                    )
                )
                if predecessor_id is None:
                    raise ValueError("Child predecessor has no saved response")
            predecessor = self.db_session.get(ChatMessage, predecessor_id)
            if (
                predecessor is None
                or root_response_id(self.db_session, predecessor) not in self.branch_ids
            ):
                raise ValueError("Child predecessor is unavailable on this branch")
        if predecessor is not None and predecessor.chat_session_id != session.id:
            raise ValueError("Child predecessor belongs to another conversation")
        response = self.db_session.scalar(
            select(ChatMessage).where(ChatMessage.run_id == record.run_id)
        )
        if response is not None:
            if response.chat_session_id != session.id:
                raise ValueError("Saved response belongs to another agent")
            question = response.parent_message
            if question is None or question.invoking_tool_call_id != invocation.id:
                raise ValueError("Saved response belongs to another invocation")
        else:
            question = ChatMessage(
                chat_session_id=session.id,
                parent_message_id=predecessor.id if predecessor else None,
                invoking_tool_call_id=invocation.id,
                message=instruction.text,
                token_count=count_tokens(instruction.text),
                message_type=MessageType.USER,
            )
            self.db_session.add(question)
            self.db_session.flush()
            response = ChatMessage(
                chat_session_id=session.id,
                parent_message_id=question.id,
                message="",
                token_count=0,
                message_type=MessageType.ASSISTANT,
            )
            self.db_session.add(response)
            self.db_session.flush()
            question.latest_child_message_id = response.id
        return response
