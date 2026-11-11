"""Pending agent and human messages. Callers own transactions and response leases.

A row is pending until a step or a new run consumes it; consuming deletes it.
"""

from collections.abc import Collection, Iterable
from uuid import UUID, uuid4

from sqlalchemy import Select, and_, delete, func, or_, select, update
from sqlalchemy.orm import Session, selectinload
from sqlalchemy.sql.elements import ColumnElement

from onyx.agents.models import (
    AgentInfo,
    AgentMessageReceipt,
    AgentMessageRequest,
    InputMessageMetadata,
    InputSource,
    MessageDelivery,
    RunFailure,
    RunFailureKind,
    RunStatus,
)
from onyx.chat.models import (
    AgentInboxWork,
    AgentResultState,
    ChatBranch,
    PendingChatMessage,
    QueuedChatTurn,
)
from onyx.configs.constants import MessageType
from onyx.db.chat import (
    agent_session_path,
    configure_response_transaction__no_commit,
    get_owned_chat_session,
    get_selected_branch,
    parent_session_id,
    response_invocation,
    root_response_id,
    session_ancestors,
)
from onyx.db.chat_checkpoint import check_checkpoint_owner__no_commit
from onyx.db.chat_response import reserve_child_response__no_commit
from onyx.db.chat_subagents import (
    agent_metadata,
    latest_agent_response,
    visible_agent,
)
from onyx.db.models import (
    ChatInput,
    ChatMessage,
    ChatResponseItem,
    ChatSession,
    ToolCall,
    User,
)
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.llm.models import UserMessage
from onyx.utils.postgres_sanitization import sanitize_string

MAX_PENDING_MESSAGES = 64
# A reserved response has no status until its run starts.
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


def wakes_for_results(
    latest_status: RunStatus | None, results: Iterable[AgentResultState]
) -> bool:
    """Whether unread finished results start an idle agent's next run."""
    return (
        latest_status is not None
        and latest_status.is_terminal
        and not _pauses_queue(latest_status)
        and any(result.status.is_terminal for result in results)
    )


def agent_run_status(latest: ChatMessage | None) -> RunStatus | None:
    """A child's latest status; a reserved response counts as running."""
    if latest is None:
        return None
    return latest.response_status or RunStatus.RUNNING


