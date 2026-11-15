"""What chat approval requests do below the HTTP API: a run that hands off
while its calls wait and resumes in a fresh store with the saved decisions,
claims, child runs, stopped program calls, the end of an unresumable response,
and which requests a non-streaming response returns. Integration tests cover
the decision API, dispatch, policies, session grants and blocked sends."""

import json
import threading
from collections.abc import Callable, Generator, Iterator, Sequence
from concurrent.futures import Future
from unittest.mock import MagicMock, patch
from uuid import UUID, uuid4

import pytest
from pydantic import BaseModel, ConfigDict
from sqlalchemy import delete, select, update
from sqlalchemy.orm import Session

from onyx.agents.agent_coordination import AgentCoordinator
from onyx.agents.events import AgentEvent
from onyx.agents.models import AgentState, ExecutionCheckpoint, RunStatus
from onyx.agents.runtime import Agent, Run
from onyx.agents.tool_execution import UNAVAILABLE_CALL_MESSAGE
from onyx.agents.tools import (
    AgentLifetime,
    AgentTool,
    ChildRunWait,
    InputMode,
    PendingToolInput,
    ToolInvocation,
)
from onyx.cache.factory import get_cache_backend
from onyx.chat import run_store
from onyx.chat.emitter import Emitter
from onyx.chat.models import (
    AnswerStreamPart,
    ChatInbox,
    ChatResponseOutcome,
    ChatResponseSnapshot,
    PersistenceStatus,
)
from onyx.chat.presentation import ResponsePresenter
from onyx.chat.process_message import gather_stream_full
from onyx.chat.run_store import (
    RESUME_FAILED_MESSAGE,
    ChatRunStore,
    fail_suspended_response,
)
from onyx.configs.constants import MessageType
from onyx.db.action_policy import replace_workspace_action_policies
from onyx.db.approval_request import create_approval_request__no_commit
from onyx.db.chat import delete_messages_and_files_from_chat_session
from onyx.db.chat_inputs import read_chat_inbox
from onyx.db.engine.sql_engine import get_session_with_tenant
from onyx.db.enums import (
    ActionPolicy,
    ApprovalDecidedVia,
    ApprovalDecision,
    GatedAppKind,
)
from onyx.db.mcp import create_mcp_server__no_commit
from onyx.db.models import (
    ApprovalRequest,
    ChatMessage,
    ChatResponseCheckpoint,
    ChatSession,
    GatedApp,
    MCPServer,
    Tool,
    User,
)
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.file_store.file_store import get_default_file_store
from onyx.llm.cancellation import CancellationSignal
from onyx.llm.interfaces import GenerationContext
from onyx.llm.models import (
    AssistantMessage,
    GenerationRequest,
    TextContent,
    ToolCall,
    ToolDefinition,
    ToolResult,
    ToolResultMessage,
    UserMessage,
)
from onyx.server.features.action_policies.models import ApprovalChoice
from onyx.server.query_and_chat.chat_backend import decide_approval
from onyx.server.query_and_chat.models import (
    ApprovalDecisionResponse,
    ChatApprovalDecisionRequest,
    MessageResponseIDInfo,
)
from onyx.server.query_and_chat.placement import Placement
from onyx.server.query_and_chat.streaming_models import (
    OverallStop,
    Packet,
    ToolApprovalRequest,
    ToolApprovalResolved,
)
from onyx.tools.interface import Tool as ChatTool
from onyx.tools.models import ToolApprovalScope, ToolContext
from onyx.tools.tool_implementations.code_mode.cells import CodeCells
from onyx.tools.tool_implementations.code_mode.code_mode_tool import (
    CodeModeTool,
    WaitCodeTool,
)
from onyx.tools.tool_implementations.mcp.mcp_tool import MCPTool
from onyx.tools.tool_implementations.subagents.subagent_tools import SpawnAgentTool
from onyx.tracing.flows import LLMFlow
from shared_configs.configs import POSTGRES_DEFAULT_SCHEMA_STANDARD_VALUE
from tests.external_dependency_unit.chat.test_run_store import (
    calls,
    chat_agent,
    replies,
)
from tests.external_dependency_unit.conftest import MakeTestUser
from tests.unit.onyx.agents.fakes import FakeModelClient
from tests.unit.onyx.tools.code_mode.fakes import LIMITS, FakeMCPTool, until

ACTION = "send_email"


