import json
from collections.abc import Collection, Mapping
from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import Integer, column, delete, exists, func, inspect, select, values
from sqlalchemy.orm import Session, aliased, joinedload, object_session, selectinload

from onyx.agents.compaction import count_tokens, is_input_context
from onyx.agents.execution_records import run_input_message_id
from onyx.agents.models import (
    AgentInfo,
    InputMessageMetadata,
    InputSource,
    RunFailureKind,
    RunStatus,
    StepRecord,
    ToolExecutionRecord,
    agent_result_message_id,
)
from onyx.chat.mention_models import PickedSkillMessage
from onyx.chat.models import (
    AgentToolApproval,
    ChatApprovals,
    ChatExecutionRecord,
    ChatResponseSnapshot,
    MessageRendering,
    PromptMetadata,
    ResponseRecord,
    ResponseReplayData,
    ResponseStatus,
    SavedResponse,
    SavedToolApproval,
    SavedToolQuestion,
    ToolRecordReference,
    ToolReplayData,
    accepted_input_messages,
    read_message_rendering,
    recorded_mentions,
    skill_message_id,
)
from onyx.chat.response import restore_response_sources
from onyx.configs.constants import DocumentSource, MessageType
from onyx.context.search.models import SearchDoc
from onyx.db.chat import (
    MAX_AGENT_DEPTH,
    MAX_AGENT_HISTORY_RUNS,
    MAX_CONVERSATION_MESSAGES,
    add_search_docs_to_chat_message,
    add_search_docs_to_tool_call,
    agent_ancestor_chain,
    agent_session_path,
    checkpoint_from_summary,
    configure_response_transaction__no_commit,
    create_db_search_doc,
    find_summary_for_ancestry,
    ownership_root_id,
    parent_session_id,
    response_invocation,
    response_invocation_chain,
    response_on_branch,
    root_response_id,
    session_ancestors,
    translate_db_search_doc_to_saved_search_doc,
    visible_message_ids,
)
from onyx.db.engine.sql_engine import get_session_with_current_tenant
from onyx.db.enums import record_mode_persists_content
from onyx.db.models import (
    AcceptedChatInput,
    ApprovalRequest,
    ChatInput,
    ChatMessage,
    ChatResponseCheckpoint,
    ChatResponseItem,
    ChatSession,
    Integration,
    QuestionRequest,
    StoredToolResult,
    ToolCall,
    UnavailableStoredToolResult,
)
from onyx.db.question_request import get_response_question_requests
from onyx.file_processing.file_types import guess_mime_type
from onyx.file_store.models import FileDescriptor
from onyx.file_store.staging import delete_files_best_effort
from onyx.llm.models import (
    GenerationRequestParams,
    Message,
    UserMessage,
)
from onyx.llm.models import ToolCall as ModelToolCall
from onyx.natural_language_processing.utils import get_tokenizer
from onyx.server.query_and_chat.chat_utils import mime_type_to_chat_file_type
from onyx.tools.models import ToolCallInfo
from onyx.tools.tool_implementations.subagents.shapes import (
    AGENT_START_TOOL_NAMES,
)
from onyx.utils.logger import setup_logger
from onyx.utils.postgres_sanitization import sanitize_json_like, sanitize_string

logger = setup_logger()
# The context of logs about the parked programs' dumps that checkpoints owned.
CHECKPOINT_DUMP_CLEANUP = "parked program dumps"


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
        record.tool_id = info.tool_id
        record.turn_number = info.turn_index
        record.tab_index = info.tab_index
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
                dict.fromkeys(search_doc_ids_for_tool)
            )

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

        # Build mapping from citation number to search doc ID
        citation_number_to_search_doc_id[citation_num] = db_search_doc_id

    # History restoration resolves citations through the response's sources.
    final_search_doc_ids = list(set(search_doc_key_to_id.values()))
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

    # Preserve referenced generated files for subsequent turns; unreferenced
    # ones remain intermediate artifacts. Published files are files of the
    # message; the chat delete finds them through their artifacts either
    # way. A terminal save can repeat, so a file already listed is not
    # added again.
    attached = [
        *(
            _extract_referenced_file_descriptors(tool_calls, sanitized_message_text)
            if sanitized_message_text
            else []
        ),
        *(
            FileDescriptor(
                id=file.file_id,
                type=mime_type_to_chat_file_type(file.mime_type),
                name=file.name,
            )
            for tool_call_info in tool_calls
            for file in tool_call_info.published_files or []
        ),
    ]
    existing_files = assistant_message.files or []
    listed = {file["id"] for file in existing_files}
    new_files = list(
        {file["id"]: file for file in attached if file["id"] not in listed}.values()
    )
    if new_files:
        assistant_message.files = existing_files + new_files

    db_session.commit()


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
        deadline = (
            response.response is not None
            and response.response.failure is not None
            and response.response.failure.kind == RunFailureKind.DEADLINE
        )
        reason = (
            "The response stopped because it reached its time limit."
            if deadline
            else "Generation was stopped by the user."
        )
        answer = ((response.answer + " ... \n\n") if response.answer else "") + reason
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
        dumps = finish_checkpoint__no_commit(session, message_id)
        processing_time = response.pre_answer_processing_time
        # A run stopped before its answer has no answer start; it worked
        # until the stop, so keep that time for the stopped header.
        if response.cancelled and processing_time is None:
            processing_time = max(
                0.0,
                (datetime.now(timezone.utc) - message.time_sent).total_seconds(),
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
            pre_answer_processing_time=processing_time,
            persist_content=keeps_content,
            response_record=response.response,
            presentation=response.presentation,
        )
    delete_files_best_effort(dumps, CHECKPOINT_DUMP_CLEANUP)
    return answer