def cancel_completed_responses__no_commit(
    session: Session, chat_session_id: UUID, response_ids: Collection[int]
) -> None:
    """Save a Stop that arrived after the answer finished; it pauses the queue."""
    lock_agent(session, str(chat_session_id))
    session.execute(
        update(ChatMessage)
        .where(
            ChatMessage.chat_session_id == chat_session_id,
            ChatMessage.message_type == MessageType.ASSISTANT,
            ChatMessage.response_status == RunStatus.COMPLETE,
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
    selected, _ = get_selected_branch(session, chat_session_id)
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
        # A running response that the selected turn does not show is another branch's.
        if target.response_status in _ACCEPTING_STATUSES and (
            selected is None or target.parent_message_id != selected.parent_message_id
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
        content=sanitize_string(message),
    )
    session.add(row)
    session.flush()
    return _pending_human_message(row)


def has_chat_inputs(session: Session, chat_session_id: UUID) -> bool:
    """Whether any inbox row belongs to this conversation, including its agents.

    Without one, the conversation has no queued turn and no running child.
    """
    addressed = (
        select(ChatInput.id)
        .where(ChatInput.recipient_session_id == chat_session_id)
        .exists()
    )
    descendant = (
        select(ChatInput.id)
        .join(ChatMessage, ChatMessage.id == ChatInput.root_response_id)
        .where(ChatMessage.chat_session_id == chat_session_id)
        .exists()
    )
    return bool(session.scalar(select(or_(addressed, descendant))))


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
    results: Iterable[AgentResultState],
) -> QueuedChatTurn | None:
    """Read the next root turn on the selected branch from `get_selected_branch`.

    `results` are the branch's unread child results; those for the root wake it.
    Acceptance rechecks the turn under the session lock.
    """
    if selected is None and len(branch.message_ids) > 1:
        # Only the root message, or a response, can precede the next question.
        return None
    # Responses saved before status tracking have no status but are finished.
    status = (
        None if selected is None else selected.response_status or RunStatus.COMPLETE
    )
    parent_response_id = selected.id if selected is not None else None
    row = session.scalar(
        _pending_human_inputs(chat_session_id)
        .order_by(None)
        .order_by(
            (ChatInput.delivery == MessageDelivery.INTERRUPT).desc(), ChatInput.id
        )
        .limit(1)
    )
    if row is not None and can_start_input(
        row.delivery, row.target_response_id, status
    ):
        return QueuedChatTurn(
            parent_response_id=parent_response_id,
            message=_pending_human_message(row),
        )
    if wakes_for_results(
        status, (result for result in results if result.recipient_id == chat_session_id)
    ):
        return QueuedChatTurn(parent_response_id=parent_response_id, message=None)
    return None


def accept_queued_turn__no_commit(
    session: Session, chat_session_id: UUID, turn: QueuedChatTurn
) -> None:
    """Consume the expected turn in the transaction that starts it."""
    lock_agent(session, str(chat_session_id))
    selected, branch = get_selected_branch(session, chat_session_id)
    current = next_queued_turn(
        session,
        chat_session_id,
        selected,
        branch,
        agent_result_states(session, branch.message_ids, chat_session_id),
    )
    if (
        current is None
        or current.parent_response_id != turn.parent_response_id
        or (current.message.id if current.message else None)
        != (turn.message.id if turn.message else None)
    ):
        raise OnyxError(
            OnyxErrorCode.CONFLICT, "The queued chat input is no longer next"
        )
    if turn.message is not None:
        session.execute(
            delete(ChatInput).where(
                ChatInput.recipient_session_id == chat_session_id,
                ChatInput.message_id == turn.message.id,
                ChatInput.source == InputSource.HUMAN,
            )
        )


def agent_result_states(
    session: Session,
    visible_ids: Collection[int],
    recipient_id: UUID | None = None,
) -> list[AgentResultState]:
    """Unread child results whose spawning root response is on the branch."""
    query = (
        select(
            ChatInput.recipient_session_id.label("recipient_id"),
            ChatMessage.id.label("response_id"),
            ChatMessage.response_status.label("status"),
        )
        .join(ChatMessage, ChatMessage.id == ChatInput.source_response_id)
        .where(
            ChatInput.source == InputSource.AGENT_RESULT,
            ChatInput.root_response_id.in_(visible_ids),
            # A reserved response that never started has no result to wait for.
            ChatMessage.response_status.is_not(None),
        )
        .order_by(ChatInput.id)
    )
    if recipient_id is not None:
        query = query.where(ChatInput.recipient_session_id == recipient_id)
    return [
        AgentResultState.model_validate(row)
        for row in session.execute(query).mappings()
    ]


def withdraw_agent_result__no_commit(session: Session, response_id: int) -> None:
    """Drop an interrupted run's result unless the run already finished.

    The recipient's lock orders this against the step that would accept it.
    """
    recipient_id = session.scalar(
        select(ChatInput.recipient_session_id).where(
            ChatInput.source == InputSource.AGENT_RESULT,
            ChatInput.source_response_id == response_id,
        )
    )
    if recipient_id is None:
        return
    lock_agent(session, str(recipient_id))
    status = session.scalar(
        select(ChatMessage.response_status).where(ChatMessage.id == response_id)
    )
    if status is not None and status.is_terminal:
        return
    session.execute(
        delete(ChatInput).where(
            ChatInput.source == InputSource.AGENT_RESULT,
            ChatInput.source_response_id == response_id,
        )
    )


def _branch_pending_inputs(
    session: Session, branch: ChatBranch, agent_id: str | None = None
) -> Select[tuple[ChatInput]]:
    """Agent messages whose sender's root response is on the branch."""
    query = (
        select(ChatInput)
        .where(
            ChatInput.source == InputSource.AGENT,
            ChatInput.root_response_id.in_(branch.message_ids),
        )
        .order_by(ChatInput.id)
    )
    if agent_id is not None:
        visible_agent(session, branch, agent_id)
        query = query.where(ChatInput.recipient_session_id == UUID(agent_id))
    return query


def pending_inputs(
    session: Session, branch: ChatBranch, agent_id: str | None = None
) -> list[ChatInput]:
    return list(
        session.scalars(
            _branch_pending_inputs(session, branch, agent_id).options(
                selectinload(ChatInput.invoking_tool_call)
            )
        )
    )


def enqueue_message(
    session: Session,
    branch: ChatBranch,
    request: AgentMessageRequest,
    root_message_id: int,
) -> AgentMessageReceipt:
    if not isinstance(request.message.content, str):
        raise ValueError("Agent messages must contain text only")
    if request.agent_id == request.parent_id:
        raise ValueError("An agent cannot message itself")
    recipient = lock_agent(session, request.agent_id)
    pending_count = session.scalar(
        select(func.count()).select_from(
            _branch_pending_inputs(session, branch, request.agent_id).subquery()
        )
    )
    if pending_count is not None and pending_count >= MAX_PENDING_MESSAGES:
        raise ValueError("Agent message queue is full")
    invocation = session.scalar(
        select(ToolCall)
        .join(
            ChatResponseItem,
            (ChatResponseItem.chat_message_id == ToolCall.parent_chat_message_id)
            & (ChatResponseItem.step_index == ToolCall.turn_number),
        )
        .where(
            ToolCall.parent_chat_message_id == int(request.parent_run_id),
            ToolCall.tool_call_id == request.parent_tool_call_id,
            ChatResponseItem.id == request.parent_message_id,
            ToolCall.chat_session_id == UUID(request.parent_id),
        )
    )
    if invocation is None:
        raise ValueError("Agent message has no saved invoking tool")
    latest = latest_agent_response(session, branch, request.agent_id)
    accepting = latest is not None and latest.response_status in _ACCEPTING_STATUSES
    if recipient.spawned_by_message_id is None:
        # The root reads agent messages at its next step and never starts a run for them.
        delivery = MessageDelivery.SEND
        target_id = None
    else:
        delivery = request.delivery
        target_id = (
            latest.id
            if latest is not None and (delivery == MessageDelivery.QUEUE or accepting)
            else None
        )
        if recipient.restoration_config is None and (
            delivery == MessageDelivery.QUEUE or target_id is None
        ):
            raise ValueError(
                "This agent cannot start another run after its resources are released"
            )
    content = sanitize_string(request.message.content)
    if parent_session_id(session, recipient) != UUID(request.parent_id):
        sender = session.get(ChatSession, UUID(request.parent_id))
        if sender is None:
            raise ValueError("Message sender is unavailable")
        content = (
            f"Message from agent {agent_session_path(session, sender)} "
            f"(agent_id: {sender.id}):\n{content}"
        )
    row = ChatInput(
        recipient_session_id=UUID(request.agent_id),
        message_id=request.message.id or str(uuid4()),
        source=InputSource.AGENT,
        invoking_tool_call_id=invocation.id,
        source_response_id=invocation.parent_chat_message_id,
        target_response_id=target_id,
        root_response_id=root_message_id,
        delivery=delivery,
        content=content,
        max_steps=request.max_steps,
        total_timeout_s=request.total_timeout_s,
    )
    session.add(row)
    session.flush()
    return AgentMessageReceipt(
        id=row.message_id,
        run_id=str(latest.id)
        if latest is not None and (target_id is not None or accepting)
        else None,
    )


def _sends(run_id: int, root_branch: Collection[int] | None) -> ColumnElement[bool]:
    """Messages a running agent reads; the root also reads untargeted agent messages."""
    targeted = and_(
        ChatInput.target_response_id == run_id,
        ChatInput.delivery == MessageDelivery.SEND,
    )
    if root_branch is None:
        return targeted
    return or_(
        targeted,
        and_(
            ChatInput.source == InputSource.AGENT,
            ChatInput.target_response_id.is_(None),
            ChatInput.root_response_id.in_(root_branch),
        ),
    )


def read_run_inputs(
    session: Session,
    agent_id: str,
    run_id: str,
    root_branch: Collection[int] | None,
    result_branch: Collection[int] | None,
) -> tuple[list[UserMessage], list[AgentResultState]]:
    """Read messages sent to a run and, with `result_branch`, its unread child results.

    One query reads both. Results are returned as states; the caller reads the
    output of finished ones.
    """
    reads = _sends(int(run_id), root_branch)
    if result_branch is not None:
        reads = or_(
            reads,
            and_(
                ChatInput.source == InputSource.AGENT_RESULT,
                ChatInput.root_response_id.in_(result_branch),
                # A reserved response that never started has no result to wait for.
                ChatMessage.response_status.is_not(None),
            ),
        )
    rows = session.execute(
        select(ChatInput, ChatMessage.response_status)
        .outerjoin(ChatMessage, ChatMessage.id == ChatInput.source_response_id)
        .where(ChatInput.recipient_session_id == UUID(agent_id), reads)
        .order_by(ChatInput.id)
    ).all()
    messages: list[UserMessage] = []
    results: list[AgentResultState] = []
    for row, status in rows:
        if row.source == InputSource.AGENT_RESULT:
            if row.source_response_id is None or status is None:
                raise ValueError("Agent result has no source response")
            results.append(
                AgentResultState(
                    recipient_id=row.recipient_session_id,
                    response_id=row.source_response_id,
                    status=status,
                )
            )
            continue
        messages.append(
            UserMessage(
                id=row.message_id,
                content=row.content,
                metadata=InputMessageMetadata(
                    source=row.source,
                    source_run_id=str(row.source_response_id)
                    if row.source_response_id is not None
                    else None,
                ),
            )
        )
    return messages, results


def consume_inputs__no_commit(
    session: Session,
    run_id: int,
    messages: list[UserMessage],
    visible_ids: Collection[int],
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
            or_(
                and_(
                    ChatInput.source == InputSource.AGENT_RESULT,
                    ChatInput.root_response_id.in_(visible_ids),
                ),
                _sends(run_id, visible_ids),
            ),
        )
        .returning(ChatInput.message_id)
    ).all()
    return set(consumed) == pending_ids