class ApprovalChat(BaseModel):
    """A user's chat session, with a saved turn, and an MCP server with one tool."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    user: User
    server: MCPServer
    gated_app_id: int
    chat_session_id: UUID
    question: UserMessage
    response_id: int

    def scope(self) -> ToolApprovalScope:
        return ToolApprovalScope(
            app_kind=GatedAppKind.MCP_SERVER,
            target_id=self.server.id,
            action_id=ACTION,
        )

    def tool(self) -> MCPTool:
        """The server's tool as tool construction builds it for an ASK policy."""
        return MCPTool(
            tool_id=1,
            mcp_server=self.server,
            tool_name=ACTION,
            tool_description="",
            tool_definition={"displayName": "Send email"},
            approval=self.scope(),
        )

    def rows(self, db_session: Session) -> list[ApprovalRequest]:
        # Refreshes only these rows: runs read the chat's user on their threads.
        return list(
            db_session.scalars(
                select(ApprovalRequest)
                .where(ApprovalRequest.chat_session_id == self.chat_session_id)
                .order_by(ApprovalRequest.created_at)
                .execution_options(populate_existing=True)
            )
        )

    def decide(
        self, db_session: Session, approval_id: UUID | str, decision: ApprovalChoice
    ) -> ApprovalDecisionResponse:
        """Save a decision; the dispatch that resumes a response is the
        integration tests' concern."""
        with patch(
            "onyx.server.query_and_chat.chat_backend.dispatch_pending_chat_messages"
        ):
            return decide_approval(
                approval_id=UUID(str(approval_id)),
                body=ChatApprovalDecisionRequest(decision=decision),
                request=MagicMock(headers={}),
                user=self.user,
                db_session=db_session,
            )


@pytest.fixture
def chat(
    db_session: Session, make_test_user: MakeTestUser
) -> Generator[ApprovalChat, None, None]:
    user = make_test_user("tool_approval")
    server = create_mcp_server__no_commit(
        owner_email=user.email,
        name=f"approvals_{uuid4().hex[:8]}",
        description=None,
        server_url="https://example.com/mcp",
        auth_type=None,
        transport=None,
        auth_performer=None,
        db_session=db_session,
    )
    db_session.add(Tool(name=ACTION, mcp_server_id=server.id, user_id=user.id))
    chat_session = ChatSession(id=uuid4(), user_id=user.id, description="approvals")
    db_session.add(chat_session)
    db_session.flush()
    question = ChatMessage(
        chat_session_id=chat_session.id,
        message="Email the team",
        token_count=3,
        message_type=MessageType.USER,
    )
    db_session.add(question)
    db_session.flush()
    response = ChatMessage(
        chat_session_id=chat_session.id,
        parent_message_id=question.id,
        message="",
        token_count=0,
        message_type=MessageType.ASSISTANT,
    )
    db_session.add(response)
    db_session.flush()
    question.latest_child_message_id = response.id
    gated_app_id = db_session.scalar(
        select(GatedApp.id).where(GatedApp.mcp_server_id == server.id)
    )
    assert gated_app_id is not None
    db_session.commit()
    try:
        yield ApprovalChat(
            user=user,
            server=server,
            gated_app_id=gated_app_id,
            chat_session_id=chat_session.id,
            question=UserMessage(id=f"chat:{question.id}", content=question.message),
            response_id=response.id,
        )
    finally:
        db_session.rollback()
        delete_messages_and_files_from_chat_session(chat_session.id, db_session)
        # Cascades to the server's tools, app identity, and requests.
        db_session.execute(delete(MCPServer).where(MCPServer.id == server.id))
        db_session.commit()


def _replies(first: AssistantMessage) -> Callable[..., AssistantMessage]:
    """The model's `first` reply, then "done" once a tool result arrives."""

    def reply(
        request: GenerationRequest, _signal: CancellationSignal
    ) -> AssistantMessage:
        if request.messages and isinstance(request.messages[-1], ToolResultMessage):
            return AssistantMessage(content=[TextContent(text="done")])
        return first

    return reply


class OwnedRun(BaseModel):
    """A chat response owned by a store whose control thread the test drives."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    owner: ChatRunStore
    coordinator: AgentCoordinator
    run: Run

    def first_result(self, call_id: str) -> str:
        result = self.run.snapshot().steps[0].tools[call_id].result
        assert result is not None
        return result.text


@pytest.fixture
def owned_runs() -> Generator[list[OwnedRun], None, None]:
    runs: list[OwnedRun] = []
    try:
        yield runs
    finally:
        for owned in runs:
            owned.run.cancel()
            assert owned.coordinator.close(timeout=10)


def _store(chat: ApprovalChat, gated: Sequence[ChatTool]) -> ChatRunStore:
    """The response's store, as each API pod builds it."""
    return ChatRunStore(
        tenant_id=POSTGRES_DEFAULT_SCHEMA_STANDARD_VALUE,
        chat_session_id=chat.chat_session_id,
        response_id=chat.response_id,
        visible_response_ids=[],
        cache=get_cache_backend(tenant_id=POSTGRES_DEFAULT_SCHEMA_STANDARD_VALUE),
        follow_up_steps=2,
        user=chat.user,
        tools=gated,
    )


def _agent(
    chat: ApprovalChat,
    reply: Callable[[GenerationRequest, CancellationSignal], AssistantMessage],
    tools: Sequence[AgentTool],
    state: AgentState | None = None,
) -> Agent:
    return Agent(
        FakeModelClient(reply),
        generation_context=GenerationContext(flow=LLMFlow.CHAT_RESPONSE),
        agent_id=str(chat.chat_session_id),
        state=state,
        tools=list(tools),
    )