def _child_responses(
    db_session: Session, root_by_parent: dict[int, int]
) -> list[ChatMessage]:
    question = aliased(ChatMessage)
    parents = values(
        column("parent_id", Integer), column("root_id", Integer), name="parents"
    ).data(list(root_by_parent.items()))
    ranked = (
        select(
            ChatMessage.id,
            ChatResponseItem.step_index,
            func.row_number()
            .over(
                partition_by=parents.c.root_id,
                order_by=(ChatResponseItem.step_index, ChatMessage.id),
            )
            .label("rank"),
        )
        .join(question, ChatMessage.parent_message_id == question.id)
        .join(ToolCall, question.invoking_tool_call_id == ToolCall.id)
        .join(parents, ToolCall.parent_chat_message_id == parents.c.parent_id)
        .join(
            ChatResponseItem,
            (ChatResponseItem.chat_message_id == ToolCall.parent_chat_message_id)
            & (ChatResponseItem.step_index == ToolCall.turn_number),
        )
        .where(ChatMessage.response_status.is_not(None))
        .subquery()
    )
    return list(
        db_session.scalars(
            select(ChatMessage)
            .join(ranked, ranked.c.id == ChatMessage.id)
            # Each root reads at most one run past its limit, to detect it.
            .where(ranked.c.rank <= MAX_AGENT_HISTORY_RUNS + 1)
            .options(
                joinedload(ChatMessage.chat_session),
                joinedload(ChatMessage.parent_message).joinedload(
                    ChatMessage.invoking_tool_call
                ),
                selectinload(ChatMessage.response_items),
                # The replay reads these tool calls' search docs.
                selectinload(ChatMessage.tool_calls).selectinload(ToolCall.search_docs),
            )
            # Stable display order; predecessor links determine child history.
            .order_by(ranked.c.step_index, ChatMessage.id)
        )
    )


def load_child_responses(
    db_session: Session, responses: Collection[ChatMessage]
) -> dict[int, list[ChatMessage]]:
    """The child responses of `responses`' response trees, by parent response.
    Each hierarchy level of all trees loads together; each tree keeps its own
    run limit."""
    children: dict[int, list[ChatMessage]] = {}
    # A child response must be linked through one of its parent's tool calls.
    root_by_response = {
        response.id: response.id for response in responses if response.tool_calls
    }
    run_counts = dict.fromkeys(root_by_response, 1)
    parents = dict(root_by_response)
    # Messages between agents add levels, so the run count bounds the walk.
    while parents:
        rows = _child_responses(db_session, parents)
        parents = {}
        for row in rows:
            invocation = response_invocation(row)
            if invocation is None or invocation.parent_chat_message_id is None:
                raise ValueError("Child response has no parent invocation")
            root_id = root_by_response[invocation.parent_chat_message_id]
            if run_counts[root_id] >= MAX_AGENT_HISTORY_RUNS or (
                row.id in root_by_response
            ):
                raise ValueError(
                    "Response hierarchy exceeds its limit or contains a cycle"
                )
            if isinstance(invocation.result, UnavailableStoredToolResult):
                continue
            children.setdefault(invocation.parent_chat_message_id, []).append(row)
            run_counts[root_id] += 1
            root_by_response[row.id] = root_id
            parents[row.id] = root_id
    return children


