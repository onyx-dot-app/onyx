"""Conditional checkpoint transitions. Callers own transactions."""

from collections.abc import Collection
from uuid import UUID

from pydantic import JsonValue, TypeAdapter
from sqlalchemy import any_, exists, select, true
from sqlalchemy.orm import Session, aliased

from onyx.agents.models import InputSource, RunFailure, RunFailureKind, RunStatus
from onyx.chat.models import ParkedRun, ResponseCheckpoint, SavedCheckpoint
from onyx.db.approval_request import close_pending_approval_requests__no_commit
from onyx.db.chat import (
    configure_response_transaction__no_commit,
    response_invocation_chain,
    session_descendants,
)
from onyx.db.chat_response import finish_checkpoint__no_commit
from onyx.db.enums import ApprovalDecision, record_mode_persists_content
from onyx.db.models import (
    ApprovalRequest,
    ChatInput,
    ChatMessage,
    ChatResponseCheckpoint,
    ChatSession,
)
from onyx.llm.override_models import LLMOverride

_JSON_OBJECT = TypeAdapter(dict[str, JsonValue])


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
    expected_ownership_version: int | None,
    child_run_ids: Collection[int] = (),
    dump_file_ids: Collection[str] = (),
) -> list[str]:
    """Save a paused response's checkpoint, with the foreground child runs it
    waits for and the program dumps it owns. Returns the dumps of the
    checkpoint that it replaces, which the caller deletes after commit.

    A deleted chat parks nothing: nobody can decide its requests. The share
    lock on the root chat row waits for a soft delete in progress, which ends
    the parked responses that it reads after its commit.
    """
    if data.binding.response_id != str(message_id):
        raise ValueError("Checkpoint binding does not match its response")
    chain = response_invocation_chain(session, message_id)
    if not chain or session.scalar(
        select(ChatSession.deleted)
        .where(ChatSession.id == chain[-1].session_id)
        .with_for_update(read=True)
    ):
        raise ValueError("A deleted chat cannot park a response")
    response = _lock_response(session, message_id)
    if not record_mode_persists_content(response.chat_session.incognito_record_mode):
        raise ValueError("Content-free responses cannot store execution checkpoints")
    if response.response_status is None or response.response_status.is_terminal:
        raise ValueError("Only an active response can pause")
    row = session.get(ChatResponseCheckpoint, message_id, populate_existing=True)
    if row is None:
        if expected_ownership_version is not None:
            raise ValueError("Checkpoint was removed")
        row = ChatResponseCheckpoint(
            chat_message_id=message_id,
            ownership_version=1,
            state={},
            child_run_ids=[],
            dump_file_ids=[],
        )
        session.add(row)
    else:
        if (
            expected_ownership_version != row.ownership_version
            or response.response_status != RunStatus.RUNNING
        ):
            raise ValueError("Checkpoint ownership changed")
        row.ownership_version += 1
    replaced = [
        file_id for file_id in row.dump_file_ids if file_id not in dump_file_ids
    ]
    row.state = _JSON_OBJECT.validate_python(data.model_dump(mode="json"))
    row.child_run_ids = list(child_run_ids)
    row.dump_file_ids = list(dump_file_ids)
    response.response_status = RunStatus.SUSPENDED
    session.flush()
    return replaced


def parked_response_model(session: Session, message_id: int) -> LLMOverride | None:
    """The model that a parked response ran, by its saved configuration and
    with its display name; None when its checkpoint names none."""
    row = session.execute(
        select(
            ChatResponseCheckpoint.state["model_configuration_id"].as_integer(),
            ChatMessage.model_display_name,
        )
        .join(ChatMessage, ChatMessage.id == ChatResponseCheckpoint.chat_message_id)
        .where(ChatResponseCheckpoint.chat_message_id == message_id)
    ).one_or_none()
    if row is None or row[0] is None:
        return None
    return LLMOverride(model_configuration_id=row[0], display_name=row[1])


def claim_checkpoint__no_commit(
    session: Session, message_id: int
) -> SavedCheckpoint | None:
    response = _lock_response(session, message_id)
    row = session.get(ChatResponseCheckpoint, message_id, populate_existing=True)
    if row is None or response.response_status != RunStatus.SUSPENDED:
        return None
    row.ownership_version += 1
    response.response_status = RunStatus.RUNNING
    session.flush()
    return SavedCheckpoint(
        ownership_version=row.ownership_version,
        data=ResponseCheckpoint.model_validate(row.state),
    )


def check_checkpoint_owner__no_commit(
    session: Session, message_id: int, ownership_version: int | None
) -> None:
    """Check the checkpoint version; callers enforce the live cache ownership lease.

    Initial executions may repeat terminal saves for lifecycle and display storage.
    """
    configure_response_transaction__no_commit(session)
    response = _lock_response(session, message_id)
    row = session.get(ChatResponseCheckpoint, message_id, populate_existing=True)
    if (row is None) != (ownership_version is None) or (
        row is not None and row.ownership_version != ownership_version
    ):
        raise ValueError("Response ownership changed")
    if ownership_version is not None and response.response_status != RunStatus.RUNNING:
        raise ValueError("Response is no longer owned by this runner")


def release_checkpoint_claim__no_commit(
    session: Session, message_id: int, ownership_version: int
) -> None:
    """Undo a failed reconstruction only before resumed execution starts."""
    check_checkpoint_owner__no_commit(session, message_id, ownership_version)
    response = session.get(ChatMessage, message_id)
    if response is None:
        raise ValueError("Response is unavailable")
    response.response_status = RunStatus.SUSPENDED


