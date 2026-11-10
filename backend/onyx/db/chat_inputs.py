"""Chat input storage. Callers own transactions and response leases."""

from collections.abc import Collection, Sequence
from uuid import UUID, uuid4

from sqlalchemy import Select, func, select, update
from sqlalchemy.orm import Session, aliased, load_only

from onyx.agents.models import (
    AgentInfo,
    AgentMessageReceipt,
    AgentMessageRequest,
    AgentMessageStatus,
    BackgroundDelegation,
    InputMessageMetadata,
    InputSource,
    MessageDelivery,
    RunFailure,
    RunFailureKind,
    RunStatus,
)
from onyx.chat.models import ChatBranch, PendingChatMessage
from onyx.configs.constants import MessageType
from onyx.db.chat import (
    configure_response_transaction__no_commit,
    get_owned_chat_session,
    get_selected_response,
    root_response_id,
    session_ancestors,
    visible_message_ids,
)
from onyx.db.chat_checkpoint import check_checkpoint_owner__no_commit
from onyx.db.chat_response import (
    read_response_input,
    reserve_agent_continuation__no_commit,
    reserve_child_response__no_commit,
)
from onyx.db.chat_subagents import (
    _agent_metadata,
    _selected_responses,
    _visible_agent,
    unread_agent_result_ids,
)
from onyx.db.models import (
    ChatInput,
    ChatMessage,
    ChatResponseItem,
    ChatSession,
    ToolCall,
)
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.llm.models import UserMessage
from onyx.utils.postgres_sanitization import sanitize_string

MAX_PENDING_MESSAGES = 64


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


def cancel_completed_responses__no_commit(
    session: Session, chat_session_id: UUID, response_ids: Collection[int]
) -> None:
    """Preserve a late Stop after terminal output is saved; the caller commits."""
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
    session: Session, chat_session_id: UUID, user_id: UUID
) -> ChatSession:
    """Authorize durable user input without granting shared-session write access."""
    chat_session = get_owned_chat_session(chat_session_id, user_id, session)
    if chat_session is None or chat_session.deleted:
        raise LookupError("Chat session is unavailable")
    if chat_session.incognito_record_mode is not None:
        raise ValueError("Pending messages are unavailable in incognito chats")
    return chat_session


def _pending_human_inputs(chat_session_id: UUID) -> Select[tuple[ChatInput]]:
    return (
        select(ChatInput)
        .where(
            ChatInput.recipient_session_id == chat_session_id,
            ChatInput.source == InputSource.HUMAN,
            ChatInput.response_item_id.is_(None),
        )
        .order_by(ChatInput.id)
    )


def _pending_human_message(row: ChatInput) -> PendingChatMessage:
    if row.delivery is None or row.response_item_id is not None:
        raise ValueError("Message is no longer pending")
    return PendingChatMessage(
        id=row.message_id,
        message=row.content,
        delivery=row.delivery,
        target_response_id=row.target_response_id,
    )


def submit_human_message__no_commit(
    session: Session,
    chat_session_id: UUID,
    user_id: UUID,
    *,
    message: str,
    delivery: MessageDelivery,
    target_response_id: int | None,
) -> PendingChatMessage:
    """Submit text on the selected branch. The caller commits the pending row."""
    get_human_input_session(session, chat_session_id, user_id)
    lock_agent(session, str(chat_session_id))
    selected = get_selected_response(session, chat_session_id)
    if target_response_id is None:
        has_messages = session.scalar(
            select(ChatMessage.id)
            .where(
                ChatMessage.chat_session_id == chat_session_id,
                ChatMessage.message_type == MessageType.USER,
            )
            .limit(1)
        )
        if has_messages is not None:
            raise ValueError("Select a response before submitting another message")
    elif selected is None or selected.id != target_response_id:
        raise ValueError("The target must be the selected branch's last response")
    if selected is not None and selected.response_status is None:
        raise OnyxError(
            OnyxErrorCode.CONFLICT,
            "This response cannot accept pending messages; send a new chat message instead",
        )
    if delivery == MessageDelivery.SEND and (
        selected is None
        or selected.response_status not in (RunStatus.RUNNING, RunStatus.SUSPENDED)
        or selected.response_inputs_closed
    ):
        raise OnyxError(
            OnyxErrorCode.CONFLICT,
            "The response no longer accepts messages; send a new chat message instead",
        )
    pending_count = session.scalar(
        select(func.count()).select_from(
            _pending_human_inputs(chat_session_id).subquery()
        )
    )
    if pending_count is not None and pending_count >= MAX_PENDING_MESSAGES:
        raise ValueError("Chat message queue is full")
    content = sanitize_string(message)
    if not content.strip():
        raise ValueError("Message cannot be empty")
    row = ChatInput(
        recipient_session_id=chat_session_id,
        message_id=str(uuid4()),
        source=InputSource.HUMAN,
        source_response_id=target_response_id,
        target_response_id=target_response_id,
        delivery=delivery,
        content=content,
    )
    session.add(row)
    session.flush()
    return _pending_human_message(row)