def read_chat_execution(
    message: ChatMessage, child_responses: Mapping[int, list[ChatMessage]]
) -> tuple[ChatExecutionRecord, dict[int, ToolCall]] | None:
    """The saved execution of `message` and the tool call rows that its tool
    records reference, by record id. `child_responses` holds the child
    responses of responses that include this one (`load_child_responses`)."""
    if message.response_status is None or not record_mode_persists_content(
        message.chat_session.incognito_record_mode
    ):
        return None
    db_session = object_session(message)
    if db_session is None:
        raise ValueError("Response content must be loaded inside its database session")
    presentation: dict[str, MessageRendering] = {}
    tool_records: list[ToolRecordReference] = []
    tool_calls: dict[int, ToolCall] = {}

    def read(
        response: ChatMessage,
        agent_path: str,
        invoking_message_id: str | None = None,
    ) -> ResponseRecord:
        record = read_response_record(
            response, agent_path, invoking_message_id=invoking_message_id
        )
        message_ids_by_step = {
            row.step_index: row.id for row in response.response_items
        }
        message_ids_by_tool: dict[int, str] = {}
        for row in response.response_items:
            if row.rendering:
                presentation[row.id] = read_message_rendering(row.rendering)
        for tool in response.tool_calls or []:
            if isinstance(tool.result, UnavailableStoredToolResult):
                continue
            assistant_message_id = message_ids_by_step[tool.turn_number]
            message_ids_by_tool[tool.id] = assistant_message_id
            tool_calls[tool.id] = tool
            tool_records.append(
                ToolRecordReference(
                    message_id=assistant_message_id,
                    tool_call_id=tool.tool_call_id,
                    record_id=tool.id,
                )
            )
        for child in child_responses.get(response.id, []):
            invocation = response_invocation(child)
            name = child.chat_session.agent_name
            if invocation is None or name is None:
                raise ValueError("Child response has no invocation or agent name")
            record.child_runs.append(
                read(
                    child,
                    f"{agent_path}/{name}",
                    message_ids_by_tool[invocation.id],
                )
            )
        return record

    root = read(message, agent_session_path(db_session, message.chat_session))
    return (
        ChatExecutionRecord(
            response=root, presentation=presentation, tool_records=tool_records
        ),
        tool_calls,
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
    if record.agent_id != str(message.chat_session_id):
        raise ValueError("Root response must use its session identity")
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
        if not record_mode_persists_content(
            response.chat_session.incognito_record_mode
        ):
            raise ValueError("Content-free sessions cannot store response records")
        self.db_session = db_session
        self.response = response
        self.branch_ids = visible_message_ids(db_session, response)
        self.tools: dict[tuple[str, str], ToolCall] = {}
        self.presentation = dict(presentation)
        self.seen_response_ids: set[int] = set()

    def store(
        self, record: ResponseRecord, parent: ChatMessage | None, depth: int = 0
    ) -> None:
        if (
            depth > MAX_AGENT_DEPTH
            or len(self.seen_response_ids) >= MAX_AGENT_HISTORY_RUNS
        ):
            raise ValueError("Response hierarchy exceeds its limit")
        if record.agent_id is None or int(record.run_id) in self.seen_response_ids:
            raise ValueError("Execution identity is missing or repeated")
        if len(record.messages) > MAX_CONVERSATION_MESSAGES:
            raise ValueError("Response exceeds its content limit")
        if parent is None:
            response = self.response
            question = response.parent_message
            if question is None or question.message_type not in (
                MessageType.USER,
                MessageType.AGENT_RESULTS,
            ):
                raise ValueError("Response has no question")
        else:
            response = self._child_response(record, parent)
        if str(response.id) != record.run_id:
            raise ValueError("Response identity does not match its reserved message")
        response.response_status = record.status
        response.response_failure = record.failure
        self.seen_response_ids.add(response.id)
        self.tools.update(
            write_response_items(
                self.db_session,
                response,
                record,
                self.presentation,
            )
        )
        if parent is not None:
            response.message = (
                sanitize_string(record.steps[record.answer_step_index].message.text)
                if record.answer_step_index is not None
                else ""
            )
            response.token_count = count_tokens(response.message)
        if record.checkpoint is not None:
            checkpoint = record.checkpoint.model_copy(
                update={
                    "summary": sanitize_string(record.checkpoint.summary),
                    "covered_through_message_id": sanitize_string(
                        record.checkpoint.covered_through_message_id
                    ),
                }
            )
            previous_summary = find_summary_for_ancestry(
                self.db_session,
                response.chat_session_id,
                visible_message_ids(self.db_session, response),
            )
            if checkpoint != checkpoint_from_summary(previous_summary):
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
        self, record: ResponseRecord, parent: ChatMessage
    ) -> ChatMessage:
        if record.agent_id is None:
            raise ValueError("Child response has no agent identity")
        invocation = self.tools.get(
            (record.parent_message_id or "", record.parent_tool_call_id or "")
        )
        if invocation is None or invocation.parent_chat_message_id != parent.id:
            raise ValueError("Child instruction has no parent invocation")
        response = find_response__no_commit(self.db_session, int(record.run_id))
        if response is None:
            raise ValueError("Child response was not reserved")
        if response.chat_session_id != UUID(record.agent_id):
            raise ValueError("Saved response belongs to another agent")
        question = response.parent_message
        if question is None or response_invocation(response) != invocation:
            raise ValueError("Saved response belongs to another invocation")
        if question.message_type == MessageType.USER:
            if len(record.input_messages) != 1 or not isinstance(
                record.input_messages[0], UserMessage
            ):
                raise ValueError("A saved child instruction requires one user message")
            if not isinstance(record.input_messages[0].content, str):
                raise ValueError("Saved child instructions must contain text only")
        elif record.input_messages:
            raise ValueError("A follow-up response accepts results through its steps")
        creation_id = response.chat_session.spawned_by_message_id
        creation_response = (
            self.db_session.get(ChatMessage, creation_id)
            if creation_id is not None
            else None
        )
        if creation_response is None or not response_on_branch(
            self.db_session, creation_response, self.branch_ids
        ):
            raise ValueError("Child session is unavailable on this branch")
        if question.parent_message_id != (
            int(record.previous_run_id) if record.previous_run_id else None
        ):
            raise ValueError("Saved response belongs to another predecessor")
        return response


