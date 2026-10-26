import json
from uuid import UUID

from pydantic import BaseModel
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session, aliased, joinedload, object_session, selectinload

from onyx.agents.compaction import count_tokens
from onyx.agents.execution_records import run_input_message_id
from onyx.agents.models import AgentInfo, RunStatus, StepRecord, ToolExecutionRecord
from onyx.chat.response_models import (
    ChatExecutionRecord,
    ChatResponseSnapshot,
    MessageRendering,
    ResponseRecord,
    ResponseReplayData,
    ToolRecordReference,
    ToolReplayData,
)
from onyx.configs.constants import MessageType
from onyx.context.search.models import SearchDoc
from onyx.db.chat import (
    MAX_AGENT_DEPTH,
    MAX_AGENT_HISTORY_RUNS,
    MAX_CONVERSATION_MESSAGES,
    add_search_docs_to_tool_call,
    agent_session_path,
    checkpoint_from_summary,
    find_summary_for_ancestry,
    parent_session_id,
    root_response_id,
    translate_db_search_doc_to_saved_search_doc,
    visible_message_ids,
)
from onyx.db.chat_display import save_chat_display__no_commit
from onyx.db.engine.sql_engine import get_session_with_current_tenant
from onyx.db.enums import record_mode_persists_content
from onyx.db.models import (
    ChatMessage,
    ChatResponseCheckpoint,
    ChatResponseItem,
    ChatSession,
    StoredToolResult,
    ToolCall,
)
from onyx.llm.models import (
    GenerationRequestParams,
    UserMessage,
)
from onyx.natural_language_processing.utils import get_tokenizer
from onyx.tools.records import RecordedToolCallInfo
from onyx.utils.logger import setup_logger
from onyx.utils.postgres_sanitization import sanitize_json_like, sanitize_string

logger = setup_logger()

CHAT_RESPONSE_STATEMENT_TIMEOUT_MS = 30_000
CHAT_RESPONSE_LOCK_TIMEOUT_MS = 5_000