def list_human_messages(
    session: Session, chat_session_id: UUID, user_id: UUID
) -> list[PendingChatMessage]:
    get_human_input_session(session, chat_session_id, user_id)
    return [
        _pending_human_message(row)
        for row in session.scalars(_pending_human_inputs(chat_session_id))
    ]


def withdraw_human_message__no_commit(
    session: Session, chat_session_id: UUID, user_id: UUID, message_id: str
) -> PendingChatMessage | None:
    """Withdraw before acceptance; callers commit before returning text to an editor."""
    get_human_input_session(session, chat_session_id, user_id)
    lock_agent(session, str(chat_session_id))
    row = session.scalar(
        _pending_human_inputs(chat_session_id)
        .where(ChatInput.message_id == message_id)
        .with_for_update(of=ChatInput)
    )
    if row is None:
        return None
    pending = _pending_human_message(row)
    session.delete(row)
    return pending


def interrupt_human_message__no_commit(
    session: Session,
    chat_session_id: UUID,
    user_id: UUID,
    message_id: str,
    target_response_id: int | None,
) -> PendingChatMessage:
    """Promote existing input without racing acceptance or stopping another branch."""
    get_human_input_session(session, chat_session_id, user_id)
    lock_agent(session, str(chat_session_id))
    row = session.scalar(
        _pending_human_inputs(chat_session_id)
        .where(ChatInput.message_id == message_id)
        .with_for_update(of=ChatInput)
    )
    if row is None:
        raise OnyxError(OnyxErrorCode.CONFLICT, "This message is no longer pending")
    if row.target_response_id != target_response_id:
        raise OnyxError(
            OnyxErrorCode.CONFLICT, "This message now targets another response"
        )
    selected = get_selected_response(session, chat_session_id)
    if row.target_response_id != (selected.id if selected else None):
        raise OnyxError(
            OnyxErrorCode.CONFLICT, "This message belongs to another response branch"
        )
    if selected is not None and selected.response_status is None:
        raise OnyxError(
            OnyxErrorCode.CONFLICT, "This response cannot accept pending messages"
        )
    row.delivery = MessageDelivery.INTERRUPT
    session.flush()
    return _pending_human_message(row)


def has_pending_human_interrupt(
    session: Session, chat_session_id: UUID, response_ids: Collection[int]
) -> bool:
    """Read durable interrupt intent for the responses owned by a live turn."""
    configure_response_transaction__no_commit(session)
    return bool(
        session.scalar(
            _pending_human_inputs(chat_session_id)
            .where(
                ChatInput.delivery == MessageDelivery.INTERRUPT,
                ChatInput.target_response_id.in_(response_ids),
            )
            .exists()
            .select()
        )
    )


def pending_human_message__no_commit(
    session: Session, chat_session_id: UUID, user_id: UUID
) -> PendingChatMessage | None:
    """Read an eligible next turn; acceptance rechecks under the session lock."""
    get_human_input_session(session, chat_session_id, user_id)
    query = _pending_human_inputs(chat_session_id).where(
        ChatInput.delivery.in_((MessageDelivery.QUEUE, MessageDelivery.INTERRUPT)),
    )
    if session.scalar(query.with_only_columns(ChatInput.id).limit(1)) is None:
        return None
    selected = get_selected_response(session, chat_session_id)
    if selected is not None:
        if selected.response_status is None or not selected.response_status.is_terminal:
            return None
        if selected.response_status != RunStatus.COMPLETE:
            query = query.where(ChatInput.delivery == MessageDelivery.INTERRUPT)
    if (
        selected is None
        and session.scalar(
            select(ChatMessage.id)
            .where(
                ChatMessage.chat_session_id == chat_session_id,
                ChatMessage.message_type == MessageType.USER,
            )
            .limit(1)
        )
        is not None
    ):
        return None
    query = query.where(
        ChatInput.target_response_id == (selected.id if selected else None)
    )
    row = session.scalar(
        query.order_by(None)
        .order_by(
            (ChatInput.delivery == MessageDelivery.INTERRUPT).desc(), ChatInput.id
        )
        .limit(1)
    )
    return _pending_human_message(row) if row is not None else None


