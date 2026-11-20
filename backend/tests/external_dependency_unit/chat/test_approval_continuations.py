"""Parked responses continue through real chat turns and dispatch, with a
scripted model and a scripted MCP tool that waits for approval.

The chat stays processing from the end of any turn to the start of the next
continuation, a continuation whose start fails for a moment retries without a
client, and the chat status reads several parked roots as roots. Integration
tests cover the same flows over HTTP, where these timings cannot be held."""

import json
from collections.abc import Generator
from threading import Event, Lock
from typing import Any
from unittest.mock import MagicMock, patch
from uuid import UUID, uuid4

import pytest
from fastapi import BackgroundTasks, Request
from sqlalchemy import select
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from onyx.agents.models import RunStatus
from onyx.cache.factory import get_cache_backend
from onyx.chat import process_message
from onyx.chat.chat_processing_checker import is_chat_session_processing
from onyx.chat.execution import chat_turn_work
from onyx.chat.process_message import (
    handle_multi_model_stream,
    handle_stream_message_objects,
)
from onyx.chat.run_store import ChatRunStore
from onyx.configs.constants import DEFAULT_PERSONA_ID, DocumentSource, MessageType
from onyx.context.search.models import BaseFilters
from onyx.db.chat import (
    create_new_chat_message,
    delete_messages_and_files_from_chat_session,
)
from onyx.db.engine.sql_engine import get_session_with_current_tenant
from onyx.db.enums import PluginInstallationPolicy
from onyx.db.models import (
    ApprovalRequest,
    ChatMessage,
    ChatResponseCheckpoint,
    ChatSession,
    User,
)
from onyx.llm.cancellation import CancellationSignal
from onyx.llm.models import (
    AssistantMessage,
    GenerationRequest,
    TextContent,
    ToolCall,
    ToolResultMessage,
)
from onyx.llm.override_models import LLMOverride
from onyx.server.features.action_policies.models import ApprovalChoice
from onyx.server.query_and_chat.chat_backend import (
    decide_approval,
    get_chat_session,
    get_chat_session_processing_status,
)
from onyx.server.query_and_chat.models import (
    ApprovalDecisionResponse,
    ChatApprovalDecisionRequest,
    ChatSessionProcessingStatus,
    SendMessageRequest,
)
from onyx.server.query_and_chat.streaming_models import (
    AWAITING_USER,
    OverallStop,
    Packet,
    ToolApprovalRequest,
)
from onyx.tools.models import CapabilityEntry, ToolOptions
from onyx.tools.tool_constructor import SearchToolConfig
from tests.external_dependency_unit.chat.test_parked_agent_handoff import (
    ACTION,
    _gated,
)
from tests.external_dependency_unit.chat.test_wait_agents import (
    ScriptedLLM,
    _wait_until,
)
from tests.external_dependency_unit.conftest import MakeTestUser
from tests.external_dependency_unit.integration_helpers import (
    delete_integrations,
    give_access,
    make_mcp_integration,
)
from tests.unit.onyx.tools.code_mode.fakes import FakeMCPTool

# A status request without pass-through headers.
_NO_HEADERS = Request({"type": "http", "headers": []})
# Two models of one turn; the patched model factory serves both.
_TWO_MODELS = [LLMOverride(model_version="a"), LLMOverride(model_version="b")]


@pytest.fixture(autouse=True)
def direct_tools() -> Generator[None, None, None]:
    """The scripted model calls the gated tool directly, so code mode is off;
    see the `code_mode` fixture in tests/external_dependency_unit/conftest.py."""
    with patch("onyx.chat.agent.CODE_MODE_ENABLED", False):
        yield


class Script:
    """Every response calls the gated tool, then answers once it has the
    result. With `hold_first_answer`, the first answer waits for `release`."""

    def __init__(self, tool: FakeMCPTool, *, hold_first_answer: bool = False) -> None:
        self.tool = tool
        self.release = Event()
        if not hold_first_answer:
            self.release.set()
        self.holding = Event()
        self._answers = 0
        self._lock = Lock()

    def generate(
        self, request: GenerationRequest, signal: CancellationSignal
    ) -> AssistantMessage:
        if request.messages and isinstance(request.messages[-1], ToolResultMessage):
            with self._lock:
                self._answers += 1
                first = self._answers == 1
            if first:
                self.holding.set()
                with signal.on_cancel(self.release.set):
                    assert self.release.wait(30)
            return AssistantMessage(content=[TextContent(text="done")])
        return AssistantMessage(
            content=[
                ToolCall(id="send", name=self.tool.name, arguments={"value": "team"})
            ]
        )


