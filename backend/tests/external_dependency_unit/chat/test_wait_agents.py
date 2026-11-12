"""The root waits for its agents with `wait_agents` and answers their results once.

Each test runs real chat turns against Postgres with a scripted model. Child
runs release through the run store, whose release event dispatches the root's
follow-up.
"""

import re
import time
from collections.abc import Callable, Generator
from threading import Event
from typing import override
from uuid import UUID, uuid4

import pytest
from fastapi import BackgroundTasks, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from onyx.agents.models import InputSource, RunStatus
from onyx.cache.factory import get_cache_backend
from onyx.chat import execution
from onyx.chat.execution import chat_turn_work
from onyx.chat.process_message import (
    dispatch_pending_chat_messages,
    handle_stream_message_objects,
)
from onyx.chat.run_store import RESPONSE_OWNER_KEY_PREFIX, stop_response
from onyx.configs.constants import DEFAULT_PERSONA_ID, MessageType
from onyx.db.chat_inputs import read_chat_inbox, withdraw_agent_result__no_commit
from onyx.db.engine.sql_engine import get_session_with_current_tenant
from onyx.db.models import ChatMessage, ChatResponseItem, ChatSession, User
from onyx.llm.cancellation import CancellationSignal
from onyx.llm.interfaces import LLMConfig
from onyx.llm.models import (
    AssistantMessage,
    GenerationRequest,
    TextContent,
    ToolCall,
    ToolResultMessage,
)
from onyx.server.query_and_chat import chat_backend
from onyx.server.query_and_chat.models import SendMessageRequest
from onyx.tools.constants import SPAWN_AGENT_TOOL_NAME, WAIT_AGENTS_TOOL_NAME
from shared_configs.contextvars import get_current_tenant_id
from tests.external_dependency_unit.conftest import MakeTestUser
from tests.unit.onyx.agents.fakes import FakeModelClient

WAIT_TIMEOUT_S = 30
WAITING = "Waiting for the workers."
STARTED = "The workers started."
QUESTION = "Ask the workers"
# A status request without pass-through headers.
_NO_HEADERS = Request({"type": "http", "headers": []})


class ScriptedLLM(FakeModelClient):
    @property
    @override
    def config(self) -> LLMConfig:
        return LLMConfig(
            model_provider="openai",
            model_name="gpt-4o-mini",
            max_input_tokens=32768,
            temperature=0,
        )


class Workers:
    """A root that starts named workers, then waits for some of them or answers.

    Each worker runs until the test releases it. A follow-up or a later turn
    answers with the names of the results that it can see.
    """

    def __init__(
        self,
        names: tuple[str, ...],
        *,
        wait_for: tuple[str, ...] | None,
        failing: frozenset[str] = frozenset(),
    ) -> None:
        self.names = names
        self.wait_for = wait_for
        self.failing = failing
        self.started = {name: Event() for name in names}
        self.release = {name: Event() for name in names}
        self.root_requests: list[GenerationRequest] = []
        self.first_turn_done = False

    def generate(
        self, request: GenerationRequest, signal: CancellationSignal
    ) -> AssistantMessage:
        texts = [message.text for message in request.messages]
        worker = next((name for name in self.names if f"Task {name}" in texts), None)
        if worker is not None:
            self.started[worker].set()
            with signal.on_cancel(self.release[worker].set):
                assert self.release[worker].wait(WAIT_TIMEOUT_S)
            signal.check()
            if worker in self.failing:
                raise RuntimeError(f"Worker {worker} failed")
            return _text(f"Result {worker}")
        self.root_requests.append(request)
        results = [
            message
            for message in request.messages
            if isinstance(message, ToolResultMessage)
        ]
        if not results:
            return AssistantMessage(
                content=[
                    ToolCall(
                        id=f"spawn-{name}",
                        name=SPAWN_AGENT_TOOL_NAME,
                        arguments={"name": name, "instruction": f"Task {name}"},
                    )
                    for name in self.names
                ]
            )
        if not self.first_turn_done:
            self.first_turn_done = True
            if self.wait_for is None:
                return _text(STARTED)
            agent_ids = {
                match[1]: match[2]
                for result in results
                if (
                    match := re.search(
                        r"/root/(\w+) \(agent_id: ([\w-]+)\)", result.text
                    )
                )
            }
            # The wait ends the run even beside another call.
            return AssistantMessage(
                content=[
                    TextContent(text=WAITING),
                    ToolCall(id="list", name="list_agents", arguments={}),
                    ToolCall(
                        id="wait",
                        name=WAIT_AGENTS_TOOL_NAME,
                        arguments={"agent_ids": [agent_ids[n] for n in self.wait_for]}
                        if self.wait_for != self.names
                        else {},
                    ),
                ]
            )
        seen = [name for name in self.names if f"Result {name}" in str(texts)]
        return _text(f"Answer with {', '.join(seen) or 'nothing'}")