def pending_agent_result_response(
    session: Session, chat_session_id: UUID, user_id: UUID
) -> int | None:
    """Select an idle root that has unread child output; callers claim admission."""
    get_human_input_session(session, chat_session_id, user_id)
    selected = get_selected_response(session, chat_session_id)
    if selected is None or selected.response_status != RunStatus.COMPLETE:
        return None
    if pending_human_message__no_commit(session, chat_session_id, user_id) is not None:
        return None
    branch = ChatBranch(
        chat_session_id=chat_session_id,
        message_ids=visible_message_ids(session, selected),
    )
    return (
        selected.id
        if unread_agent_result_ids(session, branch, str(chat_session_id))
        else None
    )


def fail_agent_result_response__no_commit(
    session: Session,
    chat_session_id: UUID,
    user_id: UUID,
    expected_response_id: int,
) -> None:
    """Record one failed automatic response; the caller holds chat admission."""
    lock_agent(session, str(chat_session_id))
    if (
        pending_agent_result_response(session, chat_session_id, user_id)
        != expected_response_id
    ):
        return
    previous = session.get(ChatMessage, expected_response_id)
    if previous is None:
        raise ValueError("Completed response disappeared during reservation")
    response_id = reserve_agent_continuation__no_commit(session, previous)
    fail_reserved_message(session, response_id)


def accept_human_message__no_commit(
    session: Session, chat_session_id: UUID, user_id: UUID, message_id: str
) -> PendingChatMessage | None:
    """Adopt the next instruction in the transaction that creates its user message."""
    get_human_input_session(session, chat_session_id, user_id)
    lock_agent(session, str(chat_session_id))
    pending = pending_human_message__no_commit(session, chat_session_id, user_id)
    if pending is None or pending.id != message_id:
        return None
    row = session.scalar(
        _pending_human_inputs(chat_session_id)
        .where(ChatInput.message_id == message_id)
        .with_for_update(of=ChatInput)
    )
    if row is None:
        return None
    session.delete(row)
    return pending


def pending_inputs(
    session: Session, branch: ChatBranch, agent_id: str | None = None
) -> list[ChatInput]:
    selected = _selected_responses(branch)
    query = (
        select(ChatInput)
        .join(ToolCall, ChatInput.invoking_tool_call_id == ToolCall.id)
        .where(
            ChatInput.response_item_id.is_(None),
            ToolCall.parent_chat_message_id.in_(select(selected.c.id)),
        )
        .order_by(ChatInput.id)
    )
    if agent_id is not None:
        _visible_agent(session, branch, agent_id)
        query = query.where(ChatInput.recipient_session_id == UUID(agent_id))
    return list(session.scalars(query))


def latest_agent_response(
    session: Session, branch: ChatBranch, agent_id: str
) -> ChatMessage | None:
    return latest_agent_responses(session, branch, [agent_id]).get(agent_id)


def latest_agent_responses(
    session: Session, branch: ChatBranch, agent_ids: Collection[str]
) -> dict[str, ChatMessage]:
    if not agent_ids:
        return {}
    selected = _selected_responses(branch)
    rows = session.scalars(
        select(ChatMessage)
        .join(selected, ChatMessage.id == selected.c.id)
        .where(
            ChatMessage.chat_session_id.in_([UUID(agent_id) for agent_id in agent_ids]),
        )
        .distinct(ChatMessage.chat_session_id)
        .order_by(ChatMessage.chat_session_id, ChatMessage.id.desc())
        .options(
            load_only(
                ChatMessage.id,
                ChatMessage.chat_session_id,
                ChatMessage.response_status,
                ChatMessage.response_inputs_closed,
            )
        )
    )
    return {str(row.chat_session_id): row for row in rows}


def message_receipt(row: ChatInput) -> AgentMessageReceipt:
    if row.delivery is None or row.response_item_id is not None:
        raise ValueError("Message is no longer pending")
    return AgentMessageReceipt(
        id=row.message_id,
        agent_id=str(row.recipient_session_id),
        status=AgentMessageStatus.PENDING,
        run_id=str(row.target_response_id)
        if row.target_response_id is not None
        else None,
        message=row.content,
        delivery=row.delivery,
    )


