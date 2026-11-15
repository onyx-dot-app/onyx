"""Parked responses continue through real chat turns and dispatch, with a
scripted model and a scripted MCP tool that waits for approval.

The chat stays processing from the end of any turn to the start of the next
continuation, a continuation whose start fails for a moment retries without a
client, and the chat status reads several parked roots as roots. Integration
tests cover the same flows over HTTP, where these timings cannot be held."""

from collections.abc import Generator
from threading import Event, Lock
from typing import Any
from unittest.mock import MagicMock
from uuid import UUID, uuid4

import pytest
from fastapi import BackgroundTasks, Request
from sqlalchemy import delete, select
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
from onyx.configs.constants import DEFAULT_PERSONA_ID, DocumentSource
from onyx.context.search.models import BaseFilters
from onyx.db.chat import delete_messages_and_files_from_chat_session
from onyx.db.engine.sql_engine import get_session_with_current_tenant
from onyx.db.mcp import create_mcp_server__no_commit
from onyx.db.models import (
    ApprovalRequest,
    ChatMessage,
    ChatSession,
    MCPServer,
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
    get_chat_session_processing_status,
)
from onyx.server.query_and_chat.models import (
    ApprovalDecisionResponse,
    ChatApprovalDecisionRequest,
    ChatSessionProcessingStatus,
    SendMessageRequest,
)
from onyx.server.query_and_chat.streaming_models import (
    AWAITING_APPROVAL,
    OverallStop,
    Packet,
)
from onyx.tools.models import ChatToolSelection
from onyx.tools.tool_constructor import SearchToolConfig
from tests.external_dependency_unit.chat.test_parked_agent_handoff import _gated
from tests.external_dependency_unit.chat.test_wait_agents import (
    ScriptedLLM,
    _wait_until,
)
from tests.external_dependency_unit.conftest import MakeTestUser
from tests.unit.onyx.tools.code_mode.fakes import FakeMCPTool

# A status request without pass-through headers.
_NO_HEADERS = Request({"type": "http", "headers": []})
# Two models of one turn; the patched model factory serves both.
_TWO_MODELS = [LLMOverride(model_version="a"), LLMOverride(model_version="b")]


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

    def __init__(self, user: User, chat_session_id: UUID, server_id: int) -> None:
        self.user = user
        self.chat_session_id = chat_session_id
        self.sent: list[str] = []
        self.tool = _gated(server_id, self.sent)
        # The tool limits and search filters that each turn built its tools with.
        self.tool_limits: list[tuple[list[int] | None, BaseFilters | None]] = []

    def start(
        self,
        monkeypatch: pytest.MonkeyPatch,
        script: Script,
        *,
        models: list[LLMOverride] | None = None,
        selection: ChatToolSelection | None = None,
    ) -> list[OverallStop]:
        """Send a message, to several `models` if given and limited to the
        tools and search filters of `selection`; returns the stops of the
        turn."""

        def construct_tools(
            *,
            allowed_tool_ids: list[int] | None,
            search_tool_config: SearchToolConfig,
            **_kwargs: object,
        ) -> dict[int, list[FakeMCPTool]]:
            self.tool_limits.append(
                (allowed_tool_ids, search_tool_config.user_selected_filters)
            )
            return {self.tool.id: [self.tool]}

        monkeypatch.setattr("onyx.chat.execution.construct_tools", construct_tools)
        model = ScriptedLLM(script.generate)
        monkeypatch.setattr(
            "onyx.chat.process_message.get_llm_for_persona", lambda **_kwargs: model
        )
        request = SendMessageRequest(
            message="Email the team",
            chat_session_id=self.chat_session_id,
            **(selection.model_dump() if selection else {}),
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
    server = create_mcp_server__no_commit(
        owner_email=user.email,
        name=f"continuations_{uuid4().hex[:8]}",
        description=None,
        server_url="https://example.com/mcp",
        auth_type=None,
        transport=None,
        auth_performer=None,
        db_session=db_session,
    )
    chat = ChatSession(
        id=uuid4(),
        user_id=user.id,
        persona_id=DEFAULT_PERSONA_ID,
        description="approval continuations",
    )
    db_session.add(chat)
    db_session.commit()
    chat_id, server_id = chat.id, server.id
    try:
        yield ApprovalTurns(user, chat_id, server_id)
    finally:
        try:
            assert chat_turn_work.wait_idle(timeout=30)
        finally:
            db_session.rollback()
            delete_messages_and_files_from_chat_session(chat_id, db_session)
            # Cascades to the server's app identity and requests.
            db_session.execute(delete(MCPServer).where(MCPServer.id == server_id))
            db_session.commit()


def _park_both(
    turns: ApprovalTurns, monkeypatch: pytest.MonkeyPatch, script: Script
) -> list[ApprovalRequest]:
    stops = turns.start(monkeypatch, script, models=_TWO_MODELS)
    assert [stop.stop_reason for stop in stops] == [AWAITING_APPROVAL] * 2
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
    needed for the response to complete."""
    script = Script(turns.tool)
    stops = turns.start(monkeypatch, script)
    assert [stop.stop_reason for stop in stops] == [AWAITING_APPROVAL]
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

    _wait_until(
        lambda: turns.response_status(request.chat_message_id) == RunStatus.COMPLETE,
        "the response completes",
    )
    assert failures == []
    assert turns.sent == ["team"]


def test_a_continuation_keeps_the_tools_and_search_filters_of_its_request(
    turns: ApprovalTurns, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A request limits its turn to some tools and search filters that the
    chat does not save. Its response parks for approval and continues after
    the decision with the same limits, not with every tool of the agent."""
    selection = ChatToolSelection(
        allowed_tool_ids=[turns.tool.id],
        internal_search_filters=BaseFilters(source_type=[DocumentSource.WEB]),
    )
    stops = turns.start(monkeypatch, Script(turns.tool), selection=selection)
    assert [stop.stop_reason for stop in stops] == [AWAITING_APPROVAL]
    [request] = turns.requests()

    turns.decide(request)

    _wait_until(
        lambda: turns.response_status(request.chat_message_id) == RunStatus.COMPLETE,
        "the response completes",
    )
    assert turns.sent == ["team"]
    limits = (selection.allowed_tool_ids, selection.internal_search_filters)
    assert turns.tool_limits == [limits, limits]


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
