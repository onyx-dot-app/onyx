"""Durable agent inbox operations. Callers own transactions and response leases."""

from collections.abc import Collection
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session, aliased, load_only

from onyx.agents.models import (
    AgentInfo,
    AgentMessageReceipt,
    AgentMessageRequest,
    AgentMessageStatus,
    InputMessageMetadata,
    InputSource,
    MessageDelivery,
    RunFailure,
    RunFailureKind,
    RunStatus,
)
from onyx.chat.models import ChatBranch
from onyx.db.chat import root_response_id, session_ancestors
from onyx.db.chat_checkpoint import check_checkpoint_owner__no_commit
from onyx.db.chat_response import (
    configure_response_transaction__no_commit,
    reserve_child_response__no_commit,
)
from onyx.db.chat_subagents import _agent_metadata, _selected_responses, _visible_agent
from onyx.db.models import (
    ChatAgentInput,
    ChatMessage,
    ChatResponseItem,
    ChatSession,
    ToolCall,
)
from onyx.llm.models import UserMessage
from onyx.utils.postgres_sanitization import sanitize_string

MAX_PENDING_AGENT_MESSAGES = 64


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


def pending_inputs(
    session: Session, branch: ChatBranch, agent_id: str | None = None
) -> list[ChatAgentInput]:
    selected = _selected_responses(branch)
    query = (
        select(ChatAgentInput)
        .join(ToolCall, ChatAgentInput.invoking_tool_call_id == ToolCall.id)
        .where(
            ChatAgentInput.response_item_id.is_(None),
            ToolCall.parent_chat_message_id.in_(select(selected.c.id)),
        )
        .order_by(ChatAgentInput.id)
    )
    if agent_id is not None:
        _visible_agent(session, branch, agent_id)
        query = query.where(ChatAgentInput.recipient_session_id == UUID(agent_id))
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
    question = aliased(ChatMessage)
    rows = session.scalars(
        select(ChatMessage)
        .join(question, ChatMessage.parent_message_id == question.id)
        .join(ToolCall, question.invoking_tool_call_id == ToolCall.id)
        .where(
            ChatMessage.chat_session_id.in_([UUID(agent_id) for agent_id in agent_ids]),
            ToolCall.parent_chat_message_id.in_(select(selected.c.id)),
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


def message_receipt(row: ChatAgentInput) -> AgentMessageReceipt:
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
    if (
        len(pending_inputs(session, branch, request.agent_id))
        >= MAX_PENDING_AGENT_MESSAGES
    ):
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
    row = ChatAgentInput(
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


def remove_message(
    session: Session, branch: ChatBranch, agent_id: str, message_id: str
) -> bool:
    lock_agent(session, agent_id)
    for row in pending_inputs(session, branch, agent_id):
        if row.message_id == message_id:
            session.delete(row)
            return True
    return False


def receive_messages(
    session: Session,
    agent_id: str,
    run_id: str,
    received_ids: Collection[str],
) -> list[UserMessage]:
    rows = session.scalars(
        select(ChatAgentInput)
        .where(
            ChatAgentInput.recipient_session_id == UUID(agent_id),
            ChatAgentInput.target_response_id == int(run_id),
            ChatAgentInput.delivery == MessageDelivery.SEND,
            ChatAgentInput.response_item_id.is_(None),
            ChatAgentInput.message_id.not_in(received_ids),
        )
        .order_by(ChatAgentInput.id)
    )
    return [
        UserMessage(
            id=row.message_id,
            content=row.content,
            metadata=InputMessageMetadata(
                source=InputSource.AGENT,
                source_run_id=str(row.invoking_tool_call.parent_chat_message_id),
                sender_agent_id=str(row.invoking_tool_call.chat_session_id),
            ),
        )
        for row in rows
        if row.invoking_tool_call is not None
    ]


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
        if (
            not isinstance(origin, InputMessageMetadata)
            or origin.source != InputSource.AGENT
        ):
            continue
        row = session.scalar(
            select(ChatAgentInput)
            .where(
                ChatAgentInput.recipient_session_id == response.chat_session_id,
                ChatAgentInput.message_id == message.id,
                ChatAgentInput.target_response_id == run_id,
            )
            .with_for_update(of=ChatAgentInput)
        )
        if row is None:
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
            select(ChatAgentInput.id)
            .where(
                ChatAgentInput.target_response_id == response_id,
                ChatAgentInput.delivery == MessageDelivery.SEND,
                ChatAgentInput.response_item_id.is_(None),
            )
            .limit(1)
        )
        is not None
    )
    if not pending or not can_continue:
        response.response_inputs_closed = True
    return pending


def queued_request(row: ChatAgentInput) -> AgentMessageRequest:
    invocation = row.invoking_tool_call
    if (
        invocation is None
        or invocation.parent_chat_message_id is None
        or row.max_steps is None
        or row.delivery is None
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


def can_start_message(row: ChatAgentInput, latest: ChatMessage | None) -> bool:
    if latest is not None and (
        latest.response_status is None or not latest.response_status.is_terminal
    ):
        return False
    if row.delivery == MessageDelivery.SEND and row.target_response_id is None:
        return True
    return latest is None or latest.response_status == RunStatus.COMPLETE


def reserve_input_response(
    session: Session, row: ChatAgentInput, agent: AgentInfo, latest: ChatMessage | None
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
        message="The queued agent run could not start",
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