def _attach_tool_artifacts(
    tool_calls: list[RecordedToolCallInfo],
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
    tool_calls: list[RecordedToolCallInfo],
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
    """Save displayed content and accepted runtime records in one transaction."""
    tool_records = save_response_content(
        assistant_message,
        response_record,
        db_session=db_session,
        persist_content=persist_content,
        presentation=presentation,
    )
    tool_sources = save_chat_display__no_commit(
        message_text=message_text,
        reasoning_tokens=reasoning_tokens,
        tool_calls=tool_calls,
        citation_to_doc=citation_to_doc,
        all_search_docs=all_search_docs,
        document_key=lambda document: document.document_id,
        db_session=db_session,
        assistant_message=assistant_message,
        tokenizer=get_tokenizer(None, None),
        is_clarification=is_clarification,
        emitted_citations=emitted_citations,
        pre_answer_processing_time=pre_answer_processing_time,
        persist_content=persist_content,
        request_params=request_params.model_dump(mode="json")
        if request_params is not None
        else None,
    )
    if persist_content:
        _attach_tool_artifacts(
            tool_calls,
            tool_records,
            db_session,
            {
                info.execution_key: sources
                for info, sources in zip(tool_calls, tool_sources, strict=True)
            },
        )
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
                ChatResponseItem,
                (ChatResponseItem.chat_message_id == ToolCall.parent_chat_message_id)
                & (ChatResponseItem.step_index == ToolCall.turn_number),
            )
            .where(
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
                selectinload(ChatMessage.tool_calls),
            )
            # Stable display order; predecessor links determine child history.
            .order_by(ChatResponseItem.step_index, ChatMessage.id)
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
            row.step_index: row.id for row in response.response_items
        }
        message_ids_by_tool: dict[int, str] = {}
        for row in response.response_items:
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
        if record.checkpoint is not None and record.checkpoint.summary:
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
        response = find_response__no_commit(self.db_session, int(record.run_id))
        if response is None:
            raise ValueError("Child response was not reserved")
        if response.chat_session_id != UUID(record.agent_id):
            raise ValueError("Saved response belongs to another agent")
        question = response.parent_message
        if question is None or question.invoking_tool_call_id != invocation.id:
            raise ValueError("Saved response belongs to another invocation")
        creation_id = response.chat_session.spawned_by_message_id
        creation_response = (
            self.db_session.get(ChatMessage, creation_id)
            if creation_id is not None
            else None
        )
        if (
            creation_response is None
            or creation_response.chat_session_id != parent.chat_session_id
            or root_response_id(self.db_session, creation_response)
            not in self.branch_ids
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
    instruction: UserMessage,
    previous_response_id: int | None,
    parent_response_id: int,
    parent_message_id: str,
    parent_tool_call_id: str,
) -> int:
    """Reserve a child question and response before execution; caller commits."""
    configure_response_transaction__no_commit(session)
    root = session.get(ChatMessage, root_message_id)
    parent = find_response__no_commit(session, parent_response_id)
    if root is None or parent is None or root_response_id(session, parent) != root.id:
        raise ValueError("Parent response is unavailable on this branch")
    if not record_mode_persists_content(root.chat_session.incognito_record_mode):
        raise ValueError("Content-free sessions cannot reserve durable child responses")
    if agent.parent_id != str(parent.chat_session_id):
        raise ValueError("Child agent belongs to another parent")
    if not isinstance(instruction.content, str):
        raise ValueError("Saved child instructions must contain text only")
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
    branch_ids = visible_message_ids(session, root)
    if child_session is None:
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
    if (
        creation_response is None
        or creation_response.chat_session_id != parent.chat_session_id
        or root_response_id(session, creation_response) not in branch_ids
    ):
        raise ValueError("Child session is unavailable on this branch")
    predecessor = None
    if previous_response_id is not None:
        predecessor = find_response__no_commit(session, previous_response_id)
        if (
            predecessor is None
            or predecessor.chat_session_id != child_session.id
            or root_response_id(session, predecessor) not in branch_ids
        ):
            raise ValueError("Child predecessor is unavailable on this branch")
        if (
            predecessor.response_status is None
            or not predecessor.response_status.is_terminal
        ):
            raise ValueError("Child predecessor has not finished")
    instruction_text = sanitize_string(instruction.text)
    question = ChatMessage(
        chat_session_id=child_session.id,
        parent_message_id=predecessor.id if predecessor else None,
        invoking_tool_call_id=invocation.id,
        message=instruction_text,
        token_count=count_tokens(instruction_text),
        message_type=MessageType.USER,
    )
    session.add(question)
    session.flush()
    response = ChatMessage(
        chat_session_id=child_session.id,
        parent_message_id=question.id,
        message="",
        token_count=0,
        message_type=MessageType.ASSISTANT,
    )
    session.add(response)
    session.flush()
    question.latest_child_message_id = response.id
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
    if question is None or question.invoking_tool_call_id is None:
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
            if tool.operation_status is not None:
                step.tools[call.id] = ToolExecutionRecord(
                    status=tool.operation_status,
                    result=result.model_copy(deep=True) if result is not None else None,
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
        input_id = run_input_message_id(str(response.id), 0)
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
                tool_call_response="",
            )
            if tool.result is not None and (
                execution is None or execution.result is None
            ):
                raise ValueError("Response update cannot discard recorded results")
            tool.tool_call_arguments = arguments
            tool.operation_status = execution.status if execution is not None else None
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
    root_message_id: int
    root_session_id: UUID
    parent_agent_id: str | None
    status: RunStatus


class _ResponseAncestry(BaseModel):
    message_id: int
    session_id: UUID
    status: RunStatus | None
    spawned_by_message_id: int | None
    parent_session_id: UUID | None
    parent_response_id: int | None