def enqueue_message(
    session: Session, branch: ChatBranch, request: AgentMessageRequest
) -> AgentMessageReceipt:
    if not isinstance(request.message.content, str):
        raise ValueError("Agent messages must contain text only")
    recipient = lock_agent(session, request.agent_id)
    if len(pending_inputs(session, branch, request.agent_id)) >= MAX_PENDING_MESSAGES:
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
    target_id = (
        latest.id
        if latest is not None
        and (
            request.delivery == MessageDelivery.QUEUE
            or (
                latest.response_status in (None, RunStatus.RUNNING, RunStatus.SUSPENDED)
                and not latest.response_inputs_closed
            )
        )
        else None
    )
    if recipient.restoration_config is None and (
        request.delivery == MessageDelivery.QUEUE or target_id is None
    ):
        raise ValueError(
            "This agent cannot start another run after its resources are released"
        )
    row = ChatInput(
        recipient_session_id=UUID(request.agent_id),
        message_id=request.message.id or str(uuid4()),
        source=InputSource.AGENT,
        invoking_tool_call_id=invocation.id,
        target_response_id=target_id,
        delivery=request.delivery,
        content=sanitize_string(request.message.content),
        max_steps=request.max_steps,
        total_timeout_s=request.total_timeout_s,
    )
    session.add(row)
    session.flush()
    return message_receipt(row)


def receive_messages(
    session: Session,
    agent_id: str,
    run_id: str,
    received_ids: Collection[str],
) -> list[UserMessage]:
    rows = session.scalars(
        select(ChatInput)
        .where(
            ChatInput.recipient_session_id == UUID(agent_id),
            ChatInput.target_response_id == int(run_id),
            ChatInput.delivery == MessageDelivery.SEND,
            ChatInput.response_item_id.is_(None),
            ChatInput.message_id.not_in(received_ids),
        )
        .order_by(ChatInput.id)
    )
    return [read_response_input(row) for row in rows]


def inputs_available(
    session: Session,
    run_id: int,
    messages: list[UserMessage],
    *,
    ownership_version: int | None,
) -> bool:
    """Lock the recipient before its response, then check ownership and pending input."""
    response = session.get(ChatMessage, run_id)
    if response is None:
        raise ValueError("Response is unavailable")
    lock_agent(session, str(response.chat_session_id))
    check_checkpoint_owner__no_commit(session, run_id, ownership_version)
    for message in messages:
        origin = message.metadata
        if not isinstance(origin, InputMessageMetadata) or (
            origin.source != InputSource.AGENT
            and not (
                origin.source == InputSource.HUMAN and origin.source_run_id is not None
            )
        ):
            continue
        row = session.scalar(
            select(ChatInput)
            .where(
                ChatInput.recipient_session_id == response.chat_session_id,
                ChatInput.message_id == message.id,
                ChatInput.target_response_id == run_id,
            )
            .with_for_update(of=ChatInput)
        )
        if row is None or row.delivery != MessageDelivery.SEND:
            return False
    return True


def close_response_inputs(
    session: Session,
    response_id: int,
    *,
    can_continue: bool,
    ownership_version: int | None,
) -> bool:
    """Close admission under the same recipient-first lock order as submission."""
    response = session.get(ChatMessage, response_id)
    if response is None:
        raise ValueError("Response is unavailable")
    lock_agent(session, str(response.chat_session_id))
    check_checkpoint_owner__no_commit(session, response_id, ownership_version)
    pending = (
        session.scalar(
            select(ChatInput.id)
            .where(
                ChatInput.target_response_id == response_id,
                ChatInput.delivery == MessageDelivery.SEND,
                ChatInput.response_item_id.is_(None),
            )
            .limit(1)
        )
        is not None
    )
    if not pending or not can_continue:
        response.response_inputs_closed = True
    return pending


def queued_request(row: ChatInput) -> AgentMessageRequest:
    invocation = row.invoking_tool_call
    if (
        invocation is None
        or invocation.parent_chat_message_id is None
        or row.max_steps is None
        or row.delivery not in (MessageDelivery.SEND, MessageDelivery.QUEUE)
    ):
        raise ValueError("Pending agent message has no invoking execution")
    return AgentMessageRequest(
        agent_id=str(row.recipient_session_id),
        parent_id=str(invocation.chat_session_id),
        message=UserMessage(id=row.message_id, content=row.content),
        delivery=row.delivery,
        max_steps=row.max_steps,
        total_timeout_s=row.total_timeout_s,
        parent_run_id=str(invocation.parent_chat_message_id),
        parent_message_id=f"{invocation.parent_chat_message_id}:{invocation.turn_number}",
        parent_tool_call_id=invocation.tool_call_id,
    )