def reserve_child_response__no_commit(
    session: Session,
    root_message_id: int,
    *,
    agent: AgentInfo,
    instruction: UserMessage | None,
    previous_response_id: int | None,
    parent_response_id: int,
    parent_message_id: str,
    parent_tool_call_id: str,
    delivers_result: bool,
) -> int:
    """Reserve a running child question and response; caller commits.

    Without an instruction, the question is a hidden AGENT_RESULTS message whose
    response receives unread results. With `delivers_result`, the response also
    gets the result inbox row of its spawner. `root_message_id` can be newer than
    the invocation's root when the run continues a predecessor from a later turn.
    """
    configure_response_transaction__no_commit(session)
    root = session.get(ChatMessage, root_message_id)
    parent = find_response__no_commit(session, parent_response_id)
    if root is None or parent is None:
        raise ValueError("Parent response is unavailable on this branch")
    branch_ids = visible_message_ids(session, root)
    if not response_on_branch(session, parent, branch_ids):
        raise ValueError("Parent response is unavailable on this branch")
    if not record_mode_persists_content(root.chat_session.incognito_record_mode):
        raise ValueError("Content-free sessions cannot reserve durable child responses")
    if instruction is not None and not isinstance(instruction.content, str):
        raise ValueError("Saved child instructions must contain text only")
    if instruction is None and previous_response_id is None:
        raise ValueError("A follow-up response requires a previous response")
    generation = next(
        (row for row in parent.response_items if row.id == parent_message_id),
        None,
    )
    invocation = next(
        (
            tool
            for tool in parent.tool_calls or []
            if generation is not None
            and tool.turn_number == generation.step_index
            and tool.tool_call_id == parent_tool_call_id
        ),
        None,
    )
    if invocation is None:
        raise ValueError("Child instruction has no parent invocation")
    child_session = session.get(ChatSession, UUID(agent.id))
    if child_session is None:
        if agent.parent_id != str(parent.chat_session_id):
            raise ValueError("Child agent belongs to another parent")
        child_session = ChatSession(
            id=UUID(agent.id),
            spawned_by_message_id=parent.id,
            user_id=root.chat_session.user_id,
            persona_id=root.chat_session.persona_id,
            onyxbot_flow=root.chat_session.onyxbot_flow,
            incognito_record_mode=root.chat_session.incognito_record_mode,
            agent_name=sanitize_string(agent.path.rsplit("/", 1)[-1]),
            description=sanitize_string(agent.description),
            restoration_config=agent.restoration_config,
        )
        session.add(child_session)
        session.flush()
    creation_response = (
        session.get(ChatMessage, child_session.spawned_by_message_id)
        if child_session.spawned_by_message_id is not None
        else None
    )
    # Any agent in the visible tree can start a run of an existing child.
    if creation_response is None or not response_on_branch(
        session, creation_response, branch_ids
    ):
        raise ValueError("Child session is unavailable on this branch")
    predecessor = None
    if previous_response_id is not None:
        predecessor = find_response__no_commit(session, previous_response_id)
        if (
            predecessor is None
            or predecessor.chat_session_id != child_session.id
            or not response_on_branch(session, predecessor, branch_ids)
        ):
            raise ValueError("Child predecessor is unavailable on this branch")
        if (
            predecessor.response_status is None
            or not predecessor.response_status.is_terminal
        ):
            raise ValueError("Child predecessor has not finished")
    instruction_text = sanitize_string(instruction.text) if instruction else ""
    question = ChatMessage(
        chat_session_id=child_session.id,
        parent_message_id=predecessor.id if predecessor else None,
        invoking_tool_call_id=invocation.id,
        message=instruction_text,
        token_count=count_tokens(instruction_text),
        message_type=MessageType.USER if instruction else MessageType.AGENT_RESULTS,
    )
    session.add(question)
    session.flush()
    # The caller commits the running response together with its execution lease.
    response = ChatMessage(
        chat_session_id=child_session.id,
        parent_message_id=question.id,
        message="",
        token_count=0,
        message_type=MessageType.ASSISTANT,
        response_status=RunStatus.RUNNING,
        # A child runs on its spawner's model
        model_display_name=parent.model_display_name,
    )
    session.add(response)
    session.flush()
    question.latest_child_message_id = response.id
    if delivers_result:
        # Results go to the spawner, whichever agent started this run.
        session.add(
            ChatInput(
                recipient_session_id=creation_response.chat_session_id,
                message_id=agent_result_message_id(str(response.id)),
                source=InputSource.AGENT_RESULT,
                source_response_id=response.id,
                root_response_id=root.id,
                content="",
            )
        )
        session.flush()
    return response.id


def abort_response_start__no_commit(
    session: Session, root_message_id: int, response_id: int
) -> None:
    """Undo an unused reservation; caller holds its ownership lock."""
    configure_response_transaction__no_commit(session)
    response = find_response__no_commit(session, response_id)
    if (
        response is None
        or response.response_status not in (None, RunStatus.RUNNING)
        or response.response_items
        or session.get(ChatResponseCheckpoint, response.id) is not None
    ):
        return
    branch = session.get(ChatMessage, root_message_id)
    root_id = root_response_id(session, response)
    root = session.get(ChatMessage, root_id)
    if (
        branch is None
        or root is None
        or root.chat_session_id != branch.chat_session_id
        or root_id not in visible_message_ids(session, branch)
    ):
        raise ValueError("Response is unavailable on this branch")
    if response.id == root_id:
        response.response_status = None
        return
    question = response.parent_message
    if question is None or response_invocation(response) is None:
        raise ValueError("Child response has no invocation")
    child_session_id = response.chat_session_id
    session.execute(
        delete(ChatMessage).where(ChatMessage.id.in_([response.id, question.id]))
    )
    session.execute(
        delete(ChatSession).where(
            ChatSession.id == child_session_id,
            ~select(ChatMessage.id)
            .where(ChatMessage.chat_session_id == child_session_id)
            .exists(),
        )
    )


def read_response_steps(response: ChatMessage) -> list[StepRecord]:
    steps: list[StepRecord] = []
    tools = {
        (tool.turn_number, tool.tool_call_id): tool
        for tool in response.tool_calls or []
    }
    # Assistant call order determines result order, not tool completion order.
    for row in sorted(response.response_items, key=lambda row: row.step_index):
        if row.chat_message_id != response.id:
            raise ValueError("Response item ownership is invalid")
        if row.message.id != row.id or row.step_index != len(steps):
            raise ValueError("Response assistant identity or step is invalid")
        step = StepRecord(
            input_messages=[
                message
                for item in row.inputs
                for message in accepted_input_messages(
                    message_id=item.id,
                    content=item.content,
                    source=item.source,
                    source_run_id=item.source_run_id,
                    mentions=item.mentions,
                    skill_messages=item.skill_messages,
                )
            ],
            message=row.message.model_copy(deep=True),
            generation_status=row.generation_status,
        )
        for call in row.message.tool_calls:
            tool = tools.pop((row.step_index, call.id), None)
            if tool is None or tool.parent_chat_message_id != response.id:
                raise ValueError(
                    "Assistant tool call has no matching stored invocation"
                )
            result = tool.result
            if result is not None and (
                tool.operation_status is None
                or result.tool_call_id != call.id
                or result.tool_name != call.name
            ):
                raise ValueError("Response tool result has no matching call")
            if isinstance(result, UnavailableStoredToolResult):
                step.message.content = [
                    part
                    for part in step.message.content
                    if not (isinstance(part, ModelToolCall) and part.id == call.id)
                ]
                continue
            if tool.operation_status is not None:
                step.tools[call.id] = ToolExecutionRecord(
                    status=tool.operation_status,
                    result=result.model_copy(deep=True) if result is not None else None,
                    display_name=tool.display_name,
                )
        steps.append(step)
    if any(tool.result is not None for tool in tools.values()):
        raise ValueError("Response tool result has no matching call")
    return steps