def _read_response_ancestry(
    session: Session, response_id: int
) -> _ResponseAncestry | None:
    question = aliased(ChatMessage)
    spawning_response = aliased(ChatMessage)
    row = (
        session.execute(
            select(
                ChatMessage.id.label("message_id"),
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
            .where(ChatMessage.id == response_id)
        )
        .mappings()
        .one_or_none()
    )
    return _ResponseAncestry.model_validate(row) if row is not None else None


def read_response_status__no_commit(
    session: Session, response_id: int
) -> ResponseStatus | None:
    """Read status and authorization identities without loading conversation content."""
    response = _read_response_ancestry(session, response_id)
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
        parent = _read_response_ancestry(session, current.parent_response_id)
        if parent is None:
            raise ValueError("Parent response is unavailable")
        current = parent
    return ResponseStatus(
        message_id=response.message_id,
        root_message_id=current.message_id,
        root_session_id=current.session_id,
        parent_agent_id=str(response.parent_session_id)
        if response.parent_session_id is not None
        else None,
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
    parent = None
    if record.parent_run_id is not None:
        parent = find_response__no_commit(session, int(record.parent_run_id))
        if parent is None or root_response_id(session, parent) != root.id:
            raise ValueError("Parent response is unavailable on this branch")
    writer = _ResponseWriter(session, root, {})
    if parent is not None:
        message_ids_by_step = {row.step_index: row.id for row in parent.response_items}
        for tool in parent.tool_calls or []:
            assistant_message_id = message_ids_by_step.get(tool.turn_number)
            if assistant_message_id is None:
                raise ValueError("Parent tool call has no assistant message")
            writer.tools[(assistant_message_id, tool.tool_call_id)] = tool
    writer.store(record, parent)
    session.flush()


def read_response_replay_data(
    execution: ChatExecutionRecord, db_session: Session
) -> ResponseReplayData:
    """Load detached display data for an already authorized response execution."""
    root = db_session.get(ChatMessage, int(execution.response.run_id))
    if root is None:
        raise ValueError("Chat response is unavailable")
    tools: dict[tuple[str, str], ToolReplayData] = {}
    references = {
        reference.record_id: reference for reference in execution.tool_records
    }
    accepted: set[tuple[str, str]] = set()
    pending = [execution.response]
    while pending:
        response = pending.pop()
        for step in response.steps:
            if step.message.id is not None:
                accepted.update(
                    (step.message.id, call.id) for call in step.message.tool_calls
                )
        pending.extend(response.child_runs)
    if len(references) != len(execution.tool_records) or any(
        (reference.message_id, reference.tool_call_id) not in accepted
        for reference in references.values()
    ):
        raise ValueError("Tool replay reference is not part of this response")

    rows = (
        db_session.execute(
            select(ToolCall, ChatResponseItem.id)
            .join(
                ChatResponseItem,
                (ChatResponseItem.chat_message_id == ToolCall.parent_chat_message_id)
                & (ChatResponseItem.step_index == ToolCall.turn_number),
            )
            .where(ToolCall.id.in_(references))
            .options(selectinload(ToolCall.search_docs))
        ).all()
        if references
        else []
    )
    for tool, message_id in rows:
        reference = references[tool.id]
        if (
            reference.message_id != message_id
            or reference.tool_call_id != tool.tool_call_id
        ):
            raise ValueError(
                "Tool replay reference does not match its accepted invocation"
            )
        tools[(message_id, tool.tool_call_id)] = ToolReplayData(
            tool_id=tool.tool_id,
            search_docs=[
                translate_db_search_doc_to_saved_search_doc(document)
                for document in tool.search_docs or []
            ],
        )
    if len(rows) != len(references):
        raise ValueError("Accepted tool replay data is unavailable")
    return ResponseReplayData(
        tools=tools,
        documents={
            document.document_id: translate_db_search_doc_to_saved_search_doc(document)
            for document in root.search_docs or []
        },
    )