def _start(
    chat: ApprovalChat,
    owned_runs: list[OwnedRun],
    *,
    reply: Callable[[GenerationRequest, CancellationSignal], AssistantMessage],
    tools: Sequence[AgentTool],
    gated: Sequence[ChatTool],
    on_event: Callable[[AgentEvent], None] = lambda _event: None,
) -> OwnedRun:
    owner = _store(chat, gated)
    agent = _agent(chat, reply, tools)
    coordinator = AgentCoordinator()
    view = owner.bind(coordinator, build_agent=lambda _checkpoint, _depth: agent)
    run = agent.start(
        messages=[chat.question], max_steps=3, coordinator=view, on_event=on_event
    )
    owned = OwnedRun(owner=owner, coordinator=coordinator, run=run)
    owned_runs.append(owned)
    return owned


def _resume(
    chat: ApprovalChat,
    owned_runs: list[OwnedRun],
    *,
    reply: Callable[[GenerationRequest, CancellationSignal], AssistantMessage],
    tools: Sequence[AgentTool],
    gated: Sequence[ChatTool],
    on_event: Callable[[AgentEvent], None] = lambda _event: None,
) -> OwnedRun | None:
    """Resume the handed-off response in a fresh store, as another pod does."""
    owner = _store(chat, gated)
    coordinator = AgentCoordinator()

    def rebuild(checkpoint: ExecutionCheckpoint, _depth: int) -> Agent:
        return _agent(chat, reply, tools, checkpoint.agent_state)

    owner.bind(coordinator, build_agent=rebuild)
    run = owner.resume(str(chat.response_id), context=AgentState(), on_event=on_event)
    if run is None:
        assert coordinator.close(timeout=10)
        return None
    owned = OwnedRun(owner=owner, coordinator=coordinator, run=run)
    owned_runs.append(owned)
    return owned


def _hand_off(owned: OwnedRun) -> None:
    """Save the waiting run and release it, as the turn does."""
    assert owned.run.wait_until_settled(10).status == RunStatus.SUSPENDED
    assert owned.run.wait_for_idle(10)
    owned.owner.handoff(owned.run.id)


def _sending(tool: MCPTool) -> AgentTool:
    """The gated tool as the run sees it, answering "sent" instead of calling
    the MCP server."""
    return AgentTool(
        definition=tool.tool_definition(),
        execute=lambda _invocation: ToolResult(content="sent"),
        approval_required=[tool.name],
    )


def _calls(tool: ChatTool, *call_ids: str) -> Callable[..., AssistantMessage]:
    """The model calls `tool` once per ID, then answers "done"."""
    return _replies(
        AssistantMessage(
            content=[
                ToolCall(id=call_id, name=tool.name, arguments={})
                for call_id in call_ids
            ]
        )
    )


def _direct_call(
    chat: ApprovalChat,
    owned_runs: list[OwnedRun],
    *call_ids: str,
) -> OwnedRun:
    """A response whose model calls the gated MCP tool directly."""
    tool = chat.tool()
    return _start(
        chat,
        owned_runs,
        reply=_calls(tool, *(call_ids or ("send",))),
        tools=[_sending(tool)],
        gated=[tool],
    )


def _recording(tool: MCPTool, sent: list[str]) -> AgentTool:
    """The gated tool, recording each call that runs."""

    def execute(invocation: ToolInvocation) -> ToolResult:
        sent.append(invocation.call_id)
        return ToolResult(content="sent")

    return AgentTool(
        definition=tool.tool_definition(),
        execute=execute,
        approval_required=[tool.name],
    )


def _resumable(db_session: Session, chat: ApprovalChat) -> int | None:
    db_session.expire_all()
    inbox = read_chat_inbox(db_session, chat.chat_session_id)
    db_session.rollback()
    return inbox.resumable_response_id


def test_a_waiting_run_hands_off_and_a_fresh_store_resumes_it(
    db_session: Session, chat: ApprovalChat, owned_runs: list[OwnedRun]
) -> None:
    tool = chat.tool()
    sent: list[str] = []
    owned = _start(
        chat,
        owned_runs,
        reply=_calls(tool, "send"),
        tools=[_recording(tool, sent)],
        gated=[tool],
    )

    _hand_off(owned)

    db_session.expire_all()
    response = db_session.get(ChatMessage, chat.response_id)
    assert response is not None and response.response_status == RunStatus.SUSPENDED
    assert db_session.get(ChatResponseCheckpoint, chat.response_id) is not None
    assert run_store.ownerless_response_ids(get_cache_backend(), [chat.response_id])
    db_session.rollback()
    [row] = chat.rows(db_session)
    assert row.decision is None
    assert _resumable(db_session, chat) is None

    chat.decide(db_session, row.id, ApprovalChoice.APPROVE_ONCE)
    assert _resumable(db_session, chat) == chat.response_id
    resumed = _resume(
        chat,
        owned_runs,
        reply=_calls(tool, "send"),
        tools=[_recording(tool, sent)],
        gated=[tool],
    )

    assert resumed is not None
    assert resumed.run.result(timeout=10).output.text == "done"
    assert resumed.run.wait_for_idle(10)
    assert resumed.first_result("send") == "sent"
    assert sent == ["send"]
    db_session.expire_all()
    assert db_session.get(ChatResponseCheckpoint, chat.response_id) is None