def _text(text: str) -> AssistantMessage:
    return AssistantMessage(content=[TextContent(text=text)])


def _wait_until(condition: Callable[[], bool], description: str) -> None:
    deadline = time.monotonic() + WAIT_TIMEOUT_S
    while time.monotonic() < deadline:
        if condition():
            return
        time.sleep(0.05)
    raise AssertionError(f"Timed out waiting until {description}")


@pytest.fixture
def owner(make_test_user: MakeTestUser) -> User:
    return make_test_user("wait-agents-owner")


@pytest.fixture
def chat(db_session: Session, owner: User) -> ChatSession:
    chat = ChatSession(
        id=uuid4(),
        user_id=owner.id,
        persona_id=DEFAULT_PERSONA_ID,
        description="Wait for agents",
    )
    db_session.add(chat)
    db_session.commit()
    return chat


@pytest.fixture
def idle_turn_work() -> Generator[None, None, None]:
    yield
    assert chat_turn_work.wait_idle(timeout=WAIT_TIMEOUT_S)


def _start(
    chat: ChatSession,
    owner: User,
    workers: Workers,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Run the root's first turn; it ends while every worker still runs."""
    # Agent tools come from the chat agent; persona tools play no part here.
    monkeypatch.setattr("onyx.chat.execution.construct_tools", lambda **_kwargs: {})
    model = ScriptedLLM(workers.generate)
    monkeypatch.setattr(
        "onyx.chat.process_message.get_llm_for_persona", lambda **_kwargs: model
    )
    _send(chat, owner, QUESTION)
    for name in workers.names:
        assert workers.started[name].wait(WAIT_TIMEOUT_S)


def _send(chat: ChatSession, owner: User, message: str) -> None:
    for _packet in handle_stream_message_objects(
        new_msg_req=SendMessageRequest(
            message=message, chat_session_id=chat.id, accepts_follow_ups=True
        ),
        user=owner,
    ):
        pass


def _worker_responses(db_session: Session, chat_id: UUID) -> dict[str, ChatMessage]:
    db_session.expire_all()
    rows = db_session.execute(
        select(ChatSession.agent_name, ChatMessage)
        .join(ChatMessage, ChatMessage.chat_session_id == ChatSession.id)
        .where(
            ChatSession.spawned_by_message_id.in_(
                select(ChatMessage.id).where(ChatMessage.chat_session_id == chat_id)
            ),
            ChatMessage.message_type == MessageType.ASSISTANT,
        )
        .order_by(ChatMessage.id)
    ).all()
    return {name: response for name, response in rows if name is not None}


def _finish(
    db_session: Session,
    chat: ChatSession,
    workers: Workers,
    name: str,
    *,
    release: bool = True,
) -> ChatMessage:
    """Wait until a worker's run ends and releases, which dispatches.

    With `release`, the worker answers first; otherwise something stops it.
    """
    if release:
        workers.release[name].set()
    response = _worker_responses(db_session, chat.id)[name]
    cache = get_cache_backend()

    def released() -> bool:
        db_session.refresh(response)
        return (
            response.response_status is not None
            and response.response_status.is_terminal
            and not cache.exists(f"{RESPONSE_OWNER_KEY_PREFIX}{response.id}")
        )

    _wait_until(released, f"{name} finishes")
    return response


def _root_answers(db_session: Session, chat_id: UUID) -> list[ChatMessage]:
    db_session.expire_all()
    return list(
        db_session.scalars(
            select(ChatMessage)
            .where(
                ChatMessage.chat_session_id == chat_id,
                ChatMessage.message_type == MessageType.ASSISTANT,
            )
            .order_by(ChatMessage.id)
        )
    )


def _follow_ups(db_session: Session, chat_id: UUID) -> list[ChatMessage]:
    """Root answers under hidden results questions, oldest first."""
    return [
        answer
        for answer in _root_answers(db_session, chat_id)
        if answer.parent_message is not None
        and answer.parent_message.message_type == MessageType.AGENT_RESULTS
    ]


def _accepted_results(db_session: Session, answer: ChatMessage) -> list[int]:
    """The child runs whose results the answer's first step accepted."""
    first = db_session.scalar(
        select(ChatResponseItem).where(
            ChatResponseItem.chat_message_id == answer.id,
            ChatResponseItem.step_index == 0,
        )
    )
    assert first is not None
    return sorted(
        int(entry.source_run_id)
        for entry in first.inputs
        if entry.source == InputSource.AGENT_RESULT and entry.source_run_id
    )


def _settled(db_session: Session, chat_id: UUID, answers: int) -> None:
    def done() -> bool:
        latest = _root_answers(db_session, chat_id)
        return len(latest) == answers and all(
            answer.response_status is not None and answer.response_status.is_terminal
            for answer in latest
        )

    _wait_until(done, f"the root has {answers} finished answers")


class _DroppedDispatches:
    """Lose the release events of chosen runs, as when their host pod is gone."""

    def __init__(self) -> None:
        self.dropping = Event()
        self.dropped = 0

    def drop_next[T](self, finish: Callable[[], T]) -> T:
        before = self.dropped
        self.dropping.set()
        try:
            result = finish()
            _wait_until(lambda: self.dropped > before, "the release is dropped")
        finally:
            self.dropping.clear()
        return result


def _drop_dispatches(monkeypatch: pytest.MonkeyPatch) -> _DroppedDispatches:
    dropped = _DroppedDispatches()
    dispatch = execution.ChatTurnExecution._dispatch_after_release

    def dispatch_unless_dropped(self: execution.ChatTurnExecution) -> None:
        if dropped.dropping.is_set():
            dropped.dropped += 1
            return
        dispatch(self)

    monkeypatch.setattr(
        execution.ChatTurnExecution, "_dispatch_after_release", dispatch_unless_dropped
    )
    return dropped


@pytest.mark.usefixtures("idle_turn_work")
def test_the_root_waits_for_staggered_agents_and_answers_once(
    chat: ChatSession,
    owner: User,
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
    code_mode: bool,  # noqa: ARG001
) -> None:
    names = ("alpha", "beta", "gamma")
    workers = Workers(names, wait_for=names)
    _start(chat, owner, workers, monkeypatch)
    [waiting] = _root_answers(db_session, chat.id)
    assert waiting.response_status == RunStatus.COMPLETE
    assert waiting.message == WAITING
    # The wait ended the turn: one model call started the workers, one waited.
    assert len(workers.root_requests) == 2
    assert chat_backend.get_chat_session_processing_status(
        chat.id, BackgroundTasks(), _NO_HEADERS, owner
    ).has_active_subagents

    finished = [_finish(db_session, chat, workers, name) for name in names[:2]]
    # Each release dispatched; the wait holds both results.
    assert read_chat_inbox(db_session, chat.id).next_turn is None
    assert _follow_ups(db_session, chat.id) == []
    finished.append(_finish(db_session, chat, workers, names[2]))
    _settled(db_session, chat.id, 2)
    [follow_up] = _follow_ups(db_session, chat.id)
    assert follow_up.message == "Answer with alpha, beta, gamma"
    assert _accepted_results(db_session, follow_up) == sorted(
        response.id for response in finished
    )
    assert read_chat_inbox(db_session, chat.id).next_turn is None


@pytest.mark.usefixtures("idle_turn_work")
def test_without_a_wait_each_staggered_result_wakes_the_root(
    chat: ChatSession,
    owner: User,
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    names = ("alpha", "beta", "gamma")
    workers = Workers(names, wait_for=None)
    _start(chat, owner, workers, monkeypatch)
    for count, name in enumerate(names, start=1):
        _finish(db_session, chat, workers, name)
        _settled(db_session, chat.id, count + 1)
    assert [answer.message for answer in _follow_ups(db_session, chat.id)] == [
        "Answer with alpha",
        "Answer with alpha, beta",
        "Answer with alpha, beta, gamma",
    ]


@pytest.mark.usefixtures("idle_turn_work")
def test_results_that_finish_together_wake_the_root_once(
    chat: ChatSession,
    owner: User,
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    names = ("alpha", "beta")
    workers = Workers(names, wait_for=None)
    dropped = _drop_dispatches(monkeypatch)
    _start(chat, owner, workers, monkeypatch)
    # Alpha's release dispatches nothing, as if beta finished at the same time.
    dropped.drop_next(lambda: _finish(db_session, chat, workers, "alpha"))
    _finish(db_session, chat, workers, "beta")
    _settled(db_session, chat.id, 2)
    [follow_up] = _follow_ups(db_session, chat.id)
    assert follow_up.message == "Answer with alpha, beta"


@pytest.mark.usefixtures("idle_turn_work")
def test_an_unawaited_result_wakes_the_root_while_the_wait_stays_open(
    chat: ChatSession,
    owner: User,
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workers = Workers(("alpha", "beta", "gamma"), wait_for=("alpha", "gamma"))
    _start(chat, owner, workers, monkeypatch)
    beta = _finish(db_session, chat, workers, "beta")
    _settled(db_session, chat.id, 2)
    [interim] = _follow_ups(db_session, chat.id)
    assert interim.message == "Answer with beta"
    assert _accepted_results(db_session, interim) == [beta.id]
    # The wait outlives the interim answer: alpha's result waits for gamma.
    alpha = _finish(db_session, chat, workers, "alpha")
    assert read_chat_inbox(db_session, chat.id).next_turn is None
    assert len(_follow_ups(db_session, chat.id)) == 1
    gamma = _finish(db_session, chat, workers, "gamma")
    _settled(db_session, chat.id, 3)
    follow_ups = _follow_ups(db_session, chat.id)
    assert len(follow_ups) == 2
    assert _accepted_results(db_session, follow_ups[1]) == sorted([alpha.id, gamma.id])
    # The follow-up read the awaited results, so the wait cannot wake the root again.
    assert read_chat_inbox(db_session, chat.id).next_turn is None


@pytest.mark.usefixtures("idle_turn_work")
def test_an_awaited_agent_that_fails_still_ends_the_wait(
    chat: ChatSession,
    owner: User,
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    names = ("alpha", "beta")
    workers = Workers(names, wait_for=names, failing=frozenset({"alpha"}))
    _start(chat, owner, workers, monkeypatch)
    alpha = _finish(db_session, chat, workers, "alpha")
    assert alpha.response_status == RunStatus.ERROR
    assert read_chat_inbox(db_session, chat.id).next_turn is None
    beta = _finish(db_session, chat, workers, "beta")
    _settled(db_session, chat.id, 2)
    [follow_up] = _follow_ups(db_session, chat.id)
    assert _accepted_results(db_session, follow_up) == sorted([alpha.id, beta.id])


@pytest.mark.usefixtures("idle_turn_work")
def test_an_interrupted_awaited_agent_reports_nothing_and_wakes_nobody(
    chat: ChatSession,
    owner: User,
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An interrupted run writes no result, so a wait on it alone never wakes the root."""
    workers = Workers(("alpha",), wait_for=("alpha",))
    _start(chat, owner, workers, monkeypatch)
    alpha = _worker_responses(db_session, chat.id)["alpha"]
    # The same steps as interrupt_agent: withdraw the result, then cancel.
    with get_session_with_current_tenant() as session:
        withdraw_agent_result__no_commit(session, alpha.id)
        session.commit()
    stop_response(get_cache_backend(), get_current_tenant_id(), alpha.id)
    _finish(db_session, chat, workers, "alpha", release=False)
    assert chat_turn_work.wait_idle(timeout=WAIT_TIMEOUT_S)
    db_session.refresh(alpha)
    assert alpha.response_status == RunStatus.CANCELLED
    assert _follow_ups(db_session, chat.id) == []
    assert read_chat_inbox(db_session, chat.id).next_turn is None


@pytest.mark.parametrize("stop", ["stop", "stop_subagents"])
@pytest.mark.usefixtures("idle_turn_work")
def test_stop_during_a_wait_wakes_nobody(
    chat: ChatSession,
    owner: User,
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
    stop: str,
) -> None:
    names = ("alpha", "beta")
    workers = Workers(names, wait_for=names)
    _start(chat, owner, workers, monkeypatch)
    with get_session_with_current_tenant() as session:
        if stop == "stop":
            chat_backend.stop_chat_session(chat.id, None, owner, session)
        else:
            chat_backend.stop_chat_subagents(chat.id, owner, session)
    for name in names:
        _finish(db_session, chat, workers, name, release=stop == "stop")
    assert chat_turn_work.wait_idle(timeout=WAIT_TIMEOUT_S)
    if stop == "stop_subagents":
        assert {
            response.response_status
            for response in _worker_responses(db_session, chat.id).values()
        } == {RunStatus.CANCELLED}
    assert _follow_ups(db_session, chat.id) == []
    assert read_chat_inbox(db_session, chat.id).next_turn is None


@pytest.mark.usefixtures("idle_turn_work")
def test_a_fresh_dispatcher_reads_the_wait_from_the_database(
    chat: ChatSession,
    owner: User,
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The saved wait_agents call is the wait's only record, so a dispatcher in
    another process wakes the root once the awaited runs finish."""
    names = ("alpha", "beta")
    workers = Workers(names, wait_for=names)
    dropped = _drop_dispatches(monkeypatch)
    _start(chat, owner, workers, monkeypatch)
    alpha = dropped.drop_next(lambda: _finish(db_session, chat, workers, "alpha"))
    dispatch_pending_chat_messages(chat.id, owner.id)
    assert read_chat_inbox(db_session, chat.id).next_turn is None
    # The release event never reaches a dispatcher, as when the host pod is gone.
    beta = dropped.drop_next(lambda: _finish(db_session, chat, workers, "beta"))
    assert _follow_ups(db_session, chat.id) == []
    assert read_chat_inbox(db_session, chat.id).next_turn is not None
    dispatch_pending_chat_messages(chat.id, owner.id)
    _settled(db_session, chat.id, 2)
    [follow_up] = _follow_ups(db_session, chat.id)
    assert _accepted_results(db_session, follow_up) == sorted([alpha.id, beta.id])


@pytest.mark.usefixtures("idle_turn_work")
def test_a_user_turn_reads_awaited_results_whose_wake_never_fired(
    chat: ChatSession,
    owner: User,
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A user turn reads the root's unread results at its first step. That ends
    a wait whose wake was lost; a wait on running agents stays open."""
    names = ("alpha", "beta")
    workers = Workers(names, wait_for=names)
    dropped = _drop_dispatches(monkeypatch)
    _start(chat, owner, workers, monkeypatch)
    # A user turn while both agents run answers normally.
    _send(chat, owner, "First question")
    _settled(db_session, chat.id, 2)
    assert _root_answers(db_session, chat.id)[-1].message == "Answer with nothing"
    # The wait is still open after that turn: alpha's result waits for beta.
    alpha = _finish(db_session, chat, workers, "alpha")
    assert read_chat_inbox(db_session, chat.id).next_turn is None
    beta = dropped.drop_next(lambda: _finish(db_session, chat, workers, "beta"))
    # The wait is ready, but its wake was lost.
    assert read_chat_inbox(db_session, chat.id).next_turn is not None
    assert _follow_ups(db_session, chat.id) == []
    _send(chat, owner, "Second question")
    _settled(db_session, chat.id, 3)
    answer = _root_answers(db_session, chat.id)[-1]
    assert answer.parent_message is not None
    assert answer.parent_message.message == "Second question"
    assert answer.message == "Answer with alpha, beta"
    assert _accepted_results(db_session, answer) == sorted([alpha.id, beta.id])
    # The turn read the awaited results, so the wait wakes nobody later.
    assert read_chat_inbox(db_session, chat.id).next_turn is None
    assert chat_turn_work.wait_idle(timeout=WAIT_TIMEOUT_S)
    assert _follow_ups(db_session, chat.id) == []