def _invoking_message_id(invocation: ToolCall) -> str:
    db_session = object_session(invocation)
    if db_session is None:
        raise ValueError("Tool invocation must be attached to its database session")
    row = db_session.scalar(
        select(ChatResponseItem).where(
            ChatResponseItem.chat_message_id == invocation.parent_chat_message_id,
            ChatResponseItem.step_index == invocation.turn_number,
        )
    )
    if row is None or invocation.tool_call_id not in {
        call.id for call in row.message.tool_calls
    }:
        raise ValueError("Tool invocation has no assistant message")
    return row.id


def _accepted_inputs(messages: list[UserMessage]) -> list[AcceptedChatInput]:
    # A picked skill's message is saved with the input that picked it.
    skills = {message.id: message for message in messages if is_input_context(message)}
    inputs: list[AcceptedChatInput] = []
    for message in messages:
        if is_input_context(message):
            continue
        if message.id is None or not isinstance(message.content, str):
            raise ValueError("Saved response inputs require an identity and text")
        origin = message.metadata
        mentions = recorded_mentions(message)
        skill_messages: list[PickedSkillMessage] = []
        for mention in mentions:
            skill = skills.get(skill_message_id(message.id, mention.version_id))
            if (
                skill is None
                or not isinstance(skill.metadata, PromptMetadata)
                or skill.metadata.token_count is None
            ):
                raise ValueError("Each picked skill needs its skill message")
            skill_messages.append(
                PickedSkillMessage(
                    version_id=mention.version_id,
                    content=sanitize_string(skill.text),
                    token_count=skill.metadata.token_count,
                )
            )
        inputs.append(
            AcceptedChatInput(
                id=sanitize_string(message.id),
                source=origin.source
                if isinstance(origin, InputMessageMetadata)
                else InputSource.HUMAN,
                source_run_id=origin.source_run_id
                if isinstance(origin, InputMessageMetadata)
                else None,
                content=sanitize_string(message.content),
                mentions=mentions,
                skill_messages=skill_messages,
            )
        )
    if len({item.id for item in inputs}) != len(inputs):
        raise ValueError("Received input identity is repeated")
    return inputs


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
        or question.message_type not in (MessageType.USER, MessageType.AGENT_RESULTS)
        or question.chat_session_id != response.chat_session_id
    ):
        raise ValueError("Response has no question in its conversation")
    invocation = question.invoking_tool_call
    inputs: list[Message] = []
    if question.message_type == MessageType.USER:
        inputs.append(
            UserMessage(
                id=run_input_message_id(str(response.id), 0)
                if invocation
                else f"chat:{question.id}",
                content=question.message,
            )
        )
    previous = question.parent_message
    if previous is not None and previous.response_status is None:
        previous = None
    parent_response_id = invocation.parent_chat_message_id if invocation else None
    return ResponseRecord(
        input_messages=inputs,
        steps=read_response_steps(response),
        answer_step_index=next(
            (row.step_index for row in response.response_items if row.is_answer),
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


def write_response_items(
    db_session: Session,
    response: ChatMessage,
    record: ResponseRecord,
    presentation: dict[str, MessageRendering],
) -> dict[tuple[str, str], ToolCall]:
    """Store message content and invocation records; the caller owns the transaction."""
    tools: dict[tuple[str, str], ToolCall] = {}
    existing = {row.id: row for row in response.response_items}
    stored_tools = {
        (tool.turn_number, tool.tool_call_id): tool
        for tool in response.tool_calls or []
    }
    incoming_ids: set[str] = set()
    incoming_calls: set[tuple[int, str]] = set()
    if record.answer_step_index is not None and not (
        0 <= record.answer_step_index < len(record.steps)
    ):
        raise ValueError("Selected answer is not a recorded step")

    response_tools = response.tool_calls
    if response_tools is None:
        response_tools = []
        response.tool_calls = response_tools
    for step_index, step in enumerate(record.steps):
        message = step.message
        message_id = message.id
        if message_id is None:
            raise ValueError("Saved assistant message has no identity")
        item_id = sanitize_string(message_id)
        if item_id in incoming_ids:
            raise ValueError("Response contains duplicate item identities")
        incoming_ids.add(item_id)
        row = existing.get(item_id) or ChatResponseItem(
            id=item_id,
            chat_message_id=response.id,
            step_index=step_index,
        )
        if row.chat_message_id != response.id or row.step_index != step_index:
            raise ValueError("Response item identity or step changed")
        if item_id not in existing:
            response.response_items.append(row)
        row.message = message
        inputs = _accepted_inputs(step.input_messages)
        if row.inputs and row.inputs != inputs:
            raise ValueError("Accepted inputs cannot change")
        row.inputs = inputs
        row.generation_status = step.generation_status
        row.is_answer = step_index == record.answer_step_index
        setting = presentation.pop(message_id, None)
        if setting is not None:
            row.rendering = sanitize_json_like(setting.model_dump(mode="json"))
        if step.tools.keys() - {call.id for call in message.tool_calls}:
            raise ValueError("Tool execution has no call in its assistant message")
        for call in message.tool_calls:
            key = (message_id, call.id)
            if key in tools:
                raise ValueError("Duplicate tool call within one assistant message")
            execution = step.tools.get(call.id)
            stored_call_id = sanitize_string(call.id)
            incoming_calls.add((step_index, stored_call_id))
            arguments = sanitize_json_like(call.arguments)
            tool = stored_tools.get((step_index, stored_call_id)) or ToolCall(
                chat_session_id=response.chat_session_id,
                parent_chat_message_id=response.id,
                turn_number=step_index,
                tab_index=len(tools),
                tool_id=None,
                tool_call_id=stored_call_id,
                tool_call_arguments=arguments,
                tool_call_tokens=count_tokens(json.dumps(arguments)),
                legacy_response="",
            )
            if tool.result is not None and (
                execution is None or execution.result is None
            ):
                raise ValueError("Response update cannot discard recorded results")
            tool.tool_call_arguments = arguments
            tool.operation_status = execution.status if execution is not None else None
            if execution is not None:
                tool.display_name = execution.display_name
            if (step_index, stored_call_id) not in stored_tools:
                response_tools.append(tool)
            db_session.add(tool)
            tools[key] = tool
            if execution is not None and execution.result is not None:
                result = execution.result
                if result.tool_call_id != call.id or result.tool_name != call.name:
                    raise ValueError("Tool result does not match its invocation")
                tool.result = StoredToolResult.model_validate(
                    result, from_attributes=True
                )
    if any(
        tool.result is not None
        for key, tool in stored_tools.items()
        if key not in incoming_calls
    ):
        raise ValueError("Response update cannot discard recorded results")
    if existing.keys() - incoming_ids:
        raise ValueError("Response update cannot discard recorded items")
    db_session.flush()
    return tools


def finish_checkpoint__no_commit(session: Session, message_id: int) -> list[str]:
    """Delete the response's checkpoint. Returns the dumps that it owned, which
    the caller deletes after commit."""
    row = session.get(ChatResponseCheckpoint, message_id)
    if row is None:
        return []
    session.delete(row)
    return list(row.dump_file_ids)


def read_response_status__no_commit(
    session: Session, response_id: int
) -> ResponseStatus | None:
    """Read status and authorization identities without loading conversation content."""
    chain = response_invocation_chain(session, response_id)
    if not chain or chain[0].status is None:
        return None
    response, root = chain[0], chain[-1]
    ancestor_agent_ids = [str(row.session_id) for row in chain[1:]]
    if any(
        parent.session_id != child.parent_session_id
        for child, parent in zip(chain, chain[1:], strict=False)
    ):
        # An agent other than the spawner can start a run, so the invokers are
        # not the session ancestors.
        ancestors = session_ancestors(session, [response.session_id])
        ancestor_agent_ids = [
            str(ancestor.id)
            for ancestor in agent_ancestor_chain(response.session_id, ancestors)[1:]
        ]
    # A continued run can belong to a later turn than its invocation.
    root_message_id = (
        ownership_root_id(session, response_id)
        if any(
            row.spawned_by_message_id is not None
            and row.previous_response_id is not None
            for row in chain
        )
        else root.message_id
    )
    if root_message_id is None:
        return None
    return ResponseStatus(
        message_id=response.message_id,
        root_message_id=root_message_id,
        root_session_id=root.session_id,
        ancestor_agent_ids=ancestor_agent_ids,
        status=response.status,
    )


def find_response__no_commit(session: Session, response_id: int) -> ChatMessage | None:
    return session.scalar(
        select(ChatMessage)
        .where(ChatMessage.id == response_id)
        .options(
            selectinload(ChatMessage.response_items),
            selectinload(ChatMessage.tool_calls),
        )
    )


def read_response__no_commit(
    session: Session, response_id: int
) -> SavedResponse | None:
    response = find_response__no_commit(session, response_id)
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
    messages: list[Message] = [step.message for step in record.steps]
    restore_response_sources(
        messages,
        {
            doc.document_id: translate_db_search_doc_to_saved_search_doc(doc)
            for saved in session.scalars(
                select(ChatMessage)
                .where(ChatMessage.id.in_({root_id, response.id}))
                .options(selectinload(ChatMessage.search_docs))
                .order_by(ChatMessage.id == response.id)
            )
            for doc in saved.search_docs or []
        },
        {
            item.id: read_message_rendering(item.rendering)
            for item in response.response_items
            if item.rendering is not None
        },
    )
    for step, message in zip(record.steps, messages, strict=True):
        step.message.metadata = message.metadata
    record.checkpoint = checkpoint_from_summary(
        find_summary_for_ancestry(
            session, response.chat_session_id, visible_message_ids(session, response)
        )
    )
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
) -> None:
    configure_response_transaction__no_commit(session)
    root = session.get(ChatMessage, root_message_id)
    if root is None:
        raise ValueError("Response root is unavailable")
    writer = _ResponseWriter(session, root, {})
    parent = None
    if record.parent_run_id is not None:
        parent = find_response__no_commit(session, int(record.parent_run_id))
        if parent is None or not response_on_branch(session, parent, writer.branch_ids):
            raise ValueError("Parent response is unavailable on this branch")
    if parent is not None:
        message_ids_by_step = {row.step_index: row.id for row in parent.response_items}
        for tool in parent.tool_calls or []:
            assistant_message_id = message_ids_by_step.get(tool.turn_number)
            if assistant_message_id is None:
                raise ValueError("Parent tool call has no assistant message")
            writer.tools[(assistant_message_id, tool.tool_call_id)] = tool
    writer.store(record, parent)
    session.flush()


def read_suspended_response_replay(
    db_session: Session,
    response_id: int,
    *,
    claimed: bool = False,
    root_session_id: UUID | None = None,
) -> tuple[ChatExecutionRecord, ResponseReplayData]:
    """The saved output of a suspended response, to replay where its run
    continues. A `claimed` response is one whose resume already marked it
    running, as an agent host's claim of a parked run does. Its requests are
    still replayed. `root_session_id` is the chat that holds the requests of
    a subagent's response; it defaults to the response's own session."""
    message = db_session.get(ChatMessage, response_id)
    if message is None:
        raise ValueError("The response is not suspended")
    read = read_chat_execution(message, load_child_responses(db_session, [message]))
    if read is None or (not claimed and read[0].response.status != RunStatus.SUSPENDED):
        raise ValueError("The response is not suspended")
    execution, tool_calls = read
    chat_approvals = load_chat_approvals(
        db_session, root_session_id or message.chat_session_id, [message.id]
    )
    return execution, read_response_replay_data(
        execution,
        tool_calls,
        message,
        db_session,
        chat_approvals,
        show_requests=claimed,
    )


def read_response_replay_data(
    execution: ChatExecutionRecord,
    tool_calls: Mapping[int, ToolCall],
    root: ChatMessage,
    db_session: Session,
    chat_approvals: ChatApprovals | None = None,
    show_requests: bool = False,
) -> ResponseReplayData:
    """Load detached display data for an already authorized response execution.

    `execution` and `tool_calls` are what `read_chat_execution` read from
    `root`. `chat_approvals` holds the requests of a page of responses that
    includes this one (`load_chat_approvals`); it is read for this response
    when not given. `show_requests` replays the requests of a running
    response whose stream starts with this replay."""
    if chat_approvals is None:
        chat_approvals = load_chat_approvals(
            db_session, root.chat_session_id, [root.id]
        )
    documents = {
        document.document_id: translate_db_search_doc_to_saved_search_doc(document)
        for document in root.search_docs or []
    }
    tools: dict[tuple[str, str], ToolReplayData] = {}
    references = {
        reference.record_id: reference for reference in execution.tool_records
    }
    accepted: set[tuple[str, str]] = set()
    # The runs whose records the replay shows: background agents' runs, which
    # agent tools start, show elsewhere.
    run_ids: list[str] = []
    pending = [(execution.response, True)]
    while pending:
        response, shown = pending.pop()
        agent_calls = {
            call.id
            for step in response.steps
            for call in step.message.tool_calls
            if call.name in AGENT_START_TOOL_NAMES
        }
        if shown:
            run_ids.append(response.run_id)
        for step in response.steps:
            if step.message.id is not None:
                accepted.update(
                    (step.message.id, call.id) for call in step.message.tool_calls
                )
        pending.extend(
            (child, shown and child.parent_tool_call_id not in agent_calls)
            for child in response.child_runs
        )
    # Only agent tools start background agents.
    starts_agents = any(
        call.name in AGENT_START_TOOL_NAMES
        for step in execution.response.steps
        for call in step.message.tool_calls
    )
    if len(references) != len(execution.tool_records) or any(
        (reference.message_id, reference.tool_call_id) not in accepted
        for reference in references.values()
    ):
        raise ValueError("Tool replay reference is not part of this response")

    # The session replay prefetches these tool calls' search docs; load them
    # only for calls that do not have them yet, in one query.
    unloaded_ids = [
        tool.id
        for tool in tool_calls.values()
        if "search_docs" in inspect(tool).unloaded
    ]
    if unloaded_ids:
        db_session.execute(
            select(ToolCall)
            .where(ToolCall.id.in_(unloaded_ids))
            .options(selectinload(ToolCall.search_docs))
        ).all()
    for record_id, reference in references.items():
        tool = tool_calls[record_id]
        search_docs = [
            translate_db_search_doc_to_saved_search_doc(document)
            for document in tool.search_docs or []
        ]
        for document in search_docs:
            documents.setdefault(document.document_id, document)
        tools[(reference.message_id, reference.tool_call_id)] = ToolReplayData(
            tool_id=tool.tool_id,
            search_docs=search_docs,
        )
    # A running response's requests reach the client through its stream.
    approvals: dict[tuple[str, str], list[SavedToolApproval]] = {}
    status = execution.response.status
    shows_requests = (
        show_requests or status.is_terminal or status == RunStatus.SUSPENDED
    )
    if accepted and shows_requests:
        for run_id in run_ids:
            for request in chat_approvals.requests.get(int(run_id), []):
                approvals.setdefault((run_id, request.tool_call_id), []).append(request)
    # Only the root run asks questions.
    questions = (
        {
            (execution.response.run_id, question.tool_call_id): question
            for question in chat_approvals.questions.get(root.id, [])
        }
        if accepted and (status.is_terminal or status == RunStatus.SUSPENDED)
        else {}
    )
    # Background agents wait independently of this response's status; the
    # runs whose records the response shows are left out.
    agent_approvals: dict[tuple[str, str], list[AgentToolApproval]] = {}
    if starts_agents:
        for agent_response_id, anchor_call_id in chat_approvals.started_runs.get(
            root.id, []
        ):
            if str(agent_response_id) in run_ids:
                continue
            agent_approvals.setdefault((str(root.id), anchor_call_id), []).extend(
                AgentToolApproval(
                    approval=request,
                    agent_name=chat_approvals.agent_names.get(agent_response_id, ""),
                )
                for request in chat_approvals.requests.get(agent_response_id, [])
            )
        for shown in agent_approvals.values():
            shown.sort(key=lambda agent: (agent.approval.created_at, agent.approval.id))
    return ResponseReplayData(
        tools=tools,
        documents=documents,
        approvals=approvals,
        agent_approvals=agent_approvals,
        questions=questions,
    )


def load_chat_approvals(
    db_session: Session, chat_session_id: UUID, response_ids: Collection[int]
) -> ChatApprovals:
    """The approval requests of `response_ids` and of the runs that they
    started, directly or through the runs they started, and the questions of
    `response_ids`, for the replays of those responses. Requests and
    questions always belong to the root chat session; a chat without them
    reads nothing else."""
    approvals = ChatApprovals()
    if not response_ids:
        return approvals
    has_approvals, has_questions = db_session.execute(
        select(
            exists().where(ApprovalRequest.chat_session_id == chat_session_id),
            exists().where(QuestionRequest.chat_session_id == chat_session_id),
        )
    ).one()
    if has_questions:
        for question in get_response_question_requests(db_session, response_ids):
            approvals.questions.setdefault(question.chat_message_id, []).append(
                SavedToolQuestion.model_validate(question)
            )
    if not has_approvals:
        return approvals
    question = aliased(ChatMessage)
    started = (
        select(
            ChatMessage.id.label("response_id"),
            ToolCall.parent_chat_message_id.label("root_id"),
            ToolCall.tool_call_id.label("anchor_call_id"),
        )
        .join(question, question.id == ChatMessage.parent_message_id)
        .join(ToolCall, ToolCall.id == question.invoking_tool_call_id)
        .where(ToolCall.parent_chat_message_id.in_(response_ids))
        .cte("agent_runs_started", recursive=True)
    )
    child = aliased(ChatMessage)
    child_question = aliased(ChatMessage)
    child_call = aliased(ToolCall)
    started = started.union_all(
        select(child.id, started.c.root_id, started.c.anchor_call_id)
        .join(child_question, child_question.id == child.parent_message_id)
        .join(child_call, child_call.id == child_question.invoking_tool_call_id)
        .join(started, child_call.parent_chat_message_id == started.c.response_id)
        .where(child.id > started.c.response_id)
    )
    started_runs = db_session.execute(
        select(started.c.response_id, started.c.root_id, started.c.anchor_call_id)
    ).all()
    rows = db_session.execute(
        select(
            ApprovalRequest,
            ChatMessage.chat_session_id,
            ChatSession.agent_name,
            Integration.kind,
        )
        .join(ChatMessage, ChatMessage.id == ApprovalRequest.chat_message_id)
        .join(ChatSession, ChatSession.id == ChatMessage.chat_session_id)
        .outerjoin(Integration, Integration.id == ApprovalRequest.integration_id)
        .where(
            ApprovalRequest.chat_session_id == chat_session_id,
            ApprovalRequest.chat_message_id.in_(
                {*response_ids, *(run.response_id for run in started_runs)}
            ),
        )
        .order_by(ApprovalRequest.created_at, ApprovalRequest.id)
    ).all()
    for request, session_id, agent_name, integration_kind in rows:
        approvals.requests.setdefault(request.chat_message_id, []).append(
            SavedToolApproval.model_validate(request).model_copy(
                update={"integration_kind": integration_kind}
            )
        )
        if session_id != chat_session_id:
            approvals.agent_names[request.chat_message_id] = agent_name or ""
    for response_id, root_id, anchor_call_id in started_runs:
        if response_id in approvals.requests:
            approvals.started_runs.setdefault(root_id, []).append(
                (response_id, anchor_call_id)
            )
    return approvals


def waiting_approval_reply_ids(db_session: Session, chat_session_id: UUID) -> set[int]:
    """The chat's responses that have an approval request or a question
    waiting for the user, or that started a run, directly or through the runs
    it started, that has a request waiting; a chat without waiting requests
    reads nothing else."""
    approvals_wait, questions_wait = db_session.execute(
        select(
            exists().where(
                ApprovalRequest.chat_session_id == chat_session_id,
                ApprovalRequest.decision.is_(None),
            ),
            exists().where(
                QuestionRequest.chat_session_id == chat_session_id,
                QuestionRequest.outcome.is_(None),
            ),
        )
    ).one()
    # Only root responses ask, so a waiting question's response is a reply.
    asking = (
        set(
            db_session.scalars(
                select(QuestionRequest.chat_message_id).where(
                    QuestionRequest.chat_session_id == chat_session_id,
                    QuestionRequest.outcome.is_(None),
                )
            )
        )
        if questions_wait
        else set()
    )
    if not approvals_wait:
        return asking
    approvals = load_chat_approvals(
        db_session,
        chat_session_id,
        db_session.scalars(
            select(ChatMessage.id).where(
                ChatMessage.chat_session_id == chat_session_id,
                ChatMessage.message_type == MessageType.ASSISTANT,
            )
        ).all(),
    )
    waiting = {
        response_id
        for response_id, requests in approvals.requests.items()
        if any(request.decision is None for request in requests)
    }
    return (
        asking
        | waiting
        | {
            root_id
            for root_id, runs in approvals.started_runs.items()
            if any(run_id in waiting for run_id, _ in runs)
        }
    )
