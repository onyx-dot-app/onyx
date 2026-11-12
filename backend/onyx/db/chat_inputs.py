"""Pending human messages. Callers own transactions and response leases.

A row is pending until a step or a new turn consumes it; consuming deletes it.
"""

from collections.abc import Collection
from uuid import UUID, uuid4

from sqlalchemy import Select, delete, func, select, update
from sqlalchemy.orm import Session
from sqlalchemy.sql.elements import ColumnElement

from onyx.agents.models import (
    InputMessageMetadata,
    InputSource,
    MessageDelivery,
    RunFailure,
    RunFailureKind,
    RunStatus,
)
from onyx.chat.models import (
    ChatBranch,
    ChatInbox,
    PendingChatMessage,
    QueuedChatTurn,
)
from onyx.configs.constants import MessageType
from onyx.db.chat import (
    configure_response_transaction__no_commit,
    get_owned_chat_session,
    get_selected_branch,
)
from onyx.db.chat_checkpoint import check_checkpoint_owner__no_commit
from onyx.db.models import (
    ChatInput,
    ChatMessage,
    ChatSession,
    User,
)
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.llm.models import UserMessage
from onyx.utils.postgres_sanitization import sanitize_string

MAX_PENDING_MESSAGES = 64
MAX_PENDING_MESSAGE_BYTES = 1024 * 1024
# A root response reserved for a turn has no status until its run starts.
_ACCEPTING_STATUSES = (None, RunStatus.RUNNING, RunStatus.SUSPENDED)


def lock_agent(session: Session, agent_id: str) -> ChatSession:
    configure_response_transaction__no_commit(session)
    # Serialize inbox changes without blocking response and tool foreign keys.
    agent = session.scalar(
        select(ChatSession)
        .where(ChatSession.id == UUID(agent_id))
        .with_for_update(key_share=True)
    )
    if agent is None:
        raise ValueError("Agent is unavailable")
    return agent


def _pauses_queue(latest_status: RunStatus | None) -> bool:
    """Stop, interruption, and failure pause a recipient's queued work; a step limit does not."""
    return latest_status in (RunStatus.CANCELLED, RunStatus.ERROR)


def can_start_input(
    delivery: MessageDelivery | None,
    target_response_id: int | None,
    latest_status: RunStatus | None,
) -> bool:
    """Whether pending input starts its recipient's next run.

    A recipient without a previous run has no latest status. After a pause,
    interruption and sends to an idle recipient still start.
    """
    if latest_status is not None and not latest_status.is_terminal:
        return False
    return (
        not _pauses_queue(latest_status)
        or delivery == MessageDelivery.INTERRUPT
        or (delivery == MessageDelivery.SEND and target_response_id is None)
    )


def cancel_completed_responses__no_commit(
    session: Session, chat_session_id: UUID, response_ids: Collection[int]
) -> None:
    """Save a Stop that arrived after the response finished; it pauses the queue."""
    lock_agent(session, str(chat_session_id))
    session.execute(
        update(ChatMessage)
        .where(
            ChatMessage.chat_session_id == chat_session_id,
            ChatMessage.message_type == MessageType.ASSISTANT,
            ChatMessage.response_status.in_([RunStatus.COMPLETE, RunStatus.LIMIT]),
            ChatMessage.id.in_(response_ids),
        )
        .values(response_status=RunStatus.CANCELLED)
    )


def get_human_input_session(
    session: Session, chat_session_id: UUID, user: User
) -> ChatSession:
    """Authorize durable user input without granting shared-session write access."""
    if user.is_anonymous or user.id is None:
        raise OnyxError(OnyxErrorCode.UNAUTHORIZED, "Sign in to use queued messages")
    chat_session = get_owned_chat_session(chat_session_id, user.id, session)
    if chat_session is None or chat_session.deleted:
        raise OnyxError(OnyxErrorCode.SESSION_NOT_FOUND, "Chat session not found")
    if chat_session.incognito_record_mode is not None:
        raise OnyxError(
            OnyxErrorCode.INVALID_INPUT,
            "Pending messages are unavailable in incognito chats",
        )
    return chat_session


def _pending_content(message: str) -> str:
    """Validate and sanitize the text of a new pending message."""
    if len(message.encode()) > MAX_PENDING_MESSAGE_BYTES:
        raise OnyxError(
            OnyxErrorCode.PAYLOAD_TOO_LARGE,
            f"A pending message can have at most {MAX_PENDING_MESSAGE_BYTES} bytes",
        )
    return sanitize_string(message)


def _pending_human_inputs(chat_session_id: UUID) -> Select[tuple[ChatInput]]:
    return (
        select(ChatInput)
        .where(
            ChatInput.recipient_session_id == chat_session_id,
            ChatInput.source == InputSource.HUMAN,
        )
        .order_by(ChatInput.id)
    )