def has_pending_sends(
    session: Session,
    agent_id: str,
    run_id: int,
    root_branch: Collection[int] | None,
) -> bool:
    """Read unreceived steering; a send that misses its run starts the next one."""
    return (
        session.scalar(
            select(ChatInput.id)
            .where(
                ChatInput.recipient_session_id == UUID(agent_id),
                _sends(run_id, root_branch),
            )
            .limit(1)
        )
        is not None
    )


def _invocation_ids(invocation: ToolCall | None) -> tuple[str, str, str]:
    """The parent run, assistant message, and tool call identities of an invocation."""
    if invocation is None or invocation.parent_chat_message_id is None:
        raise ValueError("Agent input has no invoking execution")
    return (
        str(invocation.parent_chat_message_id),
        f"{invocation.parent_chat_message_id}:{invocation.turn_number}",
        invocation.tool_call_id,
    )


def inbox_message_work(row: ChatInput) -> AgentInboxWork:
    """A queued agent message starts its recipient's next run as its question."""
    if row.max_steps is None or row.delivery not in (
        MessageDelivery.SEND,
        MessageDelivery.QUEUE,
    ):
        raise ValueError("Pending agent message has no invoking execution")
    parent_run_id, parent_message_id, parent_tool_call_id = _invocation_ids(
        row.invoking_tool_call
    )
    return AgentInboxWork(
        agent_id=str(row.recipient_session_id),
        message=UserMessage(id=row.message_id, content=row.content),
        max_steps=row.max_steps,
        total_timeout_s=row.total_timeout_s,
        parent_run_id=parent_run_id,
        parent_message_id=parent_message_id,
        parent_tool_call_id=parent_tool_call_id,
    )


