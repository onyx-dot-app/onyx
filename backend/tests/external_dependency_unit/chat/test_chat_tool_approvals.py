"""What chat approval requests do that integration tests cannot reach: expiry,
shutdown, stopped program calls, unwatched runs, how the response owner learns
of decisions, and which requests a non-streaming response returns. Integration
tests cover the decision API, policies, session grants, lost owners and
blocked sends."""

import datetime
import json
import threading
from collections.abc import Callable, Generator, Iterator, Sequence
from concurrent.futures import Future
from uuid import UUID, uuid4

import pytest
from pydantic import BaseModel, ConfigDict
from sqlalchemy import delete, select, update
from sqlalchemy.orm import Session

from onyx.agents.agent_coordination import AgentCoordinator
from onyx.agents.events import AgentEvent
from onyx.agents.models import RunStatus
from onyx.agents.runtime import Agent, Run
from onyx.agents.tools import (
    AgentLifetime,
    AgentTool,
    ChildRunWait,
    ToolInvocation,
)
from onyx.cache.factory import get_cache_backend
from onyx.chat import run_store
from onyx.chat.emitter import Emitter
from onyx.chat.models import AnswerStreamPart, ChatResponseOutcome
from onyx.chat.presentation import ResponsePresenter
from onyx.chat.process_message import gather_stream_full
from onyx.chat.run_store import ChatRunStore
from onyx.chat.tool_approvals import (
    TOOL_APPROVAL_TIMEOUT,
    end_approval_waits,
    reset_approval_waits,
)
from onyx.configs.constants import MessageType
from onyx.db.approval_request import create_approval_request__no_commit
from onyx.db.chat import delete_messages_and_files_from_chat_session
from onyx.db.enums import ApprovalDecision, GatedAppKind
from onyx.db.mcp import create_mcp_server__no_commit
from onyx.db.models import (
    ApprovalRequest,
    ChatMessage,
    ChatSession,
    GatedApp,
    MCPServer,
    Tool,
    User,
)
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.llm.cancellation import AgentCancelled, CancellationSignal
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
from onyx.server.features.action_policies.models import ApprovalChoice, DecisionBody
from onyx.server.query_and_chat.chat_backend import decide_approval
from onyx.server.query_and_chat.models import MessageResponseIDInfo
from onyx.server.query_and_chat.placement import Placement
from onyx.server.query_and_chat.streaming_models import (
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
from onyx.tracing.flows import LLMFlow
from shared_configs.configs import POSTGRES_DEFAULT_SCHEMA_STANDARD_VALUE
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
        db_session.expire_all()
        return list(
            db_session.scalars(
                select(ApprovalRequest)
                .where(ApprovalRequest.chat_session_id == self.chat_session_id)
                .order_by(ApprovalRequest.created_at)
            )
        )

    def decide(
        self, db_session: Session, approval_id: UUID | str, decision: ApprovalChoice
    ) -> None:
        decide_approval(
            approval_id=UUID(str(approval_id)),
            body=DecisionBody(decision=decision),
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


def _start(
    chat: ApprovalChat,
    owned_runs: list[OwnedRun],
    *,
    reply: Callable[[GenerationRequest, CancellationSignal], AssistantMessage],
    tools: Sequence[AgentTool],
    gated: Sequence[ChatTool],
    watched: bool = True,
    on_event: Callable[[AgentEvent], None] = lambda _event: None,
) -> OwnedRun:
    owner = ChatRunStore(
        tenant_id=POSTGRES_DEFAULT_SCHEMA_STANDARD_VALUE,
        chat_session_id=chat.chat_session_id,
        response_id=chat.response_id,
        visible_response_ids=[],
        cache=get_cache_backend(tenant_id=POSTGRES_DEFAULT_SCHEMA_STANDARD_VALUE),
        follow_up_steps=2,
        user=chat.user,
        tools=gated,
    )
    agent = Agent(
        FakeModelClient(reply),
        generation_context=GenerationContext(flow=LLMFlow.CHAT_RESPONSE),
        agent_id=str(chat.chat_session_id),
        tools=list(tools),
    )
    coordinator = AgentCoordinator()
    view = owner.bind(coordinator, build_agent=lambda _checkpoint: agent)
    run = agent.start(
        messages=[chat.question],
        max_steps=3,
        coordinator=view,
        # Chat subscribes the response presenter; a run without one is unwatched.
        on_event=on_event if watched else None,
    )
    owned = OwnedRun(owner=owner, coordinator=coordinator, run=run)
    owned_runs.append(owned)
    return owned


def _sending(tool: MCPTool) -> AgentTool:
    """The gated tool as the run sees it, answering "sent" instead of calling
    the MCP server."""
    return AgentTool(
        definition=tool.tool_definition(),
        execute=lambda _invocation: ToolResult(content="sent"),
        approval_required=[tool.name],
    )


def _direct_call(
    chat: ApprovalChat,
    owned_runs: list[OwnedRun],
    *,
    tool: MCPTool | None = None,
    watched: bool = True,
) -> OwnedRun:
    """A response whose model calls the gated MCP tool directly."""
    tool = tool or chat.tool()
    return _start(
        chat,
        owned_runs,
        reply=_replies(
            AssistantMessage(
                content=[ToolCall(id="send", name=tool.name, arguments={})]
            )
        ),
        tools=[_sending(tool)],
        gated=[tool],
        watched=watched,
    )


def _backdate(db_session: Session, approval_id: str) -> None:
    db_session.execute(
        update(ApprovalRequest)
        .where(ApprovalRequest.id == UUID(approval_id))
        .values(
            created_at=ApprovalRequest.created_at
            - TOOL_APPROVAL_TIMEOUT
            - datetime.timedelta(seconds=1)
        )
    )
    db_session.commit()


def test_an_overdue_request_cannot_be_decided_and_its_call_gets_the_timeout(
    db_session: Session, chat: ApprovalChat, owned_runs: list[OwnedRun]
) -> None:
    owned = _direct_call(chat, owned_runs)
    assert owned.run.wait_until_settled(10).status == RunStatus.SUSPENDED
    [request] = owned.run.pending_inputs
    _backdate(db_session, request.request_id)

    with pytest.raises(OnyxError) as conflict:
        chat.decide(db_session, request.request_id, ApprovalChoice.APPROVE_ONCE)
    assert conflict.value.error_code == OnyxErrorCode.CONFLICT

    owned.owner.poll_control()

    assert owned.run.result(timeout=10).output.text == "done"
    assert "did not answer the approval request" in owned.first_result("send")
    assert [row.decision for row in chat.rows(db_session)] == [ApprovalDecision.EXPIRED]


def test_a_request_creates_the_missing_app_identity(
    db_session: Session, chat: ApprovalChat, owned_runs: list[OwnedRun]
) -> None:
    db_session.execute(delete(GatedApp).where(GatedApp.id == chat.gated_app_id))
    db_session.commit()

    owned = _direct_call(chat, owned_runs, tool=chat.tool())

    assert owned.run.wait_until_settled(10).status == RunStatus.SUSPENDED
    [row] = chat.rows(db_session)
    assert row.gated_app_id == db_session.scalar(
        select(GatedApp.id).where(GatedApp.mcp_server_id == chat.server.id)
    )


def test_an_unwatched_run_cannot_wait(
    db_session: Session, chat: ApprovalChat, owned_runs: list[OwnedRun]
) -> None:
    owned = _direct_call(chat, owned_runs, watched=False)

    assert owned.run.result(timeout=10).output.text == "done"
    assert "this agent cannot ask for it" in owned.first_result("send")
    assert chat.rows(db_session) == []


def test_a_foreground_child_can_wait_and_a_background_child_cannot(
    db_session: Session,
    chat: ApprovalChat,
    owned_runs: list[OwnedRun],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A foreground child's events reach the response's listener, so the user
    sees its request; a background child's do not."""
    monkeypatch.setattr(run_store, "INPUT_POLL_SECONDS", 0)
    tool = chat.tool()
    children: dict[str, str] = {}

    def child() -> Agent:
        return Agent(
            FakeModelClient(
                _replies(
                    AssistantMessage(
                        content=[ToolCall(id="send", name=tool.name, arguments={})]
                    )
                )
            ),
            generation_context=GenerationContext(flow=LLMFlow.CHAT_RESPONSE),
            tools=[_sending(tool)],
        )

    def delegate(invocation: ToolInvocation) -> ChildRunWait:
        for lifetime in (AgentLifetime.BACKGROUND, AgentLifetime.FOREGROUND):
            children[lifetime.value] = invocation.agents.spawn_agent(
                child(),
                name=lifetime.value,
                description=lifetime.value,
                messages=[UserMessage(content="Email the team")],
                max_steps=2,
                lifetime=lifetime,
            ).run_id
        return ChildRunWait(run_ids=[children[AgentLifetime.FOREGROUND.value]])

    owned = _start(
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
    background = owned.coordinator.completion(
        _until_value(lambda: children.get(AgentLifetime.BACKGROUND.value))
    ).result(timeout=10)
    send = background.steps[0].tools["send"].result
    assert send is not None and "this agent cannot ask for it" in send.text

    [row] = _until_value(lambda: chat.rows(db_session) or None)
    assert row.chat_message_id == int(children[AgentLifetime.FOREGROUND.value])
    chat.decide(db_session, row.id, ApprovalChoice.APPROVE_ONCE)
    until(lambda: _poll(owned) and owned.run.status.is_terminal)
    assert owned.run.result(timeout=10).output.text == "done"
    assert owned.first_result("delegate") == "done"


def _until_value[T](read: Callable[[], T | None]) -> T:
    value: T | None = None

    def ready() -> bool:
        nonlocal value
        value = read()
        return value is not None

    until(ready)
    assert value is not None
    return value


def _poll(owned: OwnedRun) -> bool:
    owned.owner.poll_control()
    return True


@pytest.fixture
def approval_waits_end() -> Generator[None, None, None]:
    try:
        yield
    finally:
        reset_approval_waits()


@pytest.mark.usefixtures("approval_waits_end")
def test_shutdown_ends_waiting_runs_and_expires_their_requests(
    db_session: Session, chat: ApprovalChat, owned_runs: list[OwnedRun]
) -> None:
    owned = _direct_call(chat, owned_runs)
    assert owned.run.wait_until_settled(10).status == RunStatus.SUSPENDED

    end_approval_waits()
    owned.owner.poll_control()

    with pytest.raises(AgentCancelled):
        owned.run.result(timeout=10)
    assert owned.run.wait_for_idle(10)
    assert [row.decision for row in chat.rows(db_session)] == [ApprovalDecision.EXPIRED]


@pytest.mark.usefixtures("approval_waits_end")
def test_a_call_after_shutdown_starts_does_not_ask(
    db_session: Session, chat: ApprovalChat, owned_runs: list[OwnedRun]
) -> None:
    end_approval_waits()

    owned = _direct_call(chat, owned_runs)

    assert owned.run.result(timeout=10).output.text == "done"
    assert "the server is restarting" in owned.first_result("send")
    assert chat.rows(db_session) == []


def test_a_stopped_program_call_expires_its_request_and_its_card_closes(
    db_session: Session, chat: ApprovalChat, owned_runs: list[OwnedRun]
) -> None:
    sent: list[str] = []

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

    owned = _start(
        chat,
        owned_runs,
        reply=reply,
        tools=[
            CodeModeTool([tool], cells=cells, limits=LIMITS).bind(ToolContext),
            WaitCodeTool(cells).bind(ToolContext),
        ],
        gated=[tool],
        on_event=ResponsePresenter(Emitter(live.append)).consume,
    )
    until(lambda: len(owned.run.pending_inputs) == 1)
    owned.owner.poll_control()

    call_waits.set()

    assert owned.run.result(timeout=10).output.text == "done"
    assert owned.run.wait_for_idle(10)
    stopped = owned.run.snapshot().steps[1].tools["stop"].result
    assert stopped is not None and "terminated" in stopped.text
    assert sent == []
    assert [row.decision for row in chat.rows(db_session)] == [ApprovalDecision.EXPIRED]
    [request] = [p.obj for p in live if isinstance(p.obj, ToolApprovalRequest)]
    assert [p.obj for p in live if isinstance(p.obj, ToolApprovalResolved)] == [
        ToolApprovalResolved(approval_id=request.approval_id, outcome="cancelled")
    ]


@pytest.mark.parametrize("wake", ["woken", "wake_lost"])
def test_the_owner_reads_a_decision_when_woken_or_at_the_fallback_read(
    db_session: Session,
    chat: ApprovalChat,
    owned_runs: list[OwnedRun],
    monkeypatch: pytest.MonkeyPatch,
    wake: str,
) -> None:
    monkeypatch.setattr(run_store, "APPROVAL_FALLBACK_POLL_SECONDS", 60.0)
    owned = _direct_call(chat, owned_runs)
    assert owned.run.wait_until_settled(10).status == RunStatus.SUSPENDED
    [request] = owned.run.pending_inputs
    # The first poll reads once; later polls read only when woken.
    owned.owner.poll_control()

    chat.decide(db_session, request.request_id, ApprovalChoice.APPROVE_ONCE)
    if wake == "wake_lost":
        get_cache_backend().delete(run_store._approval_wake_key(chat.response_id))
        owned.owner.poll_control()
        assert owned.run.pending_inputs == [request]
        # The fallback read comes due.
        owned.owner._next_approval_read = 0.0

    owned.owner.poll_control()

    assert owned.run.result(timeout=10).output.text == "done"
    assert owned.first_result("send") == "sent"
    assert [row.decision for row in chat.rows(db_session)] == [
        ApprovalDecision.APPROVED
    ]


def test_a_non_streaming_response_returns_with_every_request_that_waits(
    db_session: Session, chat: ApprovalChat
) -> None:
    """Parallel calls open their requests before their packets stream, so the
    early return waits for the packet of each request that waits."""
    approval_ids = [
        str(
            create_approval_request__no_commit(
                db_session,
                chat_session_id=chat.chat_session_id,
                chat_message_id=chat.response_id,
                gated_app_id=chat.gated_app_id,
                action_id=ACTION,
            )[0]
        )
        for _ in range(3)
    ]
    db_session.commit()
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
                expires_at=datetime.datetime.now(datetime.UTC) + TOOL_APPROVAL_TIMEOUT,
            ),
        )

    def packets() -> Iterator[AnswerStreamPart]:
        yield MessageResponseIDInfo(
            user_message_id=None, reserved_assistant_message_id=chat.response_id
        )
        # A request whose call stopped waiting ends before its row expires.
        yield request(ended)
        yield Packet(
            placement=Placement(turn_index=0),
            obj=ToolApprovalResolved(approval_id=ended, outcome="cancelled"),
        )
        yield request(approval_ids[0])
        yield request(approval_ids[1])
        raise AssertionError("The response read past the requests that wait")

    response = gather_stream_full(packets(), Future[ChatResponseOutcome]())

    assert [
        pending.approval_id for pending in response.pending_tool_approvals
    ] == approval_ids[:2]