def interrupt_response__no_commit(
    session: Session,
    message_id: int,
    *,
    cancelled: bool = False,
    failure: RunFailure | None = None,
    keep_parked: bool = False,
) -> list[str] | None:
    """Caller holds the response's cache lock and has verified that no owner remains.

    A cancelled response keeps `failure`, the reason its Stop gave, if any; a
    failed one keeps `failure`, or says that its owner stopped. Its approval
    requests end, since no call waits for them anymore. With `keep_parked`, a
    parked response, SUSPENDED with a checkpoint, stays as it is. Returns the dumps that its checkpoint
    owned, which the caller deletes after commit; None when the response did
    not end here.
    """
    response = _lock_response(session, message_id)
    if (
        response.response_status is None
        or response.response_status.is_terminal
        or (
            keep_parked
            and response.response_status == RunStatus.SUSPENDED
            and session.get(ChatResponseCheckpoint, message_id) is not None
        )
    ):
        return None
    close_pending_approval_requests__no_commit(
        session, ApprovalDecision.EXPIRED, None, chat_message_ids=[message_id]
    )
    response.response_status = RunStatus.CANCELLED if cancelled else RunStatus.ERROR
    response.response_failure = (
        failure
        if cancelled
        else failure
        or RunFailure(
            kind=RunFailureKind.EXECUTION,
            message="The response owner stopped reporting progress",
        )
    )
    return finish_checkpoint__no_commit(session, message_id)


def chat_has_checkpoint(session: Session, chat_session_id: UUID) -> bool:
    """Whether a response of the chat itself, not of its agents, has a
    checkpoint; a root response can be parked only then."""
    return bool(
        session.scalar(
            select(
                exists()
                .where(ChatResponseCheckpoint.chat_message_id == ChatMessage.id)
                .where(ChatMessage.chat_session_id == chat_session_id)
            )
        )
    )


def resumable_parked_runs(session: Session, chat_session_id: UUID) -> list[ParkedRun]:
    """The parked runs of the chat, on any branch, whose waits all ended.

    A run is parked while its response is SUSPENDED with a checkpoint. Its
    waits are its approval requests, the foreground child runs that its
    checkpoint names and, for a subagent, the runs that it delegated, whose
    result rows it has not read. It resumes once none is undecided or
    unfinished; a request whose row was deleted, with its tool's server, gives
    its call no tool.
    """
    sessions = session_descendants(chat_session_id)
    child = aliased(ChatMessage)
    delegated = aliased(ChatMessage)
    unfinished = (RunStatus.RUNNING, RunStatus.SUSPENDED)
    requests = select(ApprovalRequest.id).where(
        ApprovalRequest.chat_message_id == ChatMessage.id
    )
    children = select(child.id).where(
        child.id == any_(ChatResponseCheckpoint.child_run_ids)
    )
    # The root does not wait for the runs that it delegates.
    delegations = (
        select(delegated.id)
        .join(ChatInput, ChatInput.source_response_id == delegated.id)
        .where(
            ChatMessage.chat_session_id != chat_session_id,
            ChatInput.source == InputSource.AGENT_RESULT,
            ChatInput.recipient_session_id == ChatMessage.chat_session_id,
        )
    )
    rows = session.execute(
        select(ChatMessage.id, ChatMessage.chat_session_id)
        .join(
            ChatResponseCheckpoint,
            ChatResponseCheckpoint.chat_message_id == ChatMessage.id,
        )
        .join(sessions, sessions.c.id == ChatMessage.chat_session_id)
        .where(
            ChatMessage.response_status == RunStatus.SUSPENDED,
            ~requests.where(ApprovalRequest.decision.is_(None)).exists(),
            ~children.where(child.response_status.in_(unfinished)).exists(),
            ~delegations.where(delegated.response_status.in_(unfinished)).exists(),
        )
        .order_by(ChatMessage.id)
    ).all()
    return [
        ParkedRun(
            agent_id=str(agent_id),
            response_id=response_id,
            # Resumable runs are few; each is found only after its waits end.
            root_response_id=response_id
            if agent_id == chat_session_id
            else response_invocation_chain(session, response_id)[-1].message_id,
        )
        for response_id, agent_id in rows
    ]


def parked_response_ids(
    session: Session, user_id: UUID, chat_session_id: UUID | None = None
) -> list[int]:
    """The parked responses of the user's chats, or of one chat. A parked tree
    always waits on a request somewhere, so only chats with requests are read."""
    roots = session.scalars(
        select(ApprovalRequest.chat_session_id)
        .join(ChatSession, ChatSession.id == ApprovalRequest.chat_session_id)
        .where(
            ChatSession.user_id == user_id,
            ApprovalRequest.chat_session_id == chat_session_id
            if chat_session_id is not None
            else true(),
        )
        .distinct()
    ).all()
    parked: list[int] = []
    for root in roots:
        sessions = session_descendants(root)
        parked.extend(
            session.scalars(
                select(ChatMessage.id)
                .join(
                    ChatResponseCheckpoint,
                    ChatResponseCheckpoint.chat_message_id == ChatMessage.id,
                )
                .join(sessions, sessions.c.id == ChatMessage.chat_session_id)
                .where(ChatMessage.response_status == RunStatus.SUSPENDED)
            )
        )
    return parked