def _pending_human_message(row: ChatInput) -> PendingChatMessage:
    if row.delivery is None:
        raise ValueError("Message is no longer pending")
    return PendingChatMessage(
        id=row.message_id,
        message=row.content,
        delivery=row.delivery,
        target_response_id=row.target_response_id,
    )


def _locked_human_input(
    session: Session, chat_session_id: UUID, message_id: str
) -> ChatInput:
    lock_agent(session, str(chat_session_id))
    row = session.scalar(
        _pending_human_inputs(chat_session_id)
        .where(ChatInput.message_id == message_id)
        .with_for_update(of=ChatInput)
    )
    if row is None:
        raise OnyxError(OnyxErrorCode.CONFLICT, "This message is no longer pending")
    return row


def submit_human_message__no_commit(
    session: Session,
    chat_session_id: UUID,
    *,
    message: str,
    delivery: MessageDelivery,
    target_response_id: int | None,
) -> PendingChatMessage:
    """Store text after authorization. Only `send` binds to a running response.

    A send without a target goes to the selected response. A send to a response
    that no longer accepts input waits in the queue instead.
    """
    lock_agent(session, str(chat_session_id))
    selected, branch = get_selected_branch(session, chat_session_id)
    target = selected
    if target_response_id is not None and (
        selected is None or target_response_id != selected.id
    ):
        target = session.get(ChatMessage, target_response_id)
        if (
            target is None
            or target.chat_session_id != chat_session_id
            or target.message_type != MessageType.ASSISTANT
        ):
            raise OnyxError(
                OnyxErrorCode.CONFLICT, "The target is not a current response"
            )
        # A running sibling of the selected response can still receive a send;
        # any other target must be on the selected branch.
        if (
            target.response_status in _ACCEPTING_STATUSES
            and (
                selected is None
                or target.parent_message_id != selected.parent_message_id
            )
        ) or (
            target.response_status not in _ACCEPTING_STATUSES
            and target.id not in branch.message_ids
        ):
            raise OnyxError(
                OnyxErrorCode.CONFLICT, "The target is not a current response"
            )
    if delivery == MessageDelivery.SEND and (
        target is None or target.response_status not in _ACCEPTING_STATUSES
    ):
        delivery = MessageDelivery.QUEUE
    pending_count = session.scalar(
        select(func.count()).select_from(
            _pending_human_inputs(chat_session_id).subquery()
        )
    )
    if pending_count is not None and pending_count >= MAX_PENDING_MESSAGES:
        raise OnyxError(OnyxErrorCode.INVALID_INPUT, "Chat message queue is full")
    row = ChatInput(
        recipient_session_id=chat_session_id,
        message_id=str(uuid4()),
        source=InputSource.HUMAN,
        target_response_id=target.id
        if delivery == MessageDelivery.SEND and target is not None
        else None,
        delivery=delivery,
        content=_pending_content(message),
    )
    session.add(row)
    session.flush()
    return _pending_human_message(row)


def has_chat_inputs(session: Session, chat_session_id: UUID) -> bool:
    """Whether any inbox row belongs to this conversation.

    Without one, the conversation has no queued turn.
    """
    return bool(
        session.scalar(
            select(
                select(ChatInput.id)
                .where(ChatInput.recipient_session_id == chat_session_id)
                .exists()
            )
        )
    )


def list_human_messages(
    session: Session, chat_session_id: UUID
) -> list[PendingChatMessage]:
    return [
        _pending_human_message(row)
        for row in session.scalars(_pending_human_inputs(chat_session_id))
    ]


def withdraw_human_message__no_commit(
    session: Session, chat_session_id: UUID, message_id: str
) -> PendingChatMessage:
    """Withdraw before acceptance; callers commit before returning text to an editor."""
    row = _locked_human_input(session, chat_session_id, message_id)
    pending = _pending_human_message(row)
    session.delete(row)
    return pending


def interrupt_human_message__no_commit(
    session: Session, chat_session_id: UUID, message_id: str
) -> PendingChatMessage:
    """Make the message start next, after the caller stops current work."""
    row = _locked_human_input(session, chat_session_id, message_id)
    row.delivery = MessageDelivery.INTERRUPT
    session.flush()
    return _pending_human_message(row)


