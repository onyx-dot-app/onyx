import json
from uuid import UUID

from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session, aliased, joinedload, object_session, selectinload

from onyx.agents.compaction import count_tokens
from onyx.agents.execution_records import RunStatus, run_input_message_id
from onyx.agents.models import AgentInfo, StepRecord, ToolExecutionRecord
from onyx.chat.models import (
    ChatExecutionRecord,
    ChatResponseSnapshot,
    MessageRendering,
    ResponseRecord,
    ToolRecordReference,
)
from onyx.configs.constants import DocumentSource, MessageType
from onyx.context.search.models import SearchDoc
from onyx.db.chat import (
    MAX_AGENT_DEPTH,
    MAX_AGENT_HISTORY_RUNS,
    MAX_CONVERSATION_MESSAGES,
    add_search_docs_to_chat_message,
    add_search_docs_to_tool_call,
    agent_session_path,
    checkpoint_from_summary,
    create_db_search_doc,
    find_summary_for_ancestry,
    parent_session_id,
    root_response_id,
    visible_message_ids,
)
from onyx.db.engine.sql_engine import get_session_with_current_tenant
from onyx.db.enums import record_mode_persists_content
from onyx.db.models import (
    ChatMessage,
    ChatResponseCheckpoint,
    ChatResponseMessage,
    ChatSession,
    ToolCall,
)
from onyx.file_processing.file_types import guess_mime_type
from onyx.file_store.models import FileDescriptor
from onyx.llm.models import (
    GenerationRequestParams,
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
                mime_type = guess_mime_type(gen_file.filename)
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


def save_chat_response_to_db(
    *,
    message_id: int,
    chat_session_id: UUID,
    expected_persist_content: bool,
    response: ChatResponseSnapshot,
) -> str:
    """Save response rows under the session's recording policy and return the final answer."""
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
        if message.chat_session_id != chat_session_id:
            raise ValueError("Response belongs to another chat session")
        keeps_content = record_mode_persists_content(
            message.chat_session.incognito_record_mode
        )
        if keeps_content != expected_persist_content:
            raise ValueError(
                "Chat history store does not match the session recording mode"
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
    return answer


def _child_responses(db_session: Session, response_ids: list[int]) -> list[ChatMessage]:
    question = aliased(ChatMessage)
    return list(
        db_session.scalars(
            select(ChatMessage)
            .join(question, ChatMessage.parent_message_id == question.id)
            .join(ToolCall, question.invoking_tool_call_id == ToolCall.id)
            .join(
                ChatResponseMessage,
                (ChatResponseMessage.chat_message_id == ToolCall.parent_chat_message_id)
                & (ChatResponseMessage.step_index == ToolCall.turn_number),
            )
            .where(
                ChatResponseMessage.content.is_not(None),
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
                selectinload(ChatMessage.response_messages),
                selectinload(ChatMessage.tool_calls),
            )
            # Stable display order; predecessor links determine child history.
            .order_by(ChatResponseMessage.position, ChatMessage.id)
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
    # A child response must be linked through one of this message's tool calls.
    children = (
        _load_child_responses(db_session, message.id) if message.tool_calls else {}
    )

    def read(
        response: ChatMessage,
        agent_path: str,
        invoking_message_id: str | None = None,
    ) -> ResponseRecord:
        record = read_response_record(
            response, agent_path, invoking_message_id=invoking_message_id
        )
        message_ids_by_step = {
            row.step_index: row.id
            for row in response.response_messages
            if row.content is not None
        }
        message_ids_by_tool: dict[int, str] = {}
        for row in response.response_messages:
            if row.rendering:
                presentation[row.id] = MessageRendering.model_validate(row.rendering)
        for tool in response.tool_calls or []:
            assistant_message_id = message_ids_by_step[tool.turn_number]
            message_ids_by_tool[tool.id] = assistant_message_id
            tool_records.append(
                ToolRecordReference(
                    message_id=assistant_message_id,
                    tool_call_id=tool.tool_call_id,
                    record_id=tool.id,
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
                    message_ids_by_tool[question.invoking_tool_call_id],
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
        raise ValueError("Display settings do not match response messages")
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
        if len(record.messages) > MAX_CONVERSATION_MESSAGES:
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
            write_response_messages(
                self.db_session,
                response,
                record,
                self.presentation,
            )
        )
        if parent is not None:
            response.message = (
                record.steps[record.answer_step_index].message.text
                if record.answer_step_index is not None
                else ""
            )
            response.token_count = count_tokens(response.message)
        if record.checkpoint is not None and record.checkpoint.summary:
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
                    last_summarized_message_id=checkpoint.covered_through_message_id,
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


def read_response_steps(response: ChatMessage) -> list[StepRecord]:
    steps: list[StepRecord] = []
    tools = {
        (tool.turn_number, tool.tool_call_id): tool
        for tool in response.tool_calls or []
    }
    calls: dict[str, str] = {}
    for position, row in enumerate(response.response_messages):
        if row.position != position or row.chat_message_id != response.id:
            raise ValueError("Response message order or ownership is invalid")
        if row.content is not None:
            if row.content.id != row.id or row.step_index != len(steps):
                raise ValueError("Response assistant identity or step is invalid")
            if row.operation_status is None:
                raise ValueError("Assistant message has no operation outcome")
            step = StepRecord(
                message=row.content.model_copy(deep=True),
                generation_status=row.operation_status,
            )
            calls = {call.id: call.name for call in row.content.tool_calls}
            for call in row.content.tool_calls:
                tool = tools.get((row.step_index, call.id))
                if tool is None or tool.tool_name != call.name:
                    raise ValueError(
                        "Assistant tool call has no matching stored invocation"
                    )
                if tool.operation_status is not None:
                    step.tools[call.id] = ToolExecutionRecord(
                        status=tool.operation_status
                    )
            steps.append(step)
            continue
        tool = row.tool_call
        if (
            tool is None
            or tool.parent_chat_message_id != response.id
            or tool.turn_number != len(steps) - 1
            or row.step_index != len(steps) - 1
            or tool.tool_call_id not in calls
            or tool.result is None
            or tool.result.tool_call_id != tool.tool_call_id
            or tool.tool_name != calls.get(tool.tool_call_id)
            or tool.result.tool_name != tool.tool_name
            or tool.tool_call_id not in steps[-1].tools
        ):
            raise ValueError("Response tool result has no matching call")
        del calls[tool.tool_call_id]
        steps[-1].tools[tool.tool_call_id].result = tool.result.model_copy(deep=True)
    return steps


def _invoking_message_id(invocation: ToolCall) -> str:
    db_session = object_session(invocation)
    if db_session is None:
        raise ValueError("Tool invocation must be attached to its database session")
    row = db_session.scalar(
        select(ChatResponseMessage).where(
            ChatResponseMessage.chat_message_id == invocation.parent_chat_message_id,
            ChatResponseMessage.step_index == invocation.turn_number,
            ChatResponseMessage.content.is_not(None),
        )
    )
    if (
        row is None
        or row.content is None
        or invocation.tool_call_id not in {call.id for call in row.content.tool_calls}
    ):
        raise ValueError("Tool invocation has no assistant message")
    return row.id


def read_response_record(
    response: ChatMessage,
    agent_path: str,
    *,
    invoking_message_id: str | None = None,
) -> ResponseRecord:
    if response.response_status is None:
        raise ValueError("Response has no saved outcome")
    question = response.parent_message
    if (
        question is None
        or question.message_type != MessageType.USER
        or question.chat_session_id != response.chat_session_id
    ):
        raise ValueError("Response has no question in its conversation")
    invocation = question.invoking_tool_call
    input_id = f"chat:{question.id}"
    if invocation is not None:
        if response.run_id is None:
            raise ValueError("Child response has no run identity")
        input_id = run_input_message_id(response.run_id, 0)
    previous = question.parent_message
    if previous is not None and previous.response_status is None:
        previous = None
    parent_response_id = invocation.parent_chat_message_id if invocation else None
    return ResponseRecord(
        input_messages=[
            UserMessage(
                id=input_id,
                content=question.message,
            )
        ],
        steps=read_response_steps(response),
        answer_step_index=next(
            (row.step_index for row in response.response_messages if row.is_answer),
            None,
        ),
        status=response.response_status,
        failure=response.response_failure,
        agent_id=str(response.chat_session_id),
        agent_path=agent_path,
        agent_description=response.chat_session.description or ""
        if response.chat_session.spawned_by_message_id is not None
        else "",
        restoration_config=response.chat_session.restoration_config,
        run_id=str(response.id),
        previous_run_id=str(previous.id) if previous else None,
        parent_run_id=str(parent_response_id) if parent_response_id else None,
        parent_tool_call_id=invocation.tool_call_id if invocation else None,
        parent_message_id=(invoking_message_id or _invoking_message_id(invocation))
        if invocation
        else None,
    )


def write_response_messages(
    db_session: Session,
    response: ChatMessage,
    record: ResponseRecord,
    presentation: dict[str, MessageRendering],
) -> dict[tuple[str, str], ToolCall]:
    """Store message content and invocation records; the caller owns the transaction."""
    tools: dict[tuple[str, str], ToolCall] = {}
    existing = {row.id: row for row in response.response_messages}
    stored_tools = {
        (tool.turn_number, tool.tool_call_id): tool
        for tool in response.tool_calls or []
    }
    incoming_ids: set[str] = set()
    next_position = len(existing)
    if record.answer_step_index is not None and not (
        0 <= record.answer_step_index < len(record.steps)
    ):
        raise ValueError("Selected answer is not a recorded step")

    def message_row(message_id: str, step_index: int) -> ChatResponseMessage:
        nonlocal next_position
        if message_id in incoming_ids:
            raise ValueError("Response contains duplicate message identities")
        incoming_ids.add(message_id)
        row = existing.get(message_id) or ChatResponseMessage(
            id=message_id,
            chat_message_id=response.id,
            position=next_position,
            step_index=step_index,
        )
        if row.chat_message_id != response.id or row.step_index != step_index:
            raise ValueError("Response message identity or order changed")
        if message_id not in existing:
            # Resumed tools append rows; model order comes from the assistant's calls.
            next_position += 1
            response.response_messages.append(row)
        return row

    response_tools = response.tool_calls
    if response_tools is None:
        response_tools = []
        response.tool_calls = response_tools
    for step_index, step in enumerate(record.steps):
        message = step.message
        message_id = message.id
        if message_id is None:
            raise ValueError("Saved assistant message has no identity")
        row = message_row(message_id, step_index)
        row.content = message
        row.operation_status = step.generation_status
        row.is_answer = step_index == record.answer_step_index
        setting = presentation.pop(message_id, None)
        if setting is not None:
            row.rendering = setting.model_dump(mode="json")
        if step.tools.keys() - {call.id for call in message.tool_calls}:
            raise ValueError("Tool execution has no call in its assistant message")
        for call in message.tool_calls:
            key = (message_id, call.id)
            if key in tools:
                raise ValueError("Duplicate tool call within one assistant message")
            execution = step.tools.get(call.id)
            tool = stored_tools.get((step_index, call.id)) or ToolCall(
                chat_session_id=response.chat_session_id,
                parent_chat_message_id=response.id,
                turn_number=step_index,
                tab_index=len(tools),
                tool_id=None,
                tool_call_id=call.id,
                tool_name=call.name,
                tool_call_arguments=call.arguments,
                argument_error=call.argument_error,
                raw_arguments=call.raw_arguments,
                arguments_complete=call.arguments_complete,
                tool_call_tokens=count_tokens(json.dumps(call.arguments)),
                tool_call_response="",
            )
            tool.tool_call_arguments = call.arguments
            tool.argument_error = call.argument_error
            tool.raw_arguments = call.raw_arguments
            tool.arguments_complete = call.arguments_complete
            tool.operation_status = execution.status if execution is not None else None
            if (step_index, call.id) not in stored_tools:
                response_tools.append(tool)
            db_session.add(tool)
            tools[key] = tool
            if execution is not None and execution.result is not None:
                result = execution.result
                if result.tool_call_id != call.id or result.tool_name != call.name:
                    raise ValueError("Tool result does not match its invocation")
                tool.result = result
                result_row = message_row(f"{message_id}:result:{call.id}", step_index)
                result_row.tool_call = tool
                result_row.is_answer = False
    if existing.keys() - incoming_ids:
        raise ValueError("Response update cannot discard recorded messages")
    db_session.flush()
    return tools


def finish_checkpoint__no_commit(session: Session, message_id: int) -> None:
    row = session.get(ChatResponseCheckpoint, message_id)
    if row is not None:
        session.delete(row)


class SavedResponse(BaseModel):
    message_id: int
    root_message_id: int
    root_session_id: UUID
    agent: AgentInfo
    response: ResponseRecord


class ResponseStatus(BaseModel):
    message_id: int
    run_id: str
    root_message_id: int
    root_session_id: UUID
    parent_agent_id: str | None
    status: RunStatus


class _ResponseAncestry(BaseModel):
    message_id: int
    run_id: str | None
    session_id: UUID
    status: RunStatus | None
    spawned_by_message_id: int | None
    parent_session_id: UUID | None
    parent_response_id: int | None


def _read_response_ancestry(session: Session, run_id: str) -> _ResponseAncestry | None:
    question = aliased(ChatMessage)
    spawning_response = aliased(ChatMessage)
    predicate = (
        ChatMessage.id == int(run_id)
        if run_id.isdecimal()
        else ChatMessage.run_id == run_id
    )
    row = (
        session.execute(
            select(
                ChatMessage.id.label("message_id"),
                ChatMessage.run_id,
                ChatMessage.chat_session_id.label("session_id"),
                ChatMessage.response_status.label("status"),
                ChatSession.spawned_by_message_id,
                spawning_response.chat_session_id.label("parent_session_id"),
                ToolCall.parent_chat_message_id.label("parent_response_id"),
            )
            .join(ChatSession, ChatSession.id == ChatMessage.chat_session_id)
            .outerjoin(question, question.id == ChatMessage.parent_message_id)
            .outerjoin(ToolCall, ToolCall.id == question.invoking_tool_call_id)
            .outerjoin(
                spawning_response,
                spawning_response.id == ChatSession.spawned_by_message_id,
            )
            .where(predicate)
        )
        .mappings()
        .one_or_none()
    )
    return _ResponseAncestry.model_validate(row) if row is not None else None


def read_response_status__no_commit(
    session: Session, run_id: str
) -> ResponseStatus | None:
    """Read status and authorization identities without loading conversation content."""
    response = _read_response_ancestry(session, run_id)
    if response is None or response.status is None:
        return None
    current = response
    visited: set[int] = set()
    while current.spawned_by_message_id is not None:
        if current.message_id in visited or len(visited) >= MAX_AGENT_DEPTH:
            raise ValueError("Child response hierarchy is cyclic or too deep")
        visited.add(current.message_id)
        if current.parent_session_id is None or current.parent_response_id is None:
            raise ValueError("Child response is missing its invocation or parent")
        parent = _read_response_ancestry(session, str(current.parent_response_id))
        if parent is None:
            raise ValueError("Parent response is unavailable")
        current = parent
    return ResponseStatus(
        message_id=response.message_id,
        run_id=response.run_id or str(response.message_id),
        root_message_id=current.message_id,
        root_session_id=current.session_id,
        parent_agent_id=str(response.parent_session_id)
        if response.parent_session_id is not None
        else None,
        status=response.status,
    )


def find_response__no_commit(session: Session, run_id: str) -> ChatMessage | None:
    predicate = (
        ChatMessage.id == int(run_id)
        if run_id.isdecimal()
        else ChatMessage.run_id == run_id
    )
    return session.scalar(
        select(ChatMessage)
        .where(predicate)
        .options(
            selectinload(ChatMessage.response_messages),
            selectinload(ChatMessage.tool_calls),
        )
    )


def read_response__no_commit(session: Session, run_id: str) -> SavedResponse | None:
    response = find_response__no_commit(session, run_id)
    if response is None or response.response_status is None:
        return None
    root_id = root_response_id(session, response)
    root = session.get(ChatMessage, root_id)
    if root is None:
        raise ValueError("Response root is missing")
    agent = response.chat_session
    parent_id = parent_session_id(session, agent)
    path = agent_session_path(session, agent)
    record = read_response_record(response, path)
    record.checkpoint = checkpoint_from_summary(
        find_summary_for_ancestry(
            session, response.chat_session_id, visible_message_ids(session, response)
        )
    )
    record.run_id = response.run_id or str(response.id)
    if record.previous_run_id is not None:
        previous = session.get(ChatMessage, int(record.previous_run_id))
        if previous is None:
            raise ValueError("Previous response is unavailable")
        record.previous_run_id = previous.run_id or str(previous.id)
    if record.parent_run_id is not None:
        parent = session.get(ChatMessage, int(record.parent_run_id))
        if parent is None:
            raise ValueError("Parent response is unavailable")
        record.parent_run_id = parent.run_id or str(parent.id)
    return SavedResponse(
        message_id=response.id,
        root_message_id=root_id,
        root_session_id=root.chat_session_id,
        agent=AgentInfo(
            id=str(agent.id),
            parent_id=str(parent_id) if parent_id else None,
            path=path,
            description=agent.description or "",
            restoration_config=agent.restoration_config,
            latest_run_id=record.run_id,
            status=record.status,
        ),
        response=record,
    )


def save_response_record__no_commit(
    session: Session,
    root_message_id: int,
    record: ResponseRecord,
) -> int:
    configure_response_transaction__no_commit(session)
    record = ResponseRecord.model_validate(
        sanitize_json_like(record.model_dump(mode="json"))
    )
    root = session.get(ChatMessage, root_message_id)
    if root is None:
        raise ValueError("Response root is unavailable")
    parent = None
    if record.parent_run_id is not None:
        parent = find_response__no_commit(session, record.parent_run_id)
        if parent is None or root_response_id(session, parent) != root.id:
            raise ValueError("Parent response is unavailable on this branch")
    writer = _ResponseWriter(session, root, {})
    if parent is not None:
        message_ids_by_step = {
            row.step_index: row.id
            for row in parent.response_messages
            if row.content is not None
        }
        for tool in parent.tool_calls or []:
            assistant_message_id = message_ids_by_step.get(tool.turn_number)
            if assistant_message_id is None:
                raise ValueError("Parent tool call has no assistant message")
            writer.tools[(assistant_message_id, tool.tool_call_id)] = tool
    writer.store(record, parent)
    session.flush()
    return writer.responses[record.run_id].id