def test_a_session_grant_decides_every_request_and_the_run_resumes_once(
    db_session: Session, chat: ApprovalChat, owned_runs: list[OwnedRun]
) -> None:
    tool = chat.tool()
    sent: list[str] = []
    owned = _start(
        chat,
        owned_runs,
        reply=_calls(tool, "first", "second"),
        tools=[_recording(tool, sent)],
        gated=[tool],
    )
    _hand_off(owned)
    first, second = chat.rows(db_session)

    chat.decide(db_session, first.id, ApprovalChoice.APPROVE_SESSION)

    assert [(row.decision, row.decided_via) for row in chat.rows(db_session)] == [
        (ApprovalDecision.APPROVED, ApprovalDecidedVia.SESSION_GRANT)
    ] * 2
    assert _resumable(db_session, chat) == chat.response_id
    resumed = _resume(
        chat,
        owned_runs,
        reply=_calls(tool, "first", "second"),
        tools=[_recording(tool, sent)],
        gated=[tool],
    )
    assert resumed is not None
    # Another pod that also tries finds the run claimed.
    assert (
        _resume(
            chat,
            owned_runs,
            reply=_calls(tool, "first", "second"),
            tools=[_recording(tool, sent)],
            gated=[tool],
        )
        is None
    )
    assert resumed.run.result(timeout=10).output.text == "done"
    assert sorted(sent) == ["first", "second"]


def test_a_response_does_not_resume_while_one_of_its_requests_waits(
    db_session: Session, chat: ApprovalChat, owned_runs: list[OwnedRun]
) -> None:
    owned = _direct_call(chat, owned_runs, "first", "second")
    _hand_off(owned)
    first, second = chat.rows(db_session)

    chat.decide(db_session, first.id, ApprovalChoice.APPROVE_ONCE)
    assert _resumable(db_session, chat) is None

    chat.decide(db_session, second.id, ApprovalChoice.REJECT)
    assert _resumable(db_session, chat) == chat.response_id


@pytest.mark.parametrize("first", ["decision", "stop"])
def test_a_decision_and_a_stop_of_the_live_turn_keep_the_first(
    db_session: Session, chat: ApprovalChat, owned_runs: list[OwnedRun], first: str
) -> None:
    tool = chat.tool()
    sent: list[str] = []
    ended: list[ToolApprovalResolved] = []
    owned = _start(
        chat,
        owned_runs,
        reply=_calls(tool, "send"),
        tools=[_recording(tool, sent)],
        gated=[tool],
        on_event=ResponsePresenter(
            Emitter(
                lambda packet: (
                    ended.append(packet.obj)
                    if isinstance(packet.obj, ToolApprovalResolved)
                    else None
                )
            )
        ).consume,
    )
    assert owned.run.wait_until_settled(10).status == RunStatus.SUSPENDED
    [row] = chat.rows(db_session)

    if first == "decision":
        chat.decide(db_session, row.id, ApprovalChoice.APPROVE_ONCE)
    owned.owner.reject_waiting_approvals()
    owned.run.cancel("user")
    assert owned.run.wait_for_idle(10)
    if first == "stop":
        with pytest.raises(OnyxError) as conflict:
            chat.decide(db_session, row.id, ApprovalChoice.APPROVE_ONCE)
        assert conflict.value.error_code == OnyxErrorCode.CONFLICT

    [saved] = chat.rows(db_session)
    assert saved.decision == (
        ApprovalDecision.APPROVED if first == "decision" else ApprovalDecision.REJECTED
    )
    assert sent == []
    assert [resolved.outcome for resolved in ended] == [
        "approved" if first == "decision" else "rejected"
    ]