def result_follow_up(
    latest: ChatMessage, *, max_steps: int, total_timeout_s: float
) -> AgentInboxWork:
    """An idle child's next run answers its results under its latest invocation."""
    parent_run_id, parent_message_id, parent_tool_call_id = _invocation_ids(
        response_invocation(latest)
    )
    return AgentInboxWork(
        agent_id=str(latest.chat_session_id),
        message=None,
        max_steps=max_steps,
        total_timeout_s=total_timeout_s,
        parent_run_id=parent_run_id,
        parent_message_id=parent_message_id,
        parent_tool_call_id=parent_tool_call_id,
    )


def reserve_inbox_run__no_commit(
    session: Session,
    branch: ChatBranch,
    agent: AgentInfo,
    *,
    message_id: str | None,
    previous_run_id: str | None,
    parent_ids: tuple[str, str, str] | None,
) -> tuple[int, int] | None:
    """Start an idle child's next run from its inbox; None when that work changed.

    A message becomes the run's USER question and leaves the inbox. Without a
    message, the run answers its unread results under a hidden AGENT_RESULTS
    question, and its first step consumes them. The run belongs to the newer
    root response of its sender's turn and its predecessor's turn.
    """
    lock_agent(session, agent.id)
    latest = latest_agent_response(session, branch, agent.id)
    if (str(latest.id) if latest else None) != previous_run_id:
        return None
    instruction: UserMessage | None = None
    row: ChatInput | None = None
    if message_id is not None:
        row = session.scalar(
            _branch_pending_inputs(session, branch, agent.id)
            .where(ChatInput.message_id == message_id)
            .options(selectinload(ChatInput.invoking_tool_call))
        )
        if row is None or not can_start_input(
            row.delivery, row.target_response_id, agent_run_status(latest)
        ):
            return None
        ids = _invocation_ids(row.invoking_tool_call)
        instruction = UserMessage(id=row.message_id, content=row.content)
    else:
        if latest is None or not wakes_for_results(
            latest.response_status,
            agent_result_states(session, branch.message_ids, UUID(agent.id)),
        ):
            return None
        ids = _invocation_ids(response_invocation(latest))
    if parent_ids is not None and parent_ids != ids:
        raise ValueError("Agent input changed its invocation")
    parent = session.get(ChatMessage, int(ids[0]))
    if parent is None:
        raise ValueError("Message sender is unavailable")
    roots = {root_response_id(session, parent)}
    if latest is not None:
        roots.add(root_response_id(session, latest))
    if not roots <= set(branch.message_ids):
        return None
    # Both roots are on this branch, newest first, so the first is their descendant.
    root_id = min(roots, key=branch.message_ids.index)
    response_id = reserve_child_response__no_commit(
        session,
        root_id,
        agent=agent,
        instruction=instruction,
        previous_response_id=latest.id if latest else None,
        parent_response_id=int(ids[0]),
        parent_message_id=ids[1],
        parent_tool_call_id=ids[2],
        # Nothing waits on an inbox run, so its spawner receives the result.
        delivers_result=True,
    )
    if row is not None:
        session.delete(row)
    return response_id, root_id


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