def next_queued_turn(
    session: Session,
    chat_session_id: UUID,
    selected: ChatMessage | None,
    branch: ChatBranch,
) -> QueuedChatTurn | None:
    """Read the next root turn on the selected branch from `get_selected_branch`.

    Acceptance rechecks the turn under the session lock.
    """
    if selected is None and len(branch.message_ids) > 1:
        # Only the root message, or a response, can precede the next question.
        return None
    # Responses saved before status tracking have no status but are finished.
    status = (
        None if selected is None else selected.response_status or RunStatus.COMPLETE
    )
    row = session.scalar(
        _pending_human_inputs(chat_session_id)
        .order_by(None)
        .order_by(
            (ChatInput.delivery == MessageDelivery.INTERRUPT).desc(), ChatInput.id
        )
        .limit(1)
    )
    if row is None or not can_start_input(row.delivery, row.target_response_id, status):
        return None
    return QueuedChatTurn(
        parent_response_id=selected.id if selected is not None else None,
        message=_pending_human_message(row),
    )


def read_chat_inbox(session: Session, chat_session_id: UUID) -> ChatInbox:
    """Read the selected branch and the next turn that can start on it.

    The next root turn starts through chat admission.
    """
    selected, branch = get_selected_branch(session, chat_session_id)
    inbox = ChatInbox(
        branch=branch, selected_response_id=selected.id if selected else None
    )
    # Only conversations with inbox rows have queued turns.
    if not has_chat_inputs(session, chat_session_id):
        return inbox
    if selected is not None and selected.response_status == RunStatus.RUNNING:
        inbox.running_response_ids.append(selected.id)
    inbox.next_turn = next_queued_turn(session, chat_session_id, selected, branch)
    return inbox


def accept_queued_turn__no_commit(
    session: Session, chat_session_id: UUID, turn: QueuedChatTurn
) -> None:
    """Consume the expected turn in the transaction that starts it."""
    lock_agent(session, str(chat_session_id))
    selected, branch = get_selected_branch(session, chat_session_id)
    current = next_queued_turn(session, chat_session_id, selected, branch)
    if (
        current is None
        or current.parent_response_id != turn.parent_response_id
        or current.message.id != turn.message.id
    ):
        raise OnyxError(
            OnyxErrorCode.CONFLICT, "The queued chat input is no longer next"
        )
    session.execute(
        delete(ChatInput).where(
            ChatInput.recipient_session_id == chat_session_id,
            ChatInput.message_id == turn.message.id,
            ChatInput.source == InputSource.HUMAN,
        )
    )


def _sends(run_id: int) -> ColumnElement[bool]:
    """Messages a running response reads."""
    return (ChatInput.target_response_id == run_id) & (
        ChatInput.delivery == MessageDelivery.SEND
    )


def read_run_inputs(session: Session, agent_id: str, run_id: str) -> list[UserMessage]:
    """Read messages sent to a run."""
    return [
        UserMessage(
            id=row.message_id,
            content=row.content,
            metadata=InputMessageMetadata(source=row.source),
        )
        for row in session.scalars(
            select(ChatInput)
            .where(
                ChatInput.recipient_session_id == UUID(agent_id),
                _sends(int(run_id)),
            )
            .order_by(ChatInput.id)
        )
    ]


def consume_inputs__no_commit(
    session: Session,
    run_id: int,
    messages: list[UserMessage],
    *,
    ownership_version: int | None,
) -> bool:
    """Delete the pending rows of a step's inputs; false when one is gone.

    The caller writes the step's accepted inputs in this transaction, so each
    pending message is accepted exactly once.
    """
    response = session.get(ChatMessage, run_id)
    if response is None:
        raise ValueError("Response is unavailable")
    lock_agent(session, str(response.chat_session_id))
    check_checkpoint_owner__no_commit(session, run_id, ownership_version)
    pending_ids = {
        message.id
        for message in messages
        if isinstance(message.metadata, InputMessageMetadata) and message.id is not None
    }
    if not pending_ids:
        return True
    consumed = session.scalars(
        delete(ChatInput)
        .where(
            ChatInput.recipient_session_id == response.chat_session_id,
            ChatInput.message_id.in_(pending_ids),
            _sends(run_id),
        )
        .returning(ChatInput.message_id)
    ).all()
    return set(consumed) == pending_ids


def has_pending_sends(session: Session, agent_id: str, run_id: int) -> bool:
    """Read unreceived steering; a send that misses its run starts the next one."""
    return (
        session.scalar(
            select(ChatInput.id)
            .where(
                ChatInput.recipient_session_id == UUID(agent_id),
                _sends(run_id),
            )
            .limit(1)
        )
        is not None
    )


def fail_response_start__no_commit(session: Session, response_id: int) -> None:
    """Record that reserved work could not start, so it does not retry forever."""
    response = session.get(ChatMessage, response_id)
    if (
        response is None
        or response.response_items
        or response.response_status not in (None, RunStatus.RUNNING)
    ):
        return
    response.response_status = RunStatus.ERROR
    response.response_failure = RunFailure(
        kind=RunFailureKind.EXECUTION,
        message="The response could not start",
    )