@pytest.mark.parametrize("change", ["tool_removed", "server_deleted"])
def test_a_call_whose_tool_is_gone_gets_no_longer_available(
    db_session: Session, chat: ApprovalChat, owned_runs: list[OwnedRun], change: str
) -> None:
    tool = chat.tool()
    sent: list[str] = []
    owned = _start(
        chat,
        owned_runs,
        reply=_calls(tool, "send"),
        tools=[_recording(tool, sent)],
        gated=[tool],
    )
    _hand_off(owned)
    [row] = chat.rows(db_session)
    if change == "tool_removed":
        chat.decide(db_session, row.id, ApprovalChoice.APPROVE_ONCE)
    else:
        # Deletes the server's app identity and its requests.
        db_session.execute(delete(MCPServer).where(MCPServer.id == chat.server.id))
        db_session.commit()
        with pytest.raises(OnyxError) as missing:
            chat.decide(db_session, row.id, ApprovalChoice.APPROVE_ONCE)
        assert missing.value.error_code == OnyxErrorCode.NOT_FOUND
    assert _resumable(db_session, chat) == chat.response_id

    resumed = _resume(
        chat,
        owned_runs,
        reply=_calls(tool, "send"),
        tools=[] if change == "tool_removed" else [_recording(tool, sent)],
        gated=[] if change == "tool_removed" else [tool],
    )

    assert resumed is not None
    assert resumed.run.result(timeout=10).output.text == "done"
    assert resumed.first_result("send") == UNAVAILABLE_CALL_MESSAGE
    assert sent == []


def test_a_request_creates_the_missing_app_identity(
    db_session: Session, chat: ApprovalChat, owned_runs: list[OwnedRun]
) -> None:
    db_session.execute(delete(GatedApp).where(GatedApp.id == chat.gated_app_id))
    db_session.commit()

    owned = _direct_call(chat, owned_runs)

    assert owned.run.wait_until_settled(10).status == RunStatus.SUSPENDED
    [row] = chat.rows(db_session)
    assert row.gated_app_id == db_session.scalar(
        select(GatedApp.id).where(GatedApp.mcp_server_id == chat.server.id)
    )


def _agent_runs(
    chat: ApprovalChat,
    owned_runs: list[OwnedRun],
    lifetime: AgentLifetime,
    sent: list[str],
    *,
    root_reply: Callable[..., AssistantMessage] | None = None,
) -> OwnedRun:
    """A root whose agent calls the gated tool. A background agent comes from
    `spawn_agent`, and the root answers; a foreground agent's root waits for
    it and answers with its answer."""
    tool = chat.tool()

    def child() -> Agent:
        return Agent(
            FakeModelClient(_calls(tool, "send")),
            generation_context=GenerationContext(flow=LLMFlow.CHAT_RESPONSE),
            tools=[_recording(tool, sent)],
        )

    if lifetime == AgentLifetime.BACKGROUND:
        return _start(
            chat,
            owned_runs,
            reply=root_reply
            or _replies(
                AssistantMessage(
                    content=[
                        ToolCall(
                            id="spawn",
                            name=SpawnAgentTool.name,
                            arguments={"name": "mailer", "instruction": "Email"},
                        )
                    ]
                )
            ),
            tools=[SpawnAgentTool(child, max_steps=3).bind(ToolContext), _hold()],
            gated=[tool],
        )

    def delegate(invocation: ToolInvocation) -> ChildRunWait:
        return ChildRunWait(
            run_ids=[
                invocation.agents.spawn_agent(
                    child(),
                    name="mailer",
                    description="Email",
                    messages=[UserMessage(content="Email the team")],
                    max_steps=3,
                ).run_id
            ]
        )

    return _start(
        chat,
        owned_runs,
        reply=_replies(
            AssistantMessage(
                content=[ToolCall(id="delegate", name="delegate", arguments={})]
            )
        ),
        tools=[
            AgentTool(
                definition=ToolDefinition(
                    name="delegate", description="", parameters={}
                ),
                execute=delegate,
                result_from_children=lambda _invocation, states: ToolResult(
                    content=states[0].messages[-1].text
                ),
            )
        ],
        gated=[tool],
    )


def _hold() -> AgentTool:
    """A call that waits for a person's answer that is not an approval, so
    its root stays live and owned."""
    return AgentTool(
        definition=ToolDefinition(name="hold", description="", parameters={}),
        execute=lambda _invocation: PendingToolInput(
            request_id="hold", prompt="Hold", mode=InputMode.RESULT
        ),
    )


# These reads use their own sessions: expiring the test's session would
# reload the chat's user while runs read it on their threads.


def _status(response_id: int) -> RunStatus | None:
    with get_session_with_tenant(
        tenant_id=POSTGRES_DEFAULT_SCHEMA_STANDARD_VALUE
    ) as session:
        response = session.get(ChatMessage, response_id)
        return response.response_status if response is not None else None


def _parked(response_id: int) -> bool:
    with get_session_with_tenant(
        tenant_id=POSTGRES_DEFAULT_SCHEMA_STANDARD_VALUE
    ) as session:
        saved = session.get(ChatResponseCheckpoint, response_id) is not None
    return (
        _status(response_id) == RunStatus.SUSPENDED
        and saved
        and not get_cache_backend().exists(run_store._owner_key(response_id))
    )


def _inbox(chat: ApprovalChat) -> ChatInbox:
    with get_session_with_tenant(
        tenant_id=POSTGRES_DEFAULT_SCHEMA_STANDARD_VALUE
    ) as session:
        return read_chat_inbox(session, chat.chat_session_id)


