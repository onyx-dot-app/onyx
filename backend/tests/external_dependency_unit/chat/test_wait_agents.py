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
from onyx.chat.process_message import handle_stream_message_objects
from onyx.chat.run_store import RESPONSE_OWNER_KEY_PREFIX
from onyx.configs.constants import DEFAULT_PERSONA_ID, MessageType
from onyx.db.chat_inputs import read_chat_inbox
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
from tests.external_dependency_unit.conftest import MakeTestUser
from tests.unit.onyx.agents.fakes import FakeModelClient

WAIT_TIMEOUT_S = 30
WAITING = "Waiting for the workers."
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
    """A root that starts named workers, then waits for some of them.

    Each worker runs until the test releases it. A follow-up or a later turn
    answers with the names of the results that it can see.
    """

    def __init__(
        self,
        names: tuple[str, ...],
        *,
        wait_for: tuple[str, ...] | None = None,
        failing: frozenset[str] = frozenset(),
        spawn_and_wait: bool = False,
        before_wait: Callable[[], object] | None = None,
    ) -> None:
        self.names = names
        # None waits for all workers.
        self.wait_for = wait_for
        self.failing = failing
        self.spawn_and_wait = spawn_and_wait
        self.before_wait = before_wait
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
        spawns = [
            ToolCall(
                id=f"spawn-{name}",
                name=SPAWN_AGENT_TOOL_NAME,
                arguments={"name": name, "instruction": f"Task {name}"},
            )
            for name in self.names
        ]
        if len(self.root_requests) == 1:
            if self.spawn_and_wait:
                return AssistantMessage(content=[*spawns, self._wait_call(request)])
            return AssistantMessage(content=spawns)
        if not self.first_turn_done:
            self.first_turn_done = True
            if self.spawn_and_wait:
                return _text(WAITING)
            if self.before_wait is not None:
                self.before_wait()
            return AssistantMessage(
                content=[TextContent(text=WAITING), self._wait_call(request)]
            )
        seen = [name for name in self.names if f"Result {name}" in str(texts)]
        return _text(f"Answer with {', '.join(seen) or 'nothing'}")

    def _wait_call(self, request: GenerationRequest) -> ToolCall:
        if self.wait_for is None:
            return ToolCall(id="wait", name=WAIT_AGENTS_TOOL_NAME, arguments={})
        agent_ids = {
            match[1]: match[2]
            for message in request.messages
            if isinstance(message, ToolResultMessage)
            and (
                match := re.search(r"/root/(\w+) \(agent_id: ([\w-]+)\)", message.text)
            )
        }
        return ToolCall(
            id="wait",
            name=WAIT_AGENTS_TOOL_NAME,
            arguments={"agent_ids": [agent_ids[name] for name in self.wait_for]},
        )


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
) -> ChatMessage:
    """Release a worker and wait until its run releases, which dispatches."""
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
    workers = Workers(names, failing=frozenset({"beta"}))
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
    # Each release dispatched; the wait holds both results, the failure too.
    assert finished[1].response_status == RunStatus.ERROR
    assert read_chat_inbox(db_session, chat.id).next_turn is None
    assert _follow_ups(db_session, chat.id) == []
    finished.append(_finish(db_session, chat, workers, names[2]))
    _settled(db_session, chat.id, 2)
    [follow_up] = _follow_ups(db_session, chat.id)
    assert _accepted_results(db_session, follow_up) == sorted(
        response.id for response in finished
    )
    # The follow-up read the results, so the wait cannot wake the root again.
    assert read_chat_inbox(db_session, chat.id).next_turn is None


@pytest.mark.usefixtures("idle_turn_work")
def test_a_result_that_finishes_before_the_wait_call_waits_with_the_rest(
    chat: ChatSession,
    owner: User,
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Alpha finishes while the model writes the wait call, so its result is
    unread and finished when the wait starts."""
    names = ("alpha", "beta")
    workers = Workers(
        names,
        before_wait=lambda: _finish(db_session, chat, workers, "alpha"),
    )
    _start(chat, owner, workers, monkeypatch)
    assert read_chat_inbox(db_session, chat.id).next_turn is None
    assert _follow_ups(db_session, chat.id) == []
    _finish(db_session, chat, workers, "beta")
    _settled(db_session, chat.id, 2)
    [follow_up] = _follow_ups(db_session, chat.id)
    assert follow_up.message == "Answer with alpha, beta"


@pytest.mark.usefixtures("idle_turn_work")
def test_a_wait_in_the_spawning_step_waits_for_those_agents(
    chat: ChatSession,
    owner: User,
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    names = ("alpha", "beta")
    workers = Workers(names, spawn_and_wait=True)
    _start(chat, owner, workers, monkeypatch)
    _settled(db_session, chat.id, 1)
    _finish(db_session, chat, workers, "alpha")
    assert read_chat_inbox(db_session, chat.id).next_turn is None
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
    assert read_chat_inbox(db_session, chat.id).next_turn is None


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
    workers = Workers(names)
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