def can_start_message(row: ChatInput, latest: ChatMessage | None) -> bool:
    if latest is not None and (
        latest.response_status is None or not latest.response_status.is_terminal
    ):
        return False
    if row.delivery == MessageDelivery.SEND and row.target_response_id is None:
        return True
    return latest is None or latest.response_status == RunStatus.COMPLETE


def reserve_input_response(
    session: Session, row: ChatInput, agent: AgentInfo, latest: ChatMessage | None
) -> tuple[int, int]:
    request = queued_request(row)
    parent = session.get(ChatMessage, int(request.parent_run_id))
    if parent is None:
        raise ValueError("Message sender is unavailable")
    root_id = root_response_id(session, parent)
    response_id = reserve_child_response__no_commit(
        session,
        root_id,
        agent=agent,
        instruction=request.message,
        previous_response_id=latest.id if latest else None,
        parent_response_id=int(request.parent_run_id),
        parent_message_id=request.parent_message_id,
        parent_tool_call_id=request.parent_tool_call_id,
    )
    session.delete(row)
    return response_id, root_id


def fail_reserved_message(session: Session, response_id: int) -> None:
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
        message="The agent response could not start",
    )
    response.response_inputs_closed = True


def activate_reserved_message(session: Session, response_id: int) -> None:
    response = session.get(ChatMessage, response_id)
    if response is None or response.response_status is not None:
        raise ValueError("Queued response is unavailable for execution")
    response.response_status = RunStatus.RUNNING


def fail_pending_message(
    session: Session, branch: ChatBranch, request: AgentMessageRequest
) -> None:
    agent = lock_agent(session, request.agent_id)
    row = next(
        (
            item
            for item in pending_inputs(session, branch, request.agent_id)
            if item.message_id == request.message.id
        ),
        None,
    )
    if row is None:
        return
    latest = latest_agent_response(session, branch, request.agent_id)
    if not can_start_message(row, latest):
        return
    info = _agent_metadata(
        agent,
        session_ancestors(session, [agent.id]),
        latest.id if latest else None,
        latest.response_status if latest else None,
    )
    response_id, _ = reserve_input_response(session, row, info, latest)
    fail_reserved_message(session, response_id)


def resolve_delegation_messages(
    session: Session,
    parent_response_id: int,
    delegations: Sequence[BackgroundDelegation],
) -> dict[str, str | None]:
    """Resolve current-run instructions, including those moved into child history."""
    messages = {
        item.message_id: item for item in delegations if item.message_id is not None
    }
    rows = session.execute(
        select(ChatInput.message_id, ChatResponseItem.chat_message_id)
        .join(ToolCall, ToolCall.id == ChatInput.invoking_tool_call_id)
        .outerjoin(ChatResponseItem, ChatResponseItem.id == ChatInput.response_item_id)
        .where(
            ToolCall.parent_chat_message_id == parent_response_id,
            ChatInput.source == InputSource.AGENT,
            ChatInput.message_id.in_(messages),
        )
    )
    resolved = {
        message_id: str(response_id) if response_id is not None else None
        for message_id, response_id in rows
    }
    missing = {
        message_id: item
        for message_id, item in messages.items()
        if message_id not in resolved
    }
    if not missing:
        return resolved
    question = aliased(ChatMessage)
    response = aliased(ChatMessage)
    rows = session.execute(
        select(ToolCall.tool_call_id, question.chat_session_id, response.id)
        .join(question, question.invoking_tool_call_id == ToolCall.id)
        .join(response, response.parent_message_id == question.id)
        .where(
            ToolCall.parent_chat_message_id == parent_response_id,
            ToolCall.tool_call_id.in_([item.tool_call_id for item in missing.values()]),
            question.message_type == MessageType.USER,
            response.message_type == MessageType.ASSISTANT,
        )
    )
    for call_id, agent_id, response_id in rows:
        for message_id, item in missing.items():
            if item.tool_call_id != call_id or item.agent_id != str(agent_id):
                continue
            if message_id in resolved:
                raise ValueError("Delegated instruction has ambiguous child history")
            resolved[message_id] = str(response_id)
    return resolved