@pytest.mark.parametrize("lifetime", list(AgentLifetime))
def test_an_agent_run_asks_parks_and_resumes_in_a_fresh_store(
    db_session: Session,
    chat: ApprovalChat,
    owned_runs: list[OwnedRun],
    lifetime: AgentLifetime,
) -> None:
    """An agent's call waits durably: the agent's run parks, and a foreground
    agent's parent parks after it. After the decision, a fresh store resumes
    the agent at its depth, then the parent once the agent ended."""
    sent: list[str] = []
    owned = _agent_runs(chat, owned_runs, lifetime, sent)
    until(lambda: _poll(owned) and len(chat.rows(db_session)) == 1)
    [row] = chat.rows(db_session)
    child_id = row.chat_message_id
    assert child_id != chat.response_id
    until(lambda: _poll(owned) and _parked(child_id))
    if lifetime == AgentLifetime.FOREGROUND:
        until(lambda: owned.owner.may_park(owned.run))
        owned.owner.handoff(owned.run.id)
        assert _parked(chat.response_id)
    else:
        assert owned.run.result(timeout=10).output.text == "done"
    inbox = _inbox(chat)
    assert inbox.resumable_agent_runs == []
    assert inbox.resumable_response_id is None

    chat.decide(db_session, row.id, ApprovalChoice.APPROVE_ONCE)
    assert [run.response_id for run in _inbox(chat).resumable_agent_runs] == [child_id]

    tool = chat.tool()
    depths: dict[str, int] = {}

    def rebuild(checkpoint: ExecutionCheckpoint, depth: int) -> Agent:
        agent_id = checkpoint.run_state.agent_id
        assert agent_id is not None
        depths[agent_id] = depth
        return Agent(
            FakeModelClient(_calls(tool, "send")),
            generation_context=GenerationContext(flow=LLMFlow.CHAT_RESPONSE),
            agent_id=agent_id,
            state=checkpoint.agent_state,
            tools=[_recording(tool, sent)],
        )

    fresh = _store(chat, [tool])
    coordinator = AgentCoordinator()
    fresh.bind(coordinator, build_agent=rebuild)
    try:
        until(
            lambda: (
                fresh.poll_control() is None
                and _status(child_id) == RunStatus.COMPLETE
                and not fresh.has_owned_work
            )
        )
    finally:
        assert coordinator.close(timeout=10)
    assert sent == ["send"]
    assert list(depths.values()) == [1]
    assert db_session.get(ChatResponseCheckpoint, child_id) is None
    if lifetime == AgentLifetime.FOREGROUND:
        assert _inbox(chat).resumable_response_id == chat.response_id
        resumed = _resume(
            chat,
            owned_runs,
            reply=_replies(AssistantMessage(content=[TextContent(text="done")])),
            tools=[
                AgentTool(
                    definition=ToolDefinition(
                        name="delegate", description="", parameters={}
                    ),
                    execute=lambda _invocation: pytest.fail("The agent started once"),
                    result_from_children=lambda _invocation, states: ToolResult(
                        content=states[0].messages[-1].text
                    ),
                )
            ],
            gated=[tool],
        )
        assert resumed is not None
        assert resumed.run.result(timeout=10).output.text == "done"
        assert resumed.first_result("delegate") == "done"


def test_root_stop_keeps_a_background_agents_request(
    db_session: Session, chat: ApprovalChat, owned_runs: list[OwnedRun]
) -> None:
    """The user's Stop of a live turn rejects only the requests of the runs it
    cancels; a background agent keeps running and keeps its request."""
    sent: list[str] = []
    owned = _agent_runs(
        chat,
        owned_runs,
        AgentLifetime.BACKGROUND,
        sent,
        root_reply=replies(
            calls(
                ToolCall(
                    id="spawn",
                    name=SpawnAgentTool.name,
                    arguments={"name": "mailer", "instruction": "Email"},
                )
            ),
            calls(ToolCall(id="hold", name="hold", arguments={})),
        ),
    )
    # The agent asks and stays owned: no control poll parks it.
    until(lambda: len(chat.rows(db_session)) == 1)
    assert owned.run.wait_until_settled(10).status == RunStatus.SUSPENDED

    owned.owner.reject_waiting_approvals()
    owned.run.cancel("user")
    assert owned.run.wait_for_idle(10)

    [row] = chat.rows(db_session)
    assert row.chat_message_id != chat.response_id
    assert row.decision is None


def test_ownerless_repair_keeps_a_parked_response(
    db_session: Session, chat: ApprovalChat, owned_runs: list[OwnedRun]
) -> None:
    """A parked response has no owner by design; repair leaves it waiting."""
    owned = _direct_call(chat, owned_runs)
    _hand_off(owned)

    assert (
        run_store.interrupt_ownerless_responses(
            get_cache_backend(),
            POSTGRES_DEFAULT_SCHEMA_STANDARD_VALUE,
            [chat.response_id],
        )
        == set()
    )

    assert _parked(chat.response_id)
    assert [row.decision for row in chat.rows(db_session)] == [None]


