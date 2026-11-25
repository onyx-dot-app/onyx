"""What chat approval requests do below the HTTP API: a run that hands off
while its calls wait and resumes in a fresh store with the saved decisions,
claims, child runs, stopped program calls, the end of an unresumable response,
and which requests a non-streaming response returns. Integration tests cover
the decision API, dispatch, policies, session grants and blocked sends."""

import json
import subprocess
import sys
import threading
from collections.abc import Callable, Generator, Sequence
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch
from uuid import UUID, uuid4

import pytest
from azure.core.exceptions import HttpResponseError, ServiceResponseError
from botocore.exceptions import ClientError
from google.api_core.exceptions import Forbidden, ServiceUnavailable
from pydantic import BaseModel, ConfigDict, JsonValue, ValidationError
from sqlalchemy import delete, select, update
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from onyx.agents.agent_coordination import AgentCoordinator
from onyx.agents.events import AgentEvent
from onyx.agents.models import AgentState, ExecutionCheckpoint, RunStatus
from onyx.agents.runtime import Agent, Run
from onyx.agents.tools import (
    AgentTool,
    ChildRunWait,
    ToolInvocation,
)
from onyx.cache.factory import get_cache_backend
from onyx.chat import restoration, run_store
from onyx.chat.emitter import Emitter
from onyx.chat.models import (
    ChatFeatureState,
    ChatInbox,
)
from onyx.chat.presentation import ResponsePresenter
from onyx.chat.run_store import (
    RESUME_FAILED_MESSAGE,
    ChatRunStore,
    fail_suspended_response,
)
from onyx.chat.tool_questions import CANCELLED_QUESTION_MESSAGE
from onyx.configs.constants import DEFAULT_PERSONA_ID, MessageType
from onyx.db.approval_request import create_approval_request__no_commit
from onyx.db.chat import delete_messages_and_files_from_chat_session
from onyx.db.chat_inputs import read_chat_inbox
from onyx.db.engine.sql_engine import SqlEngine, get_session_with_tenant
from onyx.db.enums import (
    ApprovalDecidedVia,
    ApprovalDecision,
    IntegrationActionPolicyValue,
    PluginInstallationPolicy,
    QuestionAnsweredVia,
    QuestionOutcome,
)
from onyx.db.integration_policy import list_session_granted_actions
from onyx.db.models import (
    ApprovalRequest,
    ChatMessage,
    ChatResponseCheckpoint,
    ChatSession,
    QuestionRequest,
    User,
)
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.file_store.azure_blob_file_store import AzureBlobBackedFileStore
from onyx.file_store.file_store import get_default_file_store
from onyx.file_store.gcs_file_store import GCSBackedFileStore
from onyx.integrations.models import CallCredentials
from onyx.llm.cancellation import CancellationSignal
from onyx.llm.interfaces import GenerationContext
from onyx.llm.model_capabilities import ToolFamily
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
from onyx.server.query_and_chat.chat_backend import (
    _reject_while_user_input_waits,
    answer_questions,
    decide_approval,
    delete_chat_session_by_id,
)
from onyx.server.query_and_chat.models import (
    ApprovalDecisionResponse,
    ChatApprovalDecisionRequest,
    ChatQuestionAnswersRequest,
    QuestionAnswersResponse,
)
from onyx.server.query_and_chat.streaming_models import (
    Packet,
    ToolApprovalRequest,
    ToolApprovalResolved,
    ToolQuestionResolved,
)
from onyx.tools.interface import Tool as ChatTool
from onyx.tools.models import ToolApprovalDetails, ToolApprovalScope, ToolContext
from onyx.tools.tool_implementations.code_mode import sandbox
from onyx.tools.tool_implementations.code_mode.cells import (
    PARK_REFUSED_MESSAGE,
    CodeCells,
)
from onyx.tools.tool_implementations.code_mode.code_mode_tool import (
    CodeModeTool,
    WaitCodeTool,
)
from onyx.tools.tool_implementations.code_mode.shapes import OPENAI_CODE_MODE
from onyx.tools.tool_implementations.mcp.mcp_tool import MCPTool
from onyx.tools.tool_implementations.question.models import ToolQuestionAnswer
from onyx.tools.tool_implementations.question.question_tool import QuestionTool
from onyx.tools.tool_implementations.question.shapes import QUESTION_SHAPES
from onyx.tracing.flows import LLMFlow
from shared_configs.configs import POSTGRES_DEFAULT_SCHEMA_STANDARD_VALUE
from tests.external_dependency_unit.chat.test_run_store import (
    chat_agent,
)
from tests.external_dependency_unit.conftest import MakeTestUser
from tests.external_dependency_unit.integration_helpers import (
    delete_integrations,
    give_access,
    make_mcp_integration,
    set_policy,
)
from tests.unit.onyx.agents.fakes import FakeModelClient
from tests.unit.onyx.tools.code_mode.fakes import (
    LIMITS,
    FakeMCPTool,
    FakeTool,
    until,
)

ACTION = "send_email"


