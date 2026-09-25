"""Response history and conditional pause transitions. Callers own transactions."""

from uuid import UUID

from pydantic import BaseModel, JsonValue, TypeAdapter
from sqlalchemy import select
from sqlalchemy.orm import Session, aliased, selectinload

from onyx.agents.execution_records import RunFailure, RunFailureKind, RunStatus
from onyx.agents.models import AgentInfo
from onyx.chat.checkpoint import ResponseCheckpoint
from onyx.chat.models import ResponseRecord
from onyx.chat.response_items import ResponseItemKind
from onyx.db.chat_history import checkpoint_from_summary, find_summary_for_ancestry
from onyx.db.chat_response import (
    _ResponseWriter,
    configure_response_transaction__no_commit,
)
from onyx.db.chat_response_items import (
    finish_checkpoint__no_commit,
    read_response_record,
)
from onyx.db.chat_subagents import (
    MAX_AGENT_DEPTH,
    agent_session_path,
    parent_session_id,
    root_response_id,
    visible_message_ids,
)
from onyx.db.models import ChatMessage, ChatResponseCheckpoint, ChatSession, ToolCall
from onyx.utils.postgres_sanitization import sanitize_json_like

_JSON_OBJECT = TypeAdapter(dict[str, JsonValue])


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


class SavedCheckpoint(BaseModel):
    revision: int
    data: ResponseCheckpoint


def find_response__no_commit(session: Session, run_id: str) -> ChatMessage | None:
    predicate = (
        ChatMessage.id == int(run_id)
        if run_id.isdecimal()
        else ChatMessage.run_id == run_id
    )
    return session.scalar(
        select(ChatMessage)
        .where(predicate)
        .options(selectinload(ChatMessage.response_items))
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


def save_response_progress__no_commit(
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
        generation_id = None
        for item in parent.response_items:
            if item.kind == ResponseItemKind.GENERATION:
                generation_id = item.id
            elif item.kind == ResponseItemKind.TOOL_CALL and item.tool_call is not None:
                if generation_id is None:
                    raise ValueError("Parent tool call has no generation")
                writer.tools[(generation_id, item.tool_call.tool_call_id)] = (
                    item.tool_call
                )
    writer.store(record, parent)
    session.flush()
    return writer.responses[record.run_id].id


def _lock_response(session: Session, message_id: int) -> ChatMessage:
    response = session.scalar(
        select(ChatMessage)
        .where(ChatMessage.id == message_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if response is None:
        raise ValueError("Response is unavailable")
    return response


def publish_checkpoint__no_commit(
    session: Session,
    message_id: int,
    data: ResponseCheckpoint,
    *,
    expected_revision: int | None,
) -> int:
    response = _lock_response(session, message_id)
    if response.response_status is None or response.response_status.is_terminal:
        raise ValueError("Only an active response can pause")
    row = session.get(ChatResponseCheckpoint, message_id, populate_existing=True)
    if row is None:
        if expected_revision is not None:
            raise ValueError("Checkpoint was removed")
        row = ChatResponseCheckpoint(
            chat_message_id=message_id, revision=1, progress={}
        )
        session.add(row)
    else:
        if (
            expected_revision != row.revision
            or response.response_status != RunStatus.RUNNING
        ):
            raise ValueError("Checkpoint ownership changed")
        row.revision += 1
    row.progress = _JSON_OBJECT.validate_python(data.model_dump(mode="json"))
    response.response_status = RunStatus.SUSPENDED
    session.flush()
    return row.revision


def claim_checkpoint__no_commit(
    session: Session, message_id: int
) -> SavedCheckpoint | None:
    response = _lock_response(session, message_id)
    row = session.get(ChatResponseCheckpoint, message_id, populate_existing=True)
    if row is None or response.response_status != RunStatus.SUSPENDED:
        return None
    row.revision += 1
    response.response_status = RunStatus.RUNNING
    session.flush()
    return SavedCheckpoint(
        revision=row.revision, data=ResponseCheckpoint.model_validate(row.progress)
    )


def check_checkpoint_owner__no_commit(
    session: Session, message_id: int, revision: int | None
) -> None:
    configure_response_transaction__no_commit(session)
    response = _lock_response(session, message_id)
    row = session.get(ChatResponseCheckpoint, message_id, populate_existing=True)
    if (row is None) != (revision is None) or (
        row is not None and row.revision != revision
    ):
        raise ValueError("Response ownership changed")
    if revision is not None and response.response_status != RunStatus.RUNNING:
        raise ValueError("Response is no longer owned by this runner")


def release_checkpoint_claim__no_commit(
    session: Session, message_id: int, revision: int
) -> None:
    """Undo a failed reconstruction only before resumed execution starts."""
    check_checkpoint_owner__no_commit(session, message_id, revision)
    response = session.get(ChatMessage, message_id)
    if response is None:
        raise ValueError("Response is unavailable")
    response.response_status = RunStatus.SUSPENDED


def interrupt_response__no_commit(
    session: Session, message_id: int, *, cancelled: bool = False
) -> None:
    """Caller holds the response's cache lock and has verified that no owner remains."""
    response = _lock_response(session, message_id)
    if response.response_status is None or response.response_status.is_terminal:
        return
    response.response_status = RunStatus.CANCELLED if cancelled else RunStatus.ERROR
    if not cancelled:
        response.response_failure = RunFailure(
            kind=RunFailureKind.EXECUTION,
            message="The response owner stopped reporting progress",
        )
    finish_checkpoint__no_commit(session, message_id)