def _poll(owned: OwnedRun) -> bool:
    owned.owner.poll_control()
    return True


# Programs of these limits can park: the dump fits within the memory share.
PARKING_LIMITS = LIMITS.model_copy(update={"max_memory_bytes": 128 * 1024 * 1024})


def _gated_function(chat: ApprovalChat, sent: list[str]) -> FakeMCPTool:
    def send(invocation: ToolInvocation, _context: ToolContext) -> ToolResult:
        sent.append(str(invocation.arguments["value"]))
        return ToolResult(content=json.dumps({"tool_result": "sent"}))

    tool = FakeMCPTool(
        ACTION,
        send,
        {
            "type": "object",
            "properties": {"value": {"type": "string"}},
            "required": ["value"],
        },
    )
    tool.approval = chat.scope()
    return tool


def test_a_stopped_program_call_ends_its_request_and_its_card_closes(
    db_session: Session, chat: ApprovalChat, owned_runs: list[OwnedRun]
) -> None:
    sent: list[str] = []
    tool = _gated_function(chat, sent)
    cells = CodeCells()
    live: list[Packet] = []
    call_waits = threading.Event()

    def reply(
        request: GenerationRequest, _signal: CancellationSignal
    ) -> AssistantMessage:
        """Start a program that yields, then waits on the call; once the call
        waits, stop the program's cell."""
        last = request.messages[-1] if request.messages else None
        if not isinstance(last, ToolResultMessage):
            code = f"yield_control()\nawait mcp__1__acme__{ACTION}(value='team')\n"
            return AssistantMessage(
                content=[
                    ToolCall(
                        id="program", name="execute_code", arguments={"code": code}
                    )
                ]
            )
        if last.tool_call_id == "program":
            assert call_waits.wait(10)
            return AssistantMessage(
                content=[
                    ToolCall(
                        id="stop",
                        name="wait_code",
                        arguments={"cell_id": 1, "terminate": True},
                    )
                ]
            )
        return AssistantMessage(content=[TextContent(text="done")])

    def on_event(event: AgentEvent) -> None:
        presenter.consume(event)
        if any(isinstance(packet.obj, ToolApprovalRequest) for packet in live):
            call_waits.set()

    presenter = ResponsePresenter(Emitter(live.append))
    owned = _start(
        chat,
        owned_runs,
        reply=reply,
        tools=[
            CodeModeTool([tool], cells=cells, limits=PARKING_LIMITS).bind(ToolContext),
            WaitCodeTool(cells).bind(ToolContext),
        ],
        gated=[tool],
        on_event=on_event,
    )

    assert owned.run.result(timeout=20).output.text == "done"
    assert owned.run.wait_for_idle(10)
    stopped = owned.run.snapshot().steps[1].tools["stop"].result
    assert stopped is not None and "terminated" in stopped.text
    assert sent == []
    assert [row.decision for row in chat.rows(db_session)] == [ApprovalDecision.EXPIRED]
    [request] = [p.obj for p in live if isinstance(p.obj, ToolApprovalRequest)]
    assert [p.obj for p in live if isinstance(p.obj, ToolApprovalResolved)] == [
        ToolApprovalResolved(approval_id=request.approval_id, outcome="cancelled")
    ]


def test_an_unresumable_response_fails_and_drops_its_saved_state(
    db_session: Session, chat: ApprovalChat, owned_runs: list[OwnedRun]
) -> None:
    """A response whose model or saved state is gone cannot continue: it is
    saved as failed, and its checkpoint and its parked program's dump go."""
    sent: list[str] = []
    tool = _gated_function(chat, sent)
    code = f"await mcp__1__acme__{ACTION}(value='team')\n"
    owner = _store(chat, [tool])
    coordinator = AgentCoordinator()
    agent = chat_agent(
        FakeModelClient(
            _replies(
                AssistantMessage(
                    content=[
                        ToolCall(
                            id="program", name="execute_code", arguments={"code": code}
                        )
                    ]
                )
            )
        ),
        agent_id=str(chat.chat_session_id),
        tools=[tool],
        code_mode=True,
    )
    view = owner.bind(coordinator, build_agent=lambda _checkpoint, _depth: agent)
    owned = OwnedRun(
        owner=owner,
        coordinator=coordinator,
        run=agent.start(messages=[chat.question], max_steps=3, coordinator=view),
    )
    owned_runs.append(owned)
    _hand_off(owned)
    file_store = get_default_file_store()
    prefix = f"agent-checkpoint/{chat.chat_session_id}/"
    try:
        assert len(file_store.list_files_by_prefix(prefix)) == 1

        fail_suspended_response(
            get_cache_backend(),
            POSTGRES_DEFAULT_SCHEMA_STANDARD_VALUE,
            chat.response_id,
        )

        db_session.expire_all()
        response = db_session.get(ChatMessage, chat.response_id)
        assert response is not None and response.response_status == RunStatus.ERROR
        assert (
            response.response_failure is not None
            and response.response_failure.message == RESUME_FAILED_MESSAGE
        )
        assert db_session.get(ChatResponseCheckpoint, chat.response_id) is None
        db_session.rollback()
        assert [row.decision for row in chat.rows(db_session)] == [
            ApprovalDecision.EXPIRED
        ]
        assert file_store.list_files_by_prefix(prefix) == []
        assert sent == []
    finally:
        for record in file_store.list_files_by_prefix(prefix):
            file_store.delete_file(record.file_id, error_on_missing=False)