def activate_reserved_message(session: Session, response_id: int) -> None:
    response = session.get(ChatMessage, response_id)
    if response is None or response.response_status is not None:
        raise ValueError("Queued response is unavailable for execution")
    response.response_status = RunStatus.RUNNING


def fail_inbox_start__no_commit(
    session: Session, branch: ChatBranch, agent_id: str, message_id: str | None
) -> None:
    """Consume inbox work that could not start, so it does not retry.

    The work becomes a failed run. When even that reservation fails, the work is
    dropped: the message, or the agent's finished results on the branch.
    """
    try:
        agent = lock_agent(session, agent_id)
        latest = latest_agent_response(session, branch, agent_id)
        reserved = reserve_inbox_run__no_commit(
            session,
            branch,
            agent_metadata(
                agent,
                session_ancestors(session, [agent.id]),
                latest.id if latest else None,
                latest.response_status if latest else None,
            ),
            message_id=message_id,
            previous_run_id=str(latest.id) if latest else None,
            parent_ids=None,
        )
        if reserved is not None:
            fail_response_start__no_commit(session, reserved[0])
        return
    except ValueError:
        session.rollback()
    lock_agent(session, agent_id)
    work = (
        and_(
            ChatInput.source == InputSource.AGENT,
            ChatInput.message_id == message_id,
        )
        if message_id is not None
        else and_(
            ChatInput.source == InputSource.AGENT_RESULT,
            ChatInput.source_response_id.in_(
                select(ChatMessage.id).where(
                    ChatMessage.response_status.in_(
                        [status for status in RunStatus if status.is_terminal]
                    )
                )
            ),
        )
    )
    session.execute(
        delete(ChatInput).where(
            ChatInput.recipient_session_id == UUID(agent_id),
            ChatInput.root_response_id.in_(branch.message_ids),
            work,
        )
    )