class ApprovalTurns:
    """A user's chat with the default agent and an MCP server whose one tool
    waits for approval. Reads and decisions use their own sessions, since
    turns read the user on their threads."""

    def __init__(self, user: User, chat_session_id: UUID, integration_id: int) -> None:
        self.user = user
        self.chat_session_id = chat_session_id
        self.sent: list[str] = []
        self.tool = _gated(integration_id, self.sent)
        # The tool limits and search filters that each turn built its tools with.
        self.tool_limits: list[tuple[ToolOptions | None, BaseFilters | None]] = []

    def start(
        self,
        monkeypatch: pytest.MonkeyPatch,
        script: Script,
        *,
        models: list[LLMOverride] | None = None,
        options: ToolOptions | None = None,
        additional_context: str | None = None,
    ) -> list[OverallStop]:
        """Send a message, to several `models` if given, limited to the tool
        `options` and with the request-only
        `additional_context`; returns the stops of the turn."""

        def construct_tools(
            *,
            tool_options: ToolOptions | None,
            search_tool_config: SearchToolConfig,
            **_kwargs: object,
        ) -> list[FakeMCPTool]:
            self.tool_limits.append(
                (tool_options, search_tool_config.user_selected_filters)
            )
            return [self.tool]

        monkeypatch.setattr("onyx.chat.execution.construct_tools", construct_tools)
        model = ScriptedLLM(script.generate)
        monkeypatch.setattr(
            "onyx.chat.process_message.get_llm_for_persona", lambda **_kwargs: model
        )
        request = SendMessageRequest(
            message="Email the team",
            chat_session_id=self.chat_session_id,
            additional_context=additional_context,
            tool_options=options,
        )
        return [
            packet.obj
            for packet in (
                handle_multi_model_stream(
                    new_msg_req=request, user=self.user, llm_overrides=models
                )
                if models
                else handle_stream_message_objects(new_msg_req=request, user=self.user)
            )
            if isinstance(packet, Packet) and isinstance(packet.obj, OverallStop)
        ]

    def requests(self) -> list[ApprovalRequest]:
        with get_session_with_current_tenant() as session:
            return list(
                session.scalars(
                    select(ApprovalRequest)
                    .where(ApprovalRequest.chat_session_id == self.chat_session_id)
                    .order_by(ApprovalRequest.chat_message_id)
                )
            )

    def decide(self, request: ApprovalRequest) -> ApprovalDecisionResponse:
        """Decide through the route, which dispatches the continuation."""
        with get_session_with_current_tenant() as session:
            return decide_approval(
                approval_id=request.id,
                body=ChatApprovalDecisionRequest(decision=ApprovalChoice.APPROVE_ONCE),
                request=_NO_HEADERS,
                user=self.user,
                db_session=session,
            )

    def status(self) -> ChatSessionProcessingStatus:
        return get_chat_session_processing_status(
            self.chat_session_id, BackgroundTasks(), _NO_HEADERS, user=self.user
        )

    def response_status(self, response_id: int) -> RunStatus | None:
        with get_session_with_current_tenant() as session:
            return session.get_one(ChatMessage, response_id).response_status


@pytest.fixture
def turns(
    db_session: Session, make_test_user: MakeTestUser
) -> Generator[ApprovalTurns, None, None]:
    user = make_test_user("approval_continuations")
    integration, _ = make_mcp_integration(
        db_session,
        server_url="https://example.com/mcp",
        name=f"continuations_{uuid4().hex[:8]}",
        tools=[ACTION],
    )
    give_access(
        db_session, [integration], installation_policy=PluginInstallationPolicy.DEFAULT
    )
    chat = ChatSession(
        id=uuid4(),
        user_id=user.id,
        persona_id=DEFAULT_PERSONA_ID,
        description="approval continuations",
    )
    db_session.add(chat)
    db_session.commit()
    chat_id, integration_id = chat.id, integration.id
    try:
        yield ApprovalTurns(user, chat_id, integration_id)
    finally:
        try:
            assert chat_turn_work.wait_idle(timeout=30)
        finally:
            db_session.rollback()
            delete_messages_and_files_from_chat_session(chat_id, db_session)
            delete_integrations(db_session, [integration_id])