def test_a_response_whose_owner_is_lost_ends_its_requests(
    db_session: Session, chat: ApprovalChat, owned_runs: list[OwnedRun]
) -> None:
    """Ownerless repair saves the response as failed, so its requests do not
    block the chat's sends."""
    owned = _direct_call(chat, owned_runs)
    assert owned.run.wait_until_settled(10).status == RunStatus.SUSPENDED
    cache = get_cache_backend()
    cache.delete(run_store._owner_key(chat.response_id))

    assert run_store.interrupt_ownerless_responses(
        cache, POSTGRES_DEFAULT_SCHEMA_STANDARD_VALUE, [chat.response_id]
    ) == {chat.response_id}

    assert [row.decision for row in chat.rows(db_session)] == [ApprovalDecision.EXPIRED]


@pytest.mark.parametrize("policy", ["unchanged", "denied"])
def test_a_saved_decision_repeated_after_the_response_ends_returns_it(
    db_session: Session, chat: ApprovalChat, policy: str
) -> None:
    """A retry whose first attempt saved the decision, but lost its HTTP
    response, gets the saved decision, also after an admin disables the tool."""
    approval_id = create_approval_request__no_commit(
        db_session,
        chat_session_id=chat.chat_session_id,
        chat_message_id=chat.response_id,
        gated_app_id=chat.gated_app_id,
        action_id=ACTION,
        tool_call_id="send",
        tool_name=ACTION,
        display_name="Send email",
    )
    db_session.execute(
        update(ApprovalRequest)
        .where(ApprovalRequest.id == approval_id)
        .values(
            decision=ApprovalDecision.APPROVED,
            decided_via=ApprovalDecidedVia.SESSION_GRANT,
        )
    )
    if policy == "denied":
        replace_workspace_action_policies(
            db_session, chat.gated_app_id, {ACTION: ActionPolicy.DENY}
        )
    db_session.commit()

    repeated = chat.decide(db_session, approval_id, ApprovalChoice.APPROVE_ONCE)

    assert (repeated.decision, repeated.decided_via) == (
        ApprovalDecision.APPROVED,
        ApprovalDecidedVia.SESSION_GRANT,
    )
    with pytest.raises(OnyxError) as conflict:
        chat.decide(db_session, approval_id, ApprovalChoice.REJECT)
    assert conflict.value.error_code == OnyxErrorCode.CONFLICT
    [row] = chat.rows(db_session)
    assert (row.decision, row.decided_via) == (
        ApprovalDecision.APPROVED,
        ApprovalDecidedVia.SESSION_GRANT,
    )


def test_a_non_streaming_response_returns_the_requests_that_wait(
    chat: ApprovalChat,
) -> None:
    """The requests streamed without a resolution before the stop that waits
    for the decisions."""
    approval_ids = [str(uuid4()) for _ in range(3)]
    ended = approval_ids[2]

    def request(approval_id: str) -> Packet:
        return Packet(
            placement=Placement(turn_index=0),
            obj=ToolApprovalRequest(
                approval_id=approval_id,
                tool_call_id=f"call_{approval_id}",
                tool_name=ACTION,
                display_name="Send email",
                arguments={"to": "team"},
            ),
        )

    def packets() -> Iterator[AnswerStreamPart]:
        yield MessageResponseIDInfo(
            user_message_id=None, reserved_assistant_message_id=chat.response_id
        )
        yield request(approval_ids[0])
        # A program's request that ended when its program stopped.
        yield request(ended)
        yield Packet(
            placement=Placement(turn_index=0),
            obj=ToolApprovalResolved(approval_id=ended, outcome="cancelled"),
        )
        yield request(approval_ids[1])
        yield Packet(
            placement=Placement(turn_index=0),
            obj=OverallStop(stop_reason="awaiting_approval"),
        )

    outcome = Future[ChatResponseOutcome]()
    outcome.set_result(
        ChatResponseOutcome(
            response=ChatResponseSnapshot(
                answer=None,
                reasoning=None,
                request_params=None,
                citation_to_doc={},
                tool_calls=[],
                is_clarification=False,
                all_search_docs={},
                pre_answer_processing_time=None,
                response=None,
                cancelled=False,
            ),
            persistence_status=PersistenceStatus.SAVED,
        )
    )
    response = gather_stream_full(packets(), outcome)

    assert [
        pending.approval_id for pending in response.pending_tool_approvals
    ] == approval_ids[:2]