class ApprovalChat(BaseModel):
    """A user's chat session, with a saved turn, and an MCP server integration
    with one action."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    user: User
    integration_id: int
    chat_session_id: UUID
    question: UserMessage
    response_id: int

    def scope(self) -> ToolApprovalScope:
        return ToolApprovalScope(integration_id=self.integration_id, action_id=ACTION)

    def tool(self) -> MCPTool:
        """The server's tool as tool construction builds it for an ASK policy."""
        return MCPTool(
            integration_id=self.integration_id,
            integration_name="approvals",
            integration_description=None,
            server_url="https://example.com/mcp",
            transport=None,
            tool_name=ACTION,
            tool_description="",
            tool_definition={"displayName": "Send email"},
            acting_user_id=self.user.id,
            credentials=CallCredentials(
                integration_id=self.integration_id,
                auth_method=None,
                connection_id=None,
                connection_user_id=None,
                headers={},
            ),
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

    def answer(
        self,
        db_session: Session,
        question_request_id: UUID,
        body: ChatQuestionAnswersRequest,
    ) -> QuestionAnswersResponse:
        """Save an answer to the response's questions, without the dispatch."""
        with patch(
            "onyx.server.query_and_chat.chat_backend.dispatch_pending_chat_messages"
        ):
            return answer_questions(
                question_request_id=question_request_id,
                body=body,
                request=MagicMock(headers={}),
                user=self.user,
                db_session=db_session,
            )

    def questions(self, db_session: Session) -> list[QuestionRequest]:
        return list(
            db_session.scalars(
                select(QuestionRequest)
                .where(QuestionRequest.chat_session_id == self.chat_session_id)
                .execution_options(populate_existing=True)
            )
        )

    def asking(self) -> QuestionTool:
        """The response's question tool, as a turn that offers it builds it."""
        return QuestionTool(
            QUESTION_SHAPES[ToolFamily.OPENAI],
            tenant_id=POSTGRES_DEFAULT_SCHEMA_STANDARD_VALUE,
            chat_session_id=self.chat_session_id,
            response_id=self.response_id,
        )


@pytest.fixture
def chat(
    db_session: Session, make_test_user: MakeTestUser
) -> Generator[ApprovalChat, None, None]:
    user = make_test_user("tool_approval")
    integration, _ = make_mcp_integration(
        db_session,
        server_url="https://example.com/mcp",
        name=f"approvals_{uuid4().hex[:8]}",
        tools=[ACTION],
    )
    # The default agent uses each plugin the user runs.
    give_access(
        db_session, [integration], installation_policy=PluginInstallationPolicy.DEFAULT
    )
    integration_id = integration.id
    chat = _saved_turn(db_session, user, integration_id)
    try:
        yield chat
    finally:
        db_session.rollback()
        delete_messages_and_files_from_chat_session(chat.chat_session_id, db_session)
        delete_integrations(db_session, [integration_id])


def _saved_turn(db_session: Session, user: User, integration_id: int) -> ApprovalChat:
    """A new chat session of the user, with a saved question and its response."""
    chat_session = ChatSession(
        id=uuid4(),
        user_id=user.id,
        persona_id=DEFAULT_PERSONA_ID,
        description="approvals",
    )
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
    db_session.commit()
    return ApprovalChat(
        user=user,
        integration_id=integration_id,
        chat_session_id=chat_session.id,
        question=UserMessage(id=f"chat:{question.id}", content=question.message),
        response_id=response.id,
    )


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


def _resumable(db_session: Session, chat: ApprovalChat) -> list[int]:
    """The chat's resumable parked runs, by response ID."""
    db_session.expire_all()
    inbox = read_chat_inbox(db_session, chat.chat_session_id)
    db_session.rollback()
    return [run.response_id for run in inbox.resumable_runs]


def _resume_direct_call_in_process(
    chat_session_id: str, response_id: str, user_id: str, integration_id: str
) -> None:
    """Resume the handed-off response with fresh objects and its saved
    decision, as another API pod does."""
    SqlEngine.init_engine(pool_size=5, max_overflow=5)
    try:
        with get_session_with_tenant(
            tenant_id=POSTGRES_DEFAULT_SCHEMA_STANDARD_VALUE
        ) as session:
            user = session.get_one(User, UUID(user_id))
            session.expunge_all()
        chat = ApprovalChat(
            user=user,
            integration_id=int(integration_id),
            chat_session_id=UUID(chat_session_id),
            question=UserMessage(content="Email the team"),
            response_id=int(response_id),
        )
        tool = chat.tool()
        sent: list[str] = []
        owned_runs: list[OwnedRun] = []
        resumed = _resume(
            chat,
            owned_runs,
            reply=_calls(tool, "send"),
            tools=[_recording(tool, sent)],
            gated=[tool],
        )
        assert resumed is not None
        try:
            assert resumed.run.result(timeout=30).output.text == "done"
            assert resumed.run.wait_for_idle(30)
            assert resumed.first_result("send") == "sent"
            assert sent == ["send"]
        finally:
            assert resumed.coordinator.close(timeout=10)
    finally:
        SqlEngine.reset_engine()


def test_a_waiting_direct_call_hands_off_and_another_process_resumes_it(
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
    # The card shows the call's own arguments, so the request keeps no copy.
    progress = owned.run.snapshot().progress
    assert progress is not None
    assert [request.display_arguments for request in progress.input_requests] == [None]

    db_session.expire_all()
    response = db_session.get(ChatMessage, chat.response_id)
    assert response is not None and response.response_status == RunStatus.SUSPENDED
    assert db_session.get(ChatResponseCheckpoint, chat.response_id) is not None
    assert run_store.ownerless_response_ids(get_cache_backend(), [chat.response_id])
    db_session.rollback()
    [row] = chat.rows(db_session)
    assert row.decision is None
    assert row.arguments == {}
    assert _resumable(db_session, chat) == []

    chat.decide(db_session, row.id, ApprovalChoice.APPROVE_ONCE)
    assert _resumable(db_session, chat) == [chat.response_id]
    completed = subprocess.run(
        [
            sys.executable,
            "-c",
            "import sys; from tests.external_dependency_unit.chat."
            "test_chat_tool_approvals import _resume_direct_call_in_process; "
            "_resume_direct_call_in_process(*sys.argv[1:])",
            str(chat.chat_session_id),
            str(chat.response_id),
            str(chat.user.id),
            str(chat.integration_id),
        ],
        cwd=Path(__file__).resolve().parents[3],
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr

    # This process ran nothing; the other one ran the approved call.
    assert sent == []
    db_session.expire_all()
    response = db_session.get(ChatMessage, chat.response_id)
    assert response is not None and response.response_status == RunStatus.COMPLETE
    assert db_session.get(ChatResponseCheckpoint, chat.response_id) is None
    db_session.rollback()
    assert [row.decision for row in chat.rows(db_session)] == [
        ApprovalDecision.APPROVED
    ]


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
    assert _resumable(db_session, chat) == [chat.response_id]
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
    # Saves the rejection, gives it to the run, and cancels the run.
    owned.owner.reject_waiting_inputs()
    assert owned.run.wait_for_idle(10)
    assert owned.run.status == RunStatus.CANCELLED
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


_CARD = ChatQuestionAnswersRequest(
    answers=[ToolQuestionAnswer(question_id="scope", option_labels=["Company"])]
)


def _asks(tool: QuestionTool) -> Callable[..., AssistantMessage]:
    """The model asks one question with `tool`, then answers "done"."""
    return _replies(
        AssistantMessage(
            content=[
                ToolCall(
                    id="ask",
                    name=tool.name,
                    arguments={
                        "questions": [
                            {
                                "id": "scope",
                                "header": "Scope",
                                "question": "Who should get the email?",
                                "options": [
                                    {"label": "Team", "description": "The team."},
                                    {"label": "Company", "description": "All."},
                                ],
                            }
                        ]
                    },
                )
            ]
        )
    )


@pytest.mark.parametrize("first", ["answer", "stop"])
def test_an_answer_and_a_stop_of_the_live_turn_keep_the_first(
    db_session: Session, chat: ApprovalChat, owned_runs: list[OwnedRun], first: str
) -> None:
    """A Stop cancels the question that the live run waits on, and the call
    keeps the result of whichever came first, so the next turn's history has
    it. The card shows how the question ended."""
    tool = chat.asking()
    ended: list[ToolQuestionResolved] = []
    owned = _start(
        chat,
        owned_runs,
        reply=_asks(tool),
        tools=[tool.bind(ToolContext)],
        gated=[],
        on_event=ResponsePresenter(
            Emitter(
                lambda packet: (
                    ended.append(packet.obj)
                    if isinstance(packet.obj, ToolQuestionResolved)
                    else None
                )
            )
        ).consume,
    )
    assert owned.run.wait_until_settled(10).status == RunStatus.SUSPENDED
    [row] = chat.questions(db_session)
    db_session.commit()

    if first == "answer":
        chat.answer(db_session, row.id, _CARD)
    owned.owner.reject_waiting_inputs()
    assert owned.run.wait_for_idle(10)
    assert owned.run.status == RunStatus.CANCELLED
    if first == "stop":
        with pytest.raises(OnyxError) as conflict:
            chat.answer(db_session, row.id, _CARD)
        assert conflict.value.error_code == OnyxErrorCode.CONFLICT

    [saved] = chat.questions(db_session)
    assert saved.outcome == (
        QuestionOutcome.ANSWERED if first == "answer" else QuestionOutcome.CANCELLED
    )
    assert owned.first_result("ask") == (
        json.dumps({"answers": {"scope": {"answers": ["Company"]}}})
        if first == "answer"
        else CANCELLED_QUESTION_MESSAGE
    )
    assert [resolved.outcome for resolved in ended] == [
        "answered" if first == "answer" else "cancelled"
    ]


def test_a_typed_answer_waits_for_the_responses_approval_requests(
    db_session: Session, chat: ApprovalChat, owned_runs: list[OwnedRun]
) -> None:
    """A typed message answers the response's questions only once no approval
    request of the response waits; the card still answers its question."""
    tool = chat.asking()
    _hand_off(
        _start(
            chat,
            owned_runs,
            reply=_asks(tool),
            tools=[tool.bind(ToolContext)],
            gated=[],
        )
    )
    create_approval_request__no_commit(
        db_session,
        chat_session_id=chat.chat_session_id,
        chat_message_id=chat.response_id,
        integration_id=chat.integration_id,
        action_id=ACTION,
        tool_call_id="send",
        tool_name=ACTION,
        display_name="Send email",
        arguments={},
    )
    db_session.commit()
    [row] = chat.questions(db_session)
    with pytest.raises(OnyxError) as pending:
        chat.answer(db_session, row.id, ChatQuestionAnswersRequest(message="Team"))
    assert pending.value.error_code == OnyxErrorCode.APPROVAL_PENDING
    db_session.rollback()
    chat.answer(db_session, row.id, _CARD)
    [saved] = chat.questions(db_session)
    assert (saved.outcome, saved.answered_via) == (
        QuestionOutcome.ANSWERED,
        QuestionAnsweredVia.CARD,
    )
    # The approval request still waits, so the response stays parked.
    assert _resumable(db_session, chat) == []


def test_a_call_whose_integration_was_deleted_is_disabled(
    db_session: Session, chat: ApprovalChat, owned_runs: list[OwnedRun]
) -> None:
    """Deleting the integration keeps the request with no integration. An
    approval of it saves a rejection by the policy; the response resumes, and
    the call reads that its tool is disabled."""
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
    delete_integrations(db_session, [chat.integration_id])
    decided = chat.decide(db_session, row.id, ApprovalChoice.APPROVE_ONCE)
    assert (decided.decision, decided.decided_via) == (
        ApprovalDecision.REJECTED,
        ApprovalDecidedVia.POLICY,
    )
    [row] = chat.rows(db_session)
    assert row.integration_id is None
    assert _resumable(db_session, chat) == [chat.response_id]

    resumed = _resume(
        chat,
        owned_runs,
        reply=_calls(tool, "send"),
        tools=[_recording(tool, sent)],
        gated=[tool],
    )

    assert resumed is not None
    assert resumed.run.result(timeout=10).output.text == "done"
    assert resumed.first_result("send") == (
        f"The {tool.name} tool is disabled, so this call did not run."
    )
    assert sent == []


def test_a_request_keys_on_the_integration_with_no_gated_app(
    db_session: Session, chat: ApprovalChat, owned_runs: list[OwnedRun]
) -> None:
    """An integration made after the upgrade has no gated_app row: the
    request writes its integration and no gated_app."""
    owned = _direct_call(chat, owned_runs)

    assert owned.run.wait_until_settled(10).status == RunStatus.SUSPENDED
    [row] = chat.rows(db_session)
    assert row.integration_id == chat.integration_id
    assert row.gated_app_id is None


def test_a_request_stores_its_arguments_without_nul_characters(
    db_session: Session, chat: ApprovalChat, owned_runs: list[OwnedRun]
) -> None:
    """PostgreSQL stores no NUL character, so the request's copy of the call
    for its card and the checkpoint of the parked response leave it out. The
    call waits for approval, its response parks, and a fresh store resumes it
    after the decision."""
    tool = chat.tool()
    reply = _replies(
        AssistantMessage(
            content=[
                ToolCall(id="send", name=tool.name, arguments={"value": "team\x00mail"})
            ]
        )
    )
    owned = _start(chat, owned_runs, reply=reply, tools=[_sending(tool)], gated=[tool])

    assert owned.run.wait_until_settled(10).status == RunStatus.SUSPENDED
    [row] = chat.rows(db_session)
    assert row.arguments == {"value": "teammail"}
    _hand_off(owned)
    assert _parked(chat.response_id)

    chat.decide(db_session, row.id, ApprovalChoice.APPROVE_ONCE)
    resumed = _resume(
        chat, owned_runs, reply=reply, tools=[_sending(tool)], gated=[tool]
    )
    assert resumed is not None
    assert resumed.run.result(timeout=10).output.text == "done"


def _foreground_agent(
    chat: ApprovalChat,
    owned_runs: list[OwnedRun],
    sent: list[str],
    *,
    alongside: AgentTool | None = None,
) -> OwnedRun:
    """A root that waits for a foreground agent, which calls the gated tool,
    and answers with its answer. The root calls `alongside` in the same step,
    if given."""
    tool = chat.tool()

    def delegate(invocation: ToolInvocation) -> ChildRunWait:
        return ChildRunWait(
            run_ids=[
                invocation.agents.spawn_agent(
                    Agent(
                        FakeModelClient(_calls(tool, "send")),
                        generation_context=GenerationContext(
                            flow=LLMFlow.CHAT_RESPONSE
                        ),
                        tools=[_recording(tool, sent)],
                    ),
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
                content=[
                    ToolCall(id="delegate", name="delegate", arguments={}),
                    *(
                        [
                            ToolCall(
                                id="alongside",
                                name=alongside.definition.name,
                                arguments={},
                            )
                        ]
                        if alongside
                        else []
                    ),
                ]
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
            ),
            *([alongside] if alongside else []),
        ],
        gated=[tool],
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


def test_a_foreground_agent_asks_parks_and_resumes_in_a_fresh_store(
    db_session: Session, chat: ApprovalChat, owned_runs: list[OwnedRun]
) -> None:
    """An agent's call waits durably: the agent's run parks, and its parent
    parks after it, in one control poll of the store. After the decision, a
    fresh store resumes the agent at its depth, then the parent once the
    agent ended."""
    sent: list[str] = []
    owned = _foreground_agent(chat, owned_runs, sent)
    until(lambda: _poll(owned) and len(chat.rows(db_session)) == 1)
    [row] = chat.rows(db_session)
    child_id = row.chat_message_id
    assert child_id != chat.response_id
    until(lambda: _poll(owned) and _parked(child_id) and _parked(chat.response_id))
    assert _inbox(chat).resumable_runs == []

    chat.decide(db_session, row.id, ApprovalChoice.APPROVE_ONCE)
    assert [run.response_id for run in _inbox(chat).resumable_runs] == [child_id]

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
    assert [run.response_id for run in _inbox(chat).resumable_runs] == [
        chat.response_id
    ]
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


def test_a_stop_rejects_the_requests_of_a_foreground_agent_that_parked(
    db_session: Session, chat: ApprovalChat, owned_runs: list[OwnedRun]
) -> None:
    """A foreground agent parks while another call keeps the root live, so
    the store no longer owns the agent's run. The user's Stop still saves the
    rejection of the agent's request, rather than leaving it to expire."""
    release = threading.Event()

    def slow(_invocation: ToolInvocation) -> ToolResult:
        assert release.wait(30)
        return ToolResult(content="slow")

    owned = _foreground_agent(
        chat,
        owned_runs,
        [],
        alongside=AgentTool(
            definition=ToolDefinition(name="slow", description="", parameters={}),
            execute=slow,
        ),
    )
    try:
        until(lambda: _poll(owned) and len(chat.rows(db_session)) == 1)
        [row] = chat.rows(db_session)
        until(lambda: _poll(owned) and _parked(row.chat_message_id))
        assert not _parked(chat.response_id)

        owned.owner.reject_waiting_inputs()

        [row] = chat.rows(db_session)
        assert row.decision == ApprovalDecision.REJECTED
        assert row.decided_via == ApprovalDecidedVia.USER
    finally:
        release.set()
    # The cancelled root ends once its other call returns.
    until(lambda: _poll(owned) and not owned.owner.has_owned_work)


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
    cells = CodeCells(OPENAI_CODE_MODE)
    live: list[Packet] = []
    call_waits = threading.Event()

    def reply(
        request: GenerationRequest, _signal: CancellationSignal
    ) -> AssistantMessage:
        """Start a program that yields, then waits on the call; once the call
        waits, stop the program's cell."""
        last = request.messages[-1] if request.messages else None
        if not isinstance(last, ToolResultMessage):
            code = (
                f"yield_control()\nawait tools.mcp__1__acme__{ACTION}(value='team')\n"
            )
            return AssistantMessage(
                content=[ToolCall(id="program", name="exec", arguments={"code": code})]
            )
        if last.tool_call_id == "program":
            assert call_waits.wait(10)
            return AssistantMessage(
                content=[
                    ToolCall(
                        id="stop",
                        name="wait",
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
    code_tool = CodeModeTool([tool], cells=cells, limits=PARKING_LIMITS)
    owned = _start(
        chat,
        owned_runs,
        reply=reply,
        tools=[
            code_tool.bind(ToolContext),
            WaitCodeTool(cells, code_tool.program).bind(ToolContext),
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


_SEND_PROGRAM = f"await tools.mcp__1__acme__{ACTION}(value='team')\n"


def _program(
    chat: ApprovalChat,
    owned_runs: list[OwnedRun],
    tool: ChatTool,
    code: str = _SEND_PROGRAM,
    on_event: Callable[[AgentEvent], None] = lambda _event: None,
) -> OwnedRun:
    """A chat response whose code mode program calls the gated tool."""
    owner = _store(chat, [tool])
    coordinator = AgentCoordinator()
    agent = chat_agent(
        FakeModelClient(
            _replies(
                AssistantMessage(
                    content=[
                        ToolCall(id="program", name="exec", arguments={"code": code})
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
        run=agent.start(
            messages=[chat.question],
            max_steps=3,
            coordinator=view,
            on_event=on_event,
        ),
    )
    owned_runs.append(owned)
    return owned


@pytest.fixture
def dumps(chat: ApprovalChat) -> Generator[Callable[[], list[str]], None, None]:
    """The file IDs of the chat's checkpoint files; teardown deletes them."""
    file_store = get_default_file_store()
    prefix = f"agent-checkpoint/{chat.chat_session_id}/"

    def listed() -> list[str]:
        return [record.file_id for record in file_store.list_files_by_prefix(prefix)]

    try:
        yield listed
    finally:
        for file_id in listed():
            file_store.delete_file(file_id, error_on_missing=False)


def test_an_unresumable_response_fails_and_drops_its_saved_state(
    db_session: Session,
    chat: ApprovalChat,
    owned_runs: list[OwnedRun],
    dumps: Callable[[], list[str]],
) -> None:
    """A response whose model or saved state is gone cannot continue: it is
    saved as failed, and its checkpoint and its parked program's dump go."""
    sent: list[str] = []
    _hand_off(_program(chat, owned_runs, _gated_function(chat, sent)))
    assert len(dumps()) == 1

    fail_suspended_response(
        get_cache_backend(), POSTGRES_DEFAULT_SCHEMA_STANDARD_VALUE, chat.response_id
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
    assert [row.decision for row in chat.rows(db_session)] == [ApprovalDecision.EXPIRED]
    assert dumps() == []
    assert sent == []


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


def test_a_saved_decision_repeated_after_the_tool_is_disabled_returns_it(
    db_session: Session, chat: ApprovalChat
) -> None:
    """A retry whose first attempt saved the decision, but lost its HTTP
    response, gets the saved decision, also after an admin disables the tool."""
    approval_id = create_approval_request__no_commit(
        db_session,
        chat_session_id=chat.chat_session_id,
        chat_message_id=chat.response_id,
        integration_id=chat.integration_id,
        action_id=ACTION,
        tool_call_id="send",
        tool_name=ACTION,
        display_name="Send email",
        arguments={"to": "team"},
    )
    db_session.execute(
        update(ApprovalRequest)
        .where(ApprovalRequest.id == approval_id)
        .values(
            decision=ApprovalDecision.APPROVED,
            decided_via=ApprovalDecidedVia.SESSION_GRANT,
        )
    )
    db_session.commit()
    set_policy(
        db_session,
        chat.integration_id,
        ACTION,
        IntegrationActionPolicyValue.BLOCKED,
    )

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


def test_a_park_refused_for_its_size_ends_the_request_and_does_not_block_sends(
    db_session: Session,
    chat: ApprovalChat,
    owned_runs: list[OwnedRun],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A program too large to pause ends its call's request: the request's
    row ends, its card resolves, the program continues without the call, and
    no response waits for the user."""
    # Any growth of the worker is over this share, so the dump is refused.
    monkeypatch.setattr(sandbox, "MAX_DUMP_MEMORY_SHARE", -1)
    sent: list[str] = []
    tool = _gated_function(chat, sent)
    live: list[Packet] = []
    owned = _start(
        chat,
        owned_runs,
        reply=_replies(
            AssistantMessage(
                content=[
                    ToolCall(
                        id="program",
                        name="exec",
                        arguments={
                            "code": f"await tools.mcp__1__acme__{ACTION}(value='team')\n"
                        },
                    )
                ]
            )
        ),
        tools=[
            CodeModeTool(
                [tool], cells=CodeCells(OPENAI_CODE_MODE), limits=PARKING_LIMITS
            ).bind(ToolContext)
        ],
        gated=[tool],
        on_event=ResponsePresenter(Emitter(live.append)).consume,
    )

    assert owned.run.result(timeout=20).output.text == "done"
    assert owned.run.wait_for_idle(10)
    assert PARK_REFUSED_MESSAGE.format(name=f"mcp__1__acme__{ACTION}") in (
        owned.first_result("program")
    )
    assert sent == []
    [row] = chat.rows(db_session)
    assert row.decision == ApprovalDecision.EXPIRED
    [request] = [p.obj for p in live if isinstance(p.obj, ToolApprovalRequest)]
    assert [p.obj for p in live if isinstance(p.obj, ToolApprovalResolved)] == [
        ToolApprovalResolved(approval_id=request.approval_id, outcome="cancelled")
    ]
    _reject_while_user_input_waits(db_session, chat.chat_session_id)


def _storage_error(code: str, status: int) -> ClientError:
    return ClientError(
        {
            "Error": {"Code": code},
            "ResponseMetadata": {
                "RequestId": "",
                "HostId": "",
                "HTTPStatusCode": status,
                "HTTPHeaders": {},
                "RetryAttempts": 0,
            },
        },
        "PutObject",
    )


def _azure_forbidden() -> HttpResponseError:
    error = HttpResponseError(message="This request is not authorized")
    error.status_code = 403
    return error


@pytest.mark.parametrize(
    "error, retries, file_store",
    [
        (OperationalError("SELECT 1", {}, Exception("connection lost")), True, None),
        (_storage_error("SlowDown", 503), True, None),
        (_storage_error("AccessDenied", 403), False, None),
        (ServiceResponseError("connection reset"), True, "azure"),
        (_azure_forbidden(), False, "azure"),
        (ServiceUnavailable("backend busy"), True, "gcs"),
        (Forbidden("access denied"), False, "gcs"),
    ],
    ids=[
        "database",
        "throttled",
        "access_denied",
        "azure_no_response",
        "azure_forbidden",
        "gcs_unavailable",
        "gcs_forbidden",
    ],
)
def test_a_park_that_fails_for_a_moment_keeps_the_run_and_its_dump_goes(
    chat: ApprovalChat,
    owned_runs: list[OwnedRun],
    dumps: Callable[[], list[str]],
    monkeypatch: pytest.MonkeyPatch,
    error: Exception,
    retries: bool,
    file_store: str | None,
) -> None:
    """A transient storage error while a run parks keeps the run waiting,
    deletes the dump that the attempt saved, and a later control poll parks
    it. A storage error that every attempt gets ends the run instead of
    retrying each second. The configured file store tells the two apart."""
    if file_store is not None:
        # Only the park's error check reads this store; dumps use the default.
        store = (
            AzureBlobBackedFileStore(
                container_name="parks", connection_string="UseDevelopmentStorage=true"
            )
            if file_store == "azure"
            else GCSBackedFileStore(bucket_name="parks")
        )
        monkeypatch.setattr(run_store, "get_default_file_store", lambda: store)
    owned = _program(chat, owned_runs, _gated_function(chat, []))
    assert owned.run.wait_until_settled(10).status == RunStatus.SUSPENDED
    assert owned.run.wait_for_idle(10)
    publish = run_store.publish_checkpoint__no_commit
    saved_before_publish: list[int] = []

    def flaky_publish(*args: Any, **kwargs: Any) -> list[str]:
        saved_before_publish.append(len(dumps()))
        if len(saved_before_publish) == 1:
            raise error
        return publish(*args, **kwargs)

    with patch.object(run_store, "publish_checkpoint__no_commit", flaky_publish):
        owned.owner.poll_control()
        assert not _parked(chat.response_id)
        assert dumps() == []
        if not retries:
            assert owned.run.cancellation_signal.cancelled
            assert owned.run.wait_until_settled(10).status == RunStatus.CANCELLED
            assert saved_before_publish == [1]
            return
        # The run waits, owned and not cancelled, without the saved dump.
        assert owned.run.status == RunStatus.SUSPENDED
        assert not owned.run.cancellation_signal.cancelled
        until(lambda: _poll(owned) and _parked(chat.response_id))
    # Each attempt saved one dump; the first one's is gone.
    assert saved_before_publish == [1, 1]
    assert len(dumps()) == 1


def test_a_failed_dump_save_deletes_the_dumps_saved_before_it(
    chat: ApprovalChat,
    owned_runs: list[OwnedRun],
    dumps: Callable[[], list[str]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A checkpoint with two parked programs saves a dump for each. When the
    second save fails, the first dump is deleted and the error reaches the
    park, which never learns that dump's ID."""
    owned = _program(chat, owned_runs, _gated_function(chat, []))
    assert owned.run.wait_until_settled(10).status == RunStatus.SUSPENDED
    assert owned.run.wait_for_idle(10)
    captured = owned.run.capture()
    progress = captured.run_state.progress
    assert progress is not None and progress.feature_state is not None
    state = ChatFeatureState.model_validate(progress.feature_state)
    [cell] = state.code_cells
    state.code_cells.append(
        cell.model_copy(
            update={
                "cell_id": cell.cell_id + 1,
                "observer": None
                if cell.observer is None
                else cell.observer.model_copy(update={"call_id": "second"}),
            },
            deep=True,
        )
    )
    progress.feature_state = state.model_dump(mode="json")
    store = get_default_file_store()
    save_file = store.save_file
    saves: list[str] = []

    def flaky_save(**kwargs: Any) -> str:
        saves.append(kwargs["file_id"])
        if len(saves) == 2:
            raise _storage_error("SlowDown", 503)
        return save_file(**kwargs)

    monkeypatch.setattr(store, "save_file", flaky_save)
    monkeypatch.setattr(restoration, "get_default_file_store", lambda: store)
    with pytest.raises(ClientError):
        restoration.persist_checkpoint_files(captured, session_id=chat.chat_session_id)
    assert len(saves) == 2
    assert dumps() == []


def test_a_response_that_parks_after_its_chat_was_deleted_ends(
    db_session: Session,
    chat: ApprovalChat,
    owned_runs: list[OwnedRun],
    dumps: Callable[[], list[str]],
) -> None:
    """A soft delete ends only the responses that are parked. One that still
    runs, such as a resume turn's, parks nothing afterwards: nobody could
    decide its requests. It ends, and its dump goes."""
    owned = _program(chat, owned_runs, _gated_function(chat, []))
    assert owned.run.wait_until_settled(10).status == RunStatus.SUSPENDED
    assert owned.run.wait_for_idle(10)

    delete_chat_session_by_id(
        chat.chat_session_id, hard_delete=False, user=chat.user, db_session=db_session
    )
    owned.owner.poll_control()

    assert owned.run.wait_until_settled(10).status == RunStatus.CANCELLED
    assert owned.run.wait_for_idle(10)
    assert not _parked(chat.response_id)
    assert dumps() == []
    assert [row.decision for row in chat.rows(db_session)] == [ApprovalDecision.EXPIRED]


def test_a_stopped_run_that_became_resumable_ends_instead_of_resuming(
    db_session: Session, chat: ApprovalChat, owned_runs: list[OwnedRun]
) -> None:
    """Stop subagents sets the Stop key before it commits the rejections that
    make a parked run resumable; a store that finds the run first ends it
    instead of running another step."""
    _hand_off(_direct_call(chat, owned_runs))
    run_store.request_response_stop(get_cache_backend(), chat.response_id, "user")
    [row] = chat.rows(db_session)
    chat.decide(db_session, row.id, ApprovalChoice.REJECT)
    tool = chat.tool()

    resumed = _resume(
        chat,
        owned_runs,
        reply=_calls(tool, "send"),
        tools=[_sending(tool)],
        gated=[tool],
    )

    assert resumed is None
    assert _status(chat.response_id) == RunStatus.CANCELLED
    assert not _parked(chat.response_id)


def test_soft_deleting_a_chat_ends_its_parked_response_and_its_dump(
    db_session: Session,
    chat: ApprovalChat,
    owned_runs: list[OwnedRun],
    dumps: Callable[[], list[str]],
) -> None:
    """Nothing can decide the requests of a deleted chat, so its parked
    responses end: the requests end and the checkpoint and its dump go."""
    _hand_off(_program(chat, owned_runs, _gated_function(chat, [])))
    assert len(dumps()) == 1

    delete_chat_session_by_id(
        chat.chat_session_id, hard_delete=False, user=chat.user, db_session=db_session
    )

    db_session.expire_all()
    response = db_session.get(ChatMessage, chat.response_id)
    assert response is not None and response.response_status == RunStatus.CANCELLED
    assert db_session.get(ChatResponseCheckpoint, chat.response_id) is None
    db_session.rollback()
    assert [row.decision for row in chat.rows(db_session)] == [ApprovalDecision.EXPIRED]
    assert dumps() == []


def test_a_parked_response_off_the_selected_branch_still_resumes(
    db_session: Session, chat: ApprovalChat, owned_runs: list[OwnedRun]
) -> None:
    """A parked response resumes after its decisions on any branch, such as
    a reply of another model or a branch that the user left; it does not
    block sends on the selected branch."""
    _hand_off(_direct_call(chat, owned_runs))
    response = db_session.get_one(ChatMessage, chat.response_id)
    question = db_session.get_one(ChatMessage, response.parent_message_id)
    sibling = ChatMessage(
        chat_session_id=chat.chat_session_id,
        parent_message_id=question.id,
        message="Another answer",
        token_count=2,
        message_type=MessageType.ASSISTANT,
    )
    db_session.add(sibling)
    db_session.flush()
    question.latest_child_message_id = sibling.id
    db_session.commit()
    _reject_while_user_input_waits(db_session, chat.chat_session_id)
    [row] = chat.rows(db_session)
    assert _resumable(db_session, chat) == []

    chat.decide(db_session, row.id, ApprovalChoice.APPROVE_ONCE)

    assert _resumable(db_session, chat) == [chat.response_id]


def test_a_suspended_response_without_its_checkpoint_is_repaired(
    db_session: Session, chat: ApprovalChat, owned_runs: list[OwnedRun]
) -> None:
    """A response is parked only while its checkpoint exists. One whose
    checkpoint is gone cannot resume; ownerless repair ends it, so it blocks
    neither sends nor anything that would resume it."""
    _hand_off(_direct_call(chat, owned_runs))
    [row] = chat.rows(db_session)
    chat.decide(db_session, row.id, ApprovalChoice.APPROVE_ONCE)
    db_session.execute(
        delete(ChatResponseCheckpoint).where(
            ChatResponseCheckpoint.chat_message_id == chat.response_id
        )
    )
    db_session.commit()

    assert _resumable(db_session, chat) == []
    unfinished = _inbox(chat).unfinished_response_ids
    assert chat.response_id in unfinished
    assert run_store.interrupt_ownerless_responses(
        get_cache_backend(), POSTGRES_DEFAULT_SCHEMA_STANDARD_VALUE, unfinished
    ) == {chat.response_id}
    assert _status(chat.response_id) == RunStatus.ERROR
    _reject_while_user_input_waits(db_session, chat.chat_session_id)


BUILTIN_ACTION = "onyx:library.delete"


class _LibraryTool(FakeTool):
    """A built-in tool whose `delete` operation asks the user."""

    def approval_details(
        self, arguments: dict[str, JsonValue]
    ) -> ToolApprovalDetails | None:
        name = arguments.get("name")
        if arguments.get("operation") != "delete" or not isinstance(name, str):
            return None
        return ToolApprovalDetails(
            display_name=f"Delete {name}", payload={"Delete": [name]}
        )


def _library(ran: list[str]) -> _LibraryTool:
    """The built-in tool with its gated action, recording each call that runs."""

    def run(invocation: ToolInvocation, _context: ToolContext) -> ToolResult:
        done = f"{invocation.arguments['operation']} {invocation.arguments['name']}"
        ran.append(done)
        return ToolResult(content=done)

    tool = _LibraryTool(
        "library",
        run,
        parameters={
            "type": "object",
            "properties": {
                "operation": {"type": "string"},
                "name": {"type": "string"},
            },
            "required": ["operation", "name"],
        },
    )
    tool.approval = ToolApprovalScope(integration_id=None, action_id=BUILTIN_ACTION)
    return tool


def _library_call(call_id: str, operation: str) -> ToolCall:
    return ToolCall(
        id=call_id,
        name="library",
        arguments={"operation": operation, "name": f"{call_id}.pdf"},
    )


def _approval_requests(live: list[Packet]) -> list[ToolApprovalRequest]:
    return [p.obj for p in live if isinstance(p.obj, ToolApprovalRequest)]


def test_a_builtin_call_that_does_not_ask_runs_without_a_request(
    db_session: Session, chat: ApprovalChat, owned_runs: list[OwnedRun]
) -> None:
    """The tool's hook decides each call before any database work, and the
    run, which opened no request, closes none when it ends."""
    ran: list[str] = []
    tool = _library(ran)
    with (
        patch.object(
            run_store, "open_tool_approval", side_effect=AssertionError("opened")
        ),
        patch.object(
            run_store,
            "close_pending_approval_requests__no_commit",
            wraps=run_store.close_pending_approval_requests__no_commit,
        ) as close,
    ):
        owned = _start(
            chat,
            owned_runs,
            reply=_replies(AssistantMessage(content=[_library_call("notes", "list")])),
            tools=[tool.bind(ToolContext)],
            gated=[tool],
        )
        assert owned.run.result(timeout=10).output.text == "done"
        until(lambda: not owned.owner.has_owned_work)
    close.assert_not_called()

    assert ran == ["list notes.pdf"]
    assert chat.rows(db_session) == []


@pytest.mark.parametrize("choice", [ApprovalChoice.APPROVE_ONCE, ApprovalChoice.REJECT])
def test_a_builtin_call_that_asks_waits_with_its_tools_card(
    db_session: Session,
    chat: ApprovalChat,
    owned_runs: list[OwnedRun],
    choice: ApprovalChoice,
) -> None:
    """The request and the live card show the hook's headline and payload.
    The user's decision is saved as made, and the resumed call runs or reads
    the rejection."""
    ran: list[str] = []
    tool = _library(ran)
    reply = _replies(AssistantMessage(content=[_library_call("report", "delete")]))
    live: list[Packet] = []
    owned = _start(
        chat,
        owned_runs,
        reply=reply,
        tools=[tool.bind(ToolContext)],
        gated=[tool],
        on_event=ResponsePresenter(Emitter(live.append)).consume,
    )
    _hand_off(owned)

    [row] = chat.rows(db_session)
    assert (row.integration_id, row.action_id) == (None, BUILTIN_ACTION)
    assert (row.display_name, row.arguments) == (
        "Delete report.pdf",
        {"Delete": ["report.pdf"]},
    )
    [card] = _approval_requests(live)
    assert (card.display_name, card.arguments) == (
        "Delete report.pdf",
        {"Delete": ["report.pdf"]},
    )
    approved = choice == ApprovalChoice.APPROVE_ONCE
    decided = chat.decide(db_session, row.id, choice)
    assert (decided.decision, decided.decided_via) == (
        ApprovalDecision.APPROVED if approved else ApprovalDecision.REJECTED,
        ApprovalDecidedVia.USER,
    )

    resumed = _resume(
        chat, owned_runs, reply=reply, tools=[tool.bind(ToolContext)], gated=[tool]
    )
    assert resumed is not None
    assert resumed.run.result(timeout=10).output.text == "done"
    if approved:
        assert ran == ["delete report.pdf"]
        assert resumed.first_result("report") == "delete report.pdf"
    else:
        assert ran == []
        assert resumed.first_result("report") == (
            "The user rejected this library call, so it did not run."
        )


def test_a_chat_grant_of_a_builtin_action_runs_later_calls_of_that_chat_only(
    db_session: Session, chat: ApprovalChat, owned_runs: list[OwnedRun]
) -> None:
    """ "Approve for this chat" approves the action's other waiting call, and
    a later call of the chat runs with no request. Another chat still asks."""
    other = _saved_turn(db_session, chat.user, chat.integration_id)
    try:
        ran: list[str] = []
        tool = _library(ran)

        def reply(
            request: GenerationRequest, _signal: CancellationSignal
        ) -> AssistantMessage:
            results = [m for m in request.messages if isinstance(m, ToolResultMessage)]
            if not results:
                return AssistantMessage(
                    content=[
                        _library_call("first", "delete"),
                        _library_call("second", "delete"),
                    ]
                )
            if len(results) == 2:
                return AssistantMessage(content=[_library_call("third", "delete")])
            return AssistantMessage(content=[TextContent(text="done")])

        _hand_off(
            _start(
                chat,
                owned_runs,
                reply=reply,
                tools=[tool.bind(ToolContext)],
                gated=[tool],
            )
        )
        first, _second = chat.rows(db_session)
        chat.decide(db_session, first.id, ApprovalChoice.APPROVE_SESSION)
        assert [(row.decision, row.decided_via) for row in chat.rows(db_session)] == [
            (ApprovalDecision.APPROVED, ApprovalDecidedVia.SESSION_GRANT)
        ] * 2
        assert list_session_granted_actions(
            db_session, chat.chat_session_id, [None, chat.integration_id]
        ) == {None: {BUILTIN_ACTION}, chat.integration_id: set()}

        resumed = _resume(
            chat,
            owned_runs,
            reply=reply,
            tools=[tool.bind(ToolContext)],
            gated=[tool],
        )
        assert resumed is not None
        assert resumed.run.result(timeout=10).output.text == "done"
        assert sorted(ran) == [
            "delete first.pdf",
            "delete second.pdf",
            "delete third.pdf",
        ]
        assert len(chat.rows(db_session)) == 2

        elsewhere = _start(
            other,
            owned_runs,
            reply=_replies(
                AssistantMessage(content=[_library_call("other", "delete")])
            ),
            tools=[tool.bind(ToolContext)],
            gated=[tool],
        )
        assert elsewhere.run.wait_until_settled(10).status == RunStatus.SUSPENDED
        assert [row.decision for row in other.rows(db_session)] == [None]
        assert "delete other.pdf" not in ran
    finally:
        db_session.rollback()
        delete_messages_and_files_from_chat_session(other.chat_session_id, db_session)


@pytest.mark.parametrize(
    "choice", [ApprovalChoice.APPROVE_ONCE, ApprovalChoice.APPROVE_SESSION]
)
def test_an_approval_of_a_builtin_request_is_never_a_policy_rejection(
    db_session: Session, chat: ApprovalChat, choice: ApprovalChoice
) -> None:
    """No policy covers a built-in action. A request whose integration was
    deleted also has no integration, and its approval is still rejected."""
    approvals = {
        action_id: create_approval_request__no_commit(
            db_session,
            chat_session_id=chat.chat_session_id,
            chat_message_id=chat.response_id,
            integration_id=None,
            action_id=action_id,
            tool_call_id=action_id,
            tool_name="library",
            display_name="Delete report.pdf",
            arguments={},
        )
        for action_id in (BUILTIN_ACTION, ACTION)
    }
    db_session.commit()

    decided = {
        action_id: chat.decide(db_session, approval_id, choice)
        for action_id, approval_id in approvals.items()
    }

    assert (decided[BUILTIN_ACTION].decision, decided[BUILTIN_ACTION].decided_via) == (
        ApprovalDecision.APPROVED,
        ApprovalDecidedVia.USER
        if choice == ApprovalChoice.APPROVE_ONCE
        else ApprovalDecidedVia.SESSION_GRANT,
    )
    assert (decided[ACTION].decision, decided[ACTION].decided_via) == (
        ApprovalDecision.REJECTED,
        ApprovalDecidedVia.POLICY,
    )


def test_a_builtin_program_call_asks_the_same_way(
    db_session: Session, chat: ApprovalChat, owned_runs: list[OwnedRun]
) -> None:
    """A code mode program's call that does not ask runs; one that asks waits
    on the program's card with the hook's card, and runs once approved."""
    ran: list[str] = []
    live: list[Packet] = []
    owned = _program(
        chat,
        owned_runs,
        _library(ran),
        "await tools.library(operation='list', name='notes.pdf')\n"
        "await tools.library(operation='delete', name='report.pdf')\n",
        on_event=ResponsePresenter(Emitter(live.append)).consume,
    )
    assert owned.run.wait_until_settled(10).status == RunStatus.SUSPENDED
    assert ran == ["list notes.pdf"]
    [row] = chat.rows(db_session)
    assert (row.tool_call_id, row.display_name, row.arguments) == (
        "program",
        "Delete report.pdf",
        {"Delete": ["report.pdf"]},
    )
    [card] = _approval_requests(live)
    assert (card.display_name, card.arguments) == (row.display_name, row.arguments)

    chat.decide(db_session, row.id, ApprovalChoice.APPROVE_ONCE)
    owned.owner.poll_control()

    assert owned.run.result(timeout=20).output.text == "done"
    assert ran == ["list notes.pdf", "delete report.pdf"]


def test_a_resumed_run_ends_the_requests_an_earlier_process_opened(
    db_session: Session, chat: ApprovalChat, owned_runs: list[OwnedRun]
) -> None:
    """The resuming store opened no request itself. When the resumed run
    ends, the request that it still waits on ends too."""
    ran: list[str] = []
    tool = _library(ran)
    reply = _replies(
        AssistantMessage(
            content=[
                _library_call("first", "delete"),
                _library_call("second", "delete"),
            ]
        )
    )
    _hand_off(
        _start(
            chat, owned_runs, reply=reply, tools=[tool.bind(ToolContext)], gated=[tool]
        )
    )
    rows = {row.tool_call_id: row for row in chat.rows(db_session)}
    chat.decide(db_session, rows["first"].id, ApprovalChoice.APPROVE_ONCE)

    resumed = _resume(
        chat, owned_runs, reply=reply, tools=[tool.bind(ToolContext)], gated=[tool]
    )
    assert resumed is not None
    assert resumed.run.wait_until_settled(10).status == RunStatus.SUSPENDED
    assert ran == ["delete first.pdf"]
    resumed.run.cancel()
    until(lambda: not resumed.owner.has_owned_work)

    assert {row.tool_call_id: row.decision for row in chat.rows(db_session)} == {
        "first": ApprovalDecision.APPROVED,
        "second": ApprovalDecision.EXPIRED,
    }


def test_the_hook_decides_on_the_arguments_that_the_call_runs_with(
    chat: ApprovalChat,
) -> None:
    """A call's displayed arguments can differ from the ones it runs with,
    such as a partial call's raw text. The hook sees the ones that run."""
    tool = _library([])
    call = ToolCall(
        id="notes",
        name="library",
        arguments={"operation": "list", "name": "notes.pdf"},
        raw_arguments='{"operation": "delete", "name": "notes.pdf"',
        arguments_complete=False,
    )
    with patch.object(
        run_store, "open_tool_approval", side_effect=AssertionError("opened")
    ):
        assert (
            _store(chat, [tool]).request_approval(
                MagicMock(spec=Run, id=str(chat.response_id)), call, None
            )
            is None
        )


def test_an_action_with_no_integration_needs_a_builtin_key() -> None:
    """Only a built-in action has no integration."""
    with pytest.raises(ValidationError):
        ToolApprovalScope(integration_id=None, action_id=ACTION)
    assert ToolApprovalScope(integration_id=None, action_id=BUILTIN_ACTION)