def _park_both(
    turns: ApprovalTurns, monkeypatch: pytest.MonkeyPatch, script: Script
) -> list[ApprovalRequest]:
    stops = turns.start(monkeypatch, script, models=_TWO_MODELS)
    assert [stop.stop_reason for stop in stops] == [AWAITING_USER] * 2
    requests = turns.requests()
    assert len(requests) == 2
    return requests


def test_the_chat_stays_processing_after_a_turn_that_does_not_park(
    turns: ApprovalTurns, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Both models of a turn park. The first decision continues its response;
    the second comes while that continuation runs, so it names none. The
    continuation ends without parking and hands the chat to the second
    response's continuation: the chat never shows idle in between, so the
    first status read after the stream ends shows it processing."""
    script = Script(turns.tool, hold_first_answer=True)
    first, second = _park_both(turns, monkeypatch, script)
    prepare = process_message.prepare_chat_turn
    holding = Event()
    started = Event()
    proceed = Event()

    def held_prepare(*args: Any, **kwargs: Any) -> Any:
        if (
            holding.is_set()
            and kwargs.get("resumed_response_id") == second.chat_message_id
        ):
            started.set()
            assert proceed.wait(30)
        return prepare(*args, **kwargs)

    monkeypatch.setattr(process_message, "prepare_chat_turn", held_prepare)
    try:
        assert turns.decide(first).continuation is not None
        assert script.holding.wait(30)
        assert turns.decide(second).continuation is None
        holding.set()
        script.release.set()
        # The second continuation's preparation waits here, after the first
        # continuation's turn released the chat.
        _wait_until(started.is_set, "the second response's continuation starts")
        assert is_chat_session_processing(turns.chat_session_id, get_cache_backend())
        assert turns.status().is_processing
    finally:
        proceed.set()
        script.release.set()
    _wait_until(
        lambda: all(
            turns.response_status(request.chat_message_id) == RunStatus.COMPLETE
            for request in (first, second)
        ),
        "both responses complete",
    )
    assert turns.sent == ["team", "team"]


@pytest.mark.parametrize("failing_step", ["preparation", "resume"])
def test_a_continuation_that_fails_to_start_for_a_moment_retries_alone(
    turns: ApprovalTurns, monkeypatch: pytest.MonkeyPatch, failing_step: str
) -> None:
    """A continuation whose preparation, or whose run's resume, fails once
    with a transient storage error keeps its response parked, and the server
    retries it after a backoff. No status read or other client request is
    needed for the response to complete, and the chat shows processing
    until then."""
    script = Script(turns.tool)
    stops = turns.start(monkeypatch, script)
    assert [stop.stop_reason for stop in stops] == [AWAITING_USER]
    [request] = turns.requests()
    failures = [OperationalError("SELECT 1", {}, Exception("connection lost"))]
    prepare = process_message.prepare_chat_turn
    resume = ChatRunStore.resume

    def flaky_prepare(*args: Any, **kwargs: Any) -> Any:
        if kwargs.get("resumed_response_id") is not None and failures:
            raise failures.pop()
        return prepare(*args, **kwargs)

    def flaky_resume(store: ChatRunStore, *args: Any, **kwargs: Any) -> Any:
        if failures:
            raise failures.pop()
        return resume(store, *args, **kwargs)

    if failing_step == "preparation":
        monkeypatch.setattr(process_message, "prepare_chat_turn", flaky_prepare)
    else:
        monkeypatch.setattr(ChatRunStore, "resume", flaky_resume)

    turns.decide(request)
    idle_reads: list[ChatSessionProcessingStatus] = []

    def completed() -> bool:
        if turns.response_status(request.chat_message_id) == RunStatus.COMPLETE:
            return True
        status = turns.status()
        if (
            not status.is_processing
            and turns.response_status(request.chat_message_id) != RunStatus.COMPLETE
        ):
            idle_reads.append(status)
        return False

    _wait_until(completed, "the response completes")
    assert failures == []
    assert idle_reads == []
    assert turns.sent == ["team"]


def test_a_continuation_keeps_the_tools_and_search_filters_of_its_request(
    turns: ApprovalTurns, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A request limits its turn to some tools and search filters that the
    chat does not save. Its response parks for approval and continues after
    the decision with the same limits, not with every tool of the agent."""
    options = ToolOptions(
        allowed=[CapabilityEntry(tool_id=1)],
        internal_search_filters=BaseFilters(source_type=[DocumentSource.WEB]),
    )
    stops = turns.start(monkeypatch, Script(turns.tool), options=options)
    assert [stop.stop_reason for stop in stops] == [AWAITING_USER]
    [request] = turns.requests()

    turns.decide(request)

    _wait_until(
        lambda: turns.response_status(request.chat_message_id) == RunStatus.COMPLETE,
        "the response completes",
    )
    assert turns.sent == ["team"]
    limits = (options, options.internal_search_filters)
    assert turns.tool_limits == [limits, limits]


def test_a_parked_response_saves_no_request_context(
    turns: ApprovalTurns, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The request's additional context is never stored: the checkpoint of a
    response that parks for approval leaves it out, and the response still
    continues after the decision."""
    context = f"open tab {uuid4().hex}"
    stops = turns.start(monkeypatch, Script(turns.tool), additional_context=context)
    assert [stop.stop_reason for stop in stops] == [AWAITING_USER]
    [request] = turns.requests()
    with get_session_with_current_tenant() as session:
        checkpoint = session.get_one(ChatResponseCheckpoint, request.chat_message_id)
        assert context not in json.dumps(checkpoint.state)

    turns.decide(request)

    _wait_until(
        lambda: turns.response_status(request.chat_message_id) == RunStatus.COMPLETE,
        "the response completes",
    )
    assert turns.sent == ["team"]


def test_the_latest_page_reaches_back_to_a_waiting_reply(
    turns: ApprovalTurns, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A reply waits for approval and later messages push it above the
    latest page. The latest page still reaches back to that reply's question,
    so a client that loads only that page shows its waiting card. An older
    page keeps its own limit."""
    stops = turns.start(monkeypatch, Script(turns.tool))
    assert [stop.stop_reason for stop in stops] == [AWAITING_USER]
    [request] = turns.requests()
    with get_session_with_current_tenant() as session:
        last = session.get_one(ChatMessage, request.chat_message_id)
        question_id = last.parent_message_id
        for index in range(6):
            last = create_new_chat_message(
                chat_session_id=turns.chat_session_id,
                parent_message=last,
                message=f"later {index}",
                token_count=1,
                message_type=MessageType.USER
                if index % 2 == 0
                else MessageType.ASSISTANT,
                db_session=session,
            )

        page = get_chat_session(
            turns.chat_session_id, limit=2, user=turns.user, db_session=session
        )
        message_ids = {message.message_id for message in page.messages}
        assert {question_id, request.chat_message_id} <= message_ids
        assert any(
            isinstance(packet.obj, ToolApprovalRequest)
            for packets in page.packets
            for packet in packets
        )
        assert page.has_older_messages

        older = get_chat_session(
            turns.chat_session_id,
            limit=2,
            before_message_id=question_id,
            user=turns.user,
            db_session=session,
        )
        assert len(older.messages) <= 2


def test_two_decided_roots_are_not_agents(
    turns: ApprovalTurns, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Two parked roots whose requests are decided wait to continue as
    roots; the status does not report them as active agents."""
    first, second = _park_both(turns, monkeypatch, Script(turns.tool))
    # The roots stay parked: no decision continues them.
    monkeypatch.setattr(
        "onyx.server.query_and_chat.chat_backend.dispatch_pending_chat_messages",
        MagicMock(),
    )
    turns.decide(first)
    turns.decide(second)

    assert not turns.status().has_active_subagents
