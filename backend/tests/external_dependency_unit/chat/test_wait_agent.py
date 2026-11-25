"""The root waits for its agents, with `wait_agent` or, in the Claude tool shape,
by itself, and answers their results once.

Each test runs real chat turns against Postgres with a scripted model. Child
runs release through the run store, whose release event dispatches the root's
follow-up.
"""

import time
from collections.abc import Callable, Generator
from threading import Event
from typing import override
from uuid import UUID, uuid4

import pytest
from fastapi import BackgroundTasks, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from onyx.agents.models import InputSource, MessageDelivery, RunStatus
from onyx.cache.factory import get_cache_backend
from onyx.chat import execution, run_store
from onyx.chat.chat_processing_checker import ChatTurnAdmission
from onyx.chat.execution import chat_turn_work
from onyx.chat.models import AgentWait
from onyx.chat.process_message import handle_stream_message_objects
from onyx.chat.run_store import RESPONSE_OWNER_KEY_PREFIX, stop_response
from onyx.configs.constants import DEFAULT_PERSONA_ID, MessageType
from onyx.db.chat import get_selected_branch
from onyx.db.chat_inputs import (
    agent_waits,
    read_chat_inbox,
    withdraw_agent_result__no_commit,
)
from onyx.db.chat_subagents import load_session_agent_metadata
from onyx.db.engine.sql_engine import get_session_with_current_tenant
from onyx.db.models import (
    ChatInput,
    ChatMessage,
    ChatResponseItem,
    ChatSession,
    User,
)
from onyx.db.models import ToolCall as ToolCallRow
from onyx.llm.cancellation import CancellationSignal
from onyx.llm.interfaces import LLMConfig
from onyx.llm.model_capabilities import ToolFamily
from onyx.llm.models import (
    AssistantMessage,
    GenerationRequest,
    TextContent,
    ToolCall,
)
from onyx.server.query_and_chat import chat_backend
from onyx.server.query_and_chat.models import SendMessageRequest
from onyx.tools.constants import (
    AGENT_TOOL_NAME,
    SPAWN_AGENT_TOOL_NAME,
    WAIT_AGENT_TOOL_NAME,
)
from shared_configs.contextvars import get_current_tenant_id
from tests.external_dependency_unit.conftest import MakeTestUser
from tests.unit.onyx.agents.fakes import TEST_MODEL_NAMES, FakeModelClient

WAIT_TIMEOUT_S = 30
WAITING = "Waiting for the workers."
QUESTION = "Ask the workers"
LATER_QUESTION = "Ask more workers"
# A status request without pass-through headers.
_NO_HEADERS = Request({"type": "http", "headers": []})


class ScriptedLLM(FakeModelClient):
    @property
    @override
    def config(self) -> LLMConfig:
        return LLMConfig(
            model_provider="openai",
            model_name="gpt-4o-mini"
            if self.family is ToolFamily.OPENAI
            else TEST_MODEL_NAMES[self.family],
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
        wait: bool = True,
        family: ToolFamily = ToolFamily.OPENAI,
        later: tuple[str, ...] = (),
    ) -> None:
        # `later` are workers that a later turn, LATER_QUESTION, starts.
        self.names = names + later
        self.later = later
        self.later_requests = 0
        # The root's tool family; the Claude shape has no wait tool, so its
        # root ends its first turn with text.
        self.family = family
        # None waits for all workers.
        self.wait_for = wait_for
        self.failing = failing
        self.spawn_and_wait = spawn_and_wait
        self.before_wait = before_wait
        # False answers the first turn with text and no wait call.
        self.wait = wait
        self.started = {name: Event() for name in self.names}
        self.release = {name: Event() for name in self.names}
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
        if LATER_QUESTION in texts:
            self.later_requests += 1
            if self.later_requests == 1:
                return AssistantMessage(content=self._spawns(self.later))
            return _text(WAITING)
        spawns = self._spawns(tuple(n for n in self.names if n not in self.later))
        if len(self.root_requests) == 1:
            if self.spawn_and_wait:
                return AssistantMessage(content=[*spawns, self._wait_call()])
            return AssistantMessage(content=spawns)
        if not self.first_turn_done:
            self.first_turn_done = True
            if self.spawn_and_wait:
                return _text(WAITING)
            if self.before_wait is not None:
                self.before_wait()
            if not self.wait or self.family is ToolFamily.CLAUDE:
                return _text(WAITING)
            return AssistantMessage(
                content=[TextContent(text=WAITING), self._wait_call()]
            )
        seen = [name for name in self.names if f"Result {name}" in str(texts)]
        return _text(f"Answer with {', '.join(seen) or 'nothing'}")

    def _spawns(self, names: tuple[str, ...]) -> list[ToolCall]:
        return [
            ToolCall(
                id=f"spawn-{name}",
                name=SPAWN_AGENT_TOOL_NAME,
                arguments={"task_name": name, "message": f"Task {name}"},
            )
            if self.family is ToolFamily.OPENAI
            else ToolCall(
                id=f"spawn-{name}",
                name=AGENT_TOOL_NAME,
                arguments={"description": name, "prompt": f"Task {name}"},
            )
            for name in names
        ]

    def _wait_call(self) -> ToolCall:
        if self.wait_for is None:
            return ToolCall(id="wait", name=WAIT_AGENT_TOOL_NAME, arguments={})
        return ToolCall(
            id="wait",
            name=WAIT_AGENT_TOOL_NAME,
            arguments={"targets": [f"/root/{name}" for name in self.wait_for]},
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
    monkeypatch.setattr("onyx.chat.execution.construct_tools", lambda **_kwargs: [])
    model = ScriptedLLM(workers.generate, family=workers.family)
    monkeypatch.setattr(
        "onyx.chat.process_message.get_llm_for_persona", lambda **_kwargs: model
    )
    _send(chat, owner, QUESTION)
    for name in workers.names:
        if name not in workers.later:
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


def _message_agent(
    db_session: Session,
    chat: ChatSession,
    worker: ChatMessage,
    delivery: MessageDelivery,
) -> ChatInput:
    """Store a root message for a worker's run, as `send_message` does."""
    spawn = db_session.scalar(
        select(ToolCallRow).where(
            ToolCallRow.chat_session_id == chat.id,
            ToolCallRow.tool_call_id.like("spawn-%"),
        )
    )
    assert spawn is not None and spawn.parent_chat_message_id is not None
    row = ChatInput(
        recipient_session_id=worker.chat_session_id,
        message_id=str(uuid4()),
        source=InputSource.AGENT,
        invoking_tool_call_id=spawn.id,
        source_response_id=spawn.parent_chat_message_id,
        target_response_id=worker.id,
        root_response_id=spawn.parent_chat_message_id,
        delivery=delivery,
        content="More work",
        max_steps=3,
    )
    db_session.add(row)
    db_session.commit()
    return row


def _interrupt(db_session: Session, chat: ChatSession, name: str) -> ChatMessage:
    """The same steps as interrupt_agent: withdraw the result, then cancel."""
    worker = _worker_responses(db_session, chat.id)[name]
    with get_session_with_current_tenant() as session:
        withdraw_agent_result__no_commit(session, worker.id)
        session.commit()
    stop_response(get_cache_backend(), get_current_tenant_id(), worker.id)
    cache = get_cache_backend()

    def released() -> bool:
        db_session.refresh(worker)
        return worker.response_status == RunStatus.CANCELLED and not cache.exists(
            f"{RESPONSE_OWNER_KEY_PREFIX}{worker.id}"
        )

    _wait_until(released, f"{name} is interrupted")
    return worker


class _DroppedDispatches:
    """Lose the release events of chosen runs, as when their host pod is gone."""

    def __init__(self) -> None:
        self.dropping = Event()
        self.dropped = 0
        # A run's release callback runs after its owner key is gone.
        self.callbacks = 0

    def keep_next[T](self, finish: Callable[[], T]) -> T:
        """Finish a run and wait until its release callback has run."""
        before = self.callbacks
        result = finish()
        _wait_until(lambda: self.callbacks > before, "the release is dispatched")
        return result

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

    def dispatch_unless_dropped(
        self: execution.ChatTurnExecution,
        admission: ChatTurnAdmission | None = None,
    ) -> None:
        try:
            if dropped.dropping.is_set():
                dropped.dropped += 1
                return
            dispatch(self, admission)
        finally:
            dropped.callbacks += 1

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
def test_a_wait_with_more_results_than_one_step_reads_answers_once(
    chat: ChatSession,
    owner: User,
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A step reads at most two results here, so the follow-up reads the third
    in a later step before it answers."""
    monkeypatch.setattr(run_store, "MAX_AGENT_COMPLETIONS_PER_STEP", 2)
    names = ("alpha", "beta", "gamma")
    workers = Workers(names)
    _start(chat, owner, workers, monkeypatch)
    for name in names:
        _finish(db_session, chat, workers, name)
    _settled(db_session, chat.id, 2)
    [follow_up] = _follow_ups(db_session, chat.id)
    assert follow_up.message == "Answer with alpha, beta, gamma"
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
def test_a_result_during_a_user_turn_answer_starts_a_separate_follow_up(
    chat: ChatSession,
    owner: User,
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Alpha finishes while the root writes its answer with no wait. The answer
    stays as the user saw it, and the result starts its own follow-up."""
    workers = Workers(
        ("alpha",),
        wait=False,
        before_wait=lambda: _finish(db_session, chat, workers, "alpha"),
    )
    _start(chat, owner, workers, monkeypatch)
    _settled(db_session, chat.id, 2)
    answer, follow_up = _root_answers(db_session, chat.id)
    assert answer.message == WAITING
    assert follow_up.parent_message is not None
    assert follow_up.parent_message.message_type == MessageType.AGENT_RESULTS
    assert follow_up.message == "Answer with alpha"


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
def test_an_unawaited_follow_up_leaves_awaited_results_for_the_wait(
    chat: ChatSession,
    owner: User,
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Alpha finishes, then unawaited beta wakes the root while gamma runs.
    That follow-up reads only beta, and the wait outlives it: alpha waits for
    gamma's follow-up."""
    workers = Workers(("alpha", "beta", "gamma"), wait_for=("alpha", "gamma"))
    _start(chat, owner, workers, monkeypatch)
    alpha = _finish(db_session, chat, workers, "alpha")
    assert read_chat_inbox(db_session, chat.id).next_turn is None
    beta = _finish(db_session, chat, workers, "beta")
    _settled(db_session, chat.id, 2)
    [interim] = _follow_ups(db_session, chat.id)
    assert interim.message == "Answer with beta"
    assert _accepted_results(db_session, interim) == [beta.id]
    assert read_chat_inbox(db_session, chat.id).next_turn is None
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
    alpha = dropped.keep_next(lambda: _finish(db_session, chat, workers, "alpha"))
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


@pytest.mark.usefixtures("idle_turn_work")
def test_a_message_that_can_no_longer_start_does_not_hold_the_wait(
    chat: ChatSession,
    owner: User,
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A send to a run that then fails never starts a run, so it holds nothing."""
    workers = Workers(("alpha",), failing=frozenset({"alpha"}))
    _start(chat, owner, workers, monkeypatch)
    alpha = _worker_responses(db_session, chat.id)["alpha"]
    _message_agent(db_session, chat, alpha, MessageDelivery.SEND)
    alpha = _finish(db_session, chat, workers, "alpha")
    assert alpha.response_status == RunStatus.ERROR
    _settled(db_session, chat.id, 2)
    [follow_up] = _follow_ups(db_session, chat.id)
    assert _accepted_results(db_session, follow_up) == [alpha.id]


@pytest.mark.usefixtures("idle_turn_work")
def test_a_message_queued_behind_an_interrupt_does_not_hold_the_wait(
    chat: ChatSession,
    owner: User,
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An interrupt pauses the agent's queue, so its queued message waits for an
    explicit send and holds nothing; the interrupted run reports nothing."""
    workers = Workers(("alpha", "beta"))
    _start(chat, owner, workers, monkeypatch)
    alpha = _worker_responses(db_session, chat.id)["alpha"]
    _message_agent(db_session, chat, alpha, MessageDelivery.QUEUE)
    _interrupt(db_session, chat, "alpha")
    beta = _finish(db_session, chat, workers, "beta")
    _settled(db_session, chat.id, 2)
    [follow_up] = _follow_ups(db_session, chat.id)
    assert _accepted_results(db_session, follow_up) == [beta.id]


@pytest.mark.usefixtures("idle_turn_work")
def test_a_message_that_will_start_a_run_holds_the_wait(
    chat: ChatSession,
    owner: User,
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workers = Workers(("alpha",))
    dropped = _drop_dispatches(monkeypatch)
    _start(chat, owner, workers, monkeypatch)
    alpha = dropped.drop_next(lambda: _finish(db_session, chat, workers, "alpha"))
    # Nothing scans once every run has released.
    assert chat_turn_work.wait_idle(timeout=WAIT_TIMEOUT_S)
    assert read_chat_inbox(db_session, chat.id).next_turn is not None
    queued = _message_agent(db_session, chat, alpha, MessageDelivery.QUEUE)
    _, branch = get_selected_branch(db_session, chat.id)
    [wait] = agent_waits(db_session, chat.id, branch)
    assert wait.queued
    assert read_chat_inbox(db_session, chat.id).next_turn is None
    db_session.delete(queued)
    db_session.commit()
    assert read_chat_inbox(db_session, chat.id).next_turn is not None


def test_agents_of_the_current_user_turn(
    chat: ChatSession,
    owner: User,
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workers = Workers(("alpha", "beta"))
    _start(chat, owner, workers, monkeypatch)
    [waiting] = _root_answers(db_session, chat.id)

    def current() -> dict[str, bool]:
        latest = _root_answers(db_session, chat.id)[-1]
        return {
            agent.path: agent.current_turn
            for agent in load_session_agent_metadata(latest.id)
        }

    assert current() == {"/root": True, "/root/alpha": True, "/root/beta": True}
    for name in workers.names:
        _finish(db_session, chat, workers, name)
    _settled(db_session, chat.id, 2)
    # The follow-up still belongs to the user turn that started the agents.
    assert current() == {"/root": True, "/root/alpha": True, "/root/beta": True}
    assert chat_turn_work.wait_idle(timeout=WAIT_TIMEOUT_S)
    _send(chat, owner, "Next question")
    _settled(db_session, chat.id, 3)
    assert current() == {"/root": True, "/root/alpha": False, "/root/beta": False}
    assert waiting.id < _root_answers(db_session, chat.id)[-1].id
    assert chat_turn_work.wait_idle(timeout=WAIT_TIMEOUT_S)


# A Claude root has no wait tool: a response that ends while the agents that
# it started run waits for them by itself (no AgentShape.wait_name).


@pytest.mark.usefixtures("idle_turn_work")
def test_a_claude_root_answers_its_staggered_agents_once(
    chat: ChatSession,
    owner: User,
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Three agents finish at different times, one with an error; the root
    answers all their results in one follow-up."""
    names = ("alpha", "beta", "gamma")
    workers = Workers(names, failing=frozenset({"beta"}), family=ToolFamily.CLAUDE)
    _start(chat, owner, workers, monkeypatch)
    [answer] = _root_answers(db_session, chat.id)
    assert answer.message == WAITING
    finished = [_finish(db_session, chat, workers, name) for name in names[:2]]
    assert finished[1].response_status == RunStatus.ERROR
    assert read_chat_inbox(db_session, chat.id).next_turn is None
    assert _follow_ups(db_session, chat.id) == []
    finished.append(_finish(db_session, chat, workers, names[2]))
    _settled(db_session, chat.id, 2)
    [follow_up] = _follow_ups(db_session, chat.id)
    assert _accepted_results(db_session, follow_up) == sorted(
        response.id for response in finished
    )
    assert read_chat_inbox(db_session, chat.id).next_turn is None


@pytest.mark.usefixtures("idle_turn_work")
def test_the_default_root_answers_each_agent_that_it_did_not_wait_for(
    chat: ChatSession,
    owner: User,
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Without a wait call, a root of the default shape answers each result
    on its own."""
    names = ("alpha", "beta")
    workers = Workers(names, wait=False)
    _start(chat, owner, workers, monkeypatch)
    _finish(db_session, chat, workers, "alpha")
    _settled(db_session, chat.id, 2)
    _finish(db_session, chat, workers, "beta")
    _settled(db_session, chat.id, 3)
    assert [answer.message for answer in _follow_ups(db_session, chat.id)] == [
        "Answer with alpha",
        "Answer with alpha, beta",
    ]


@pytest.mark.usefixtures("idle_turn_work")
def test_a_claude_agent_that_finishes_before_the_response_ends_waits_with_the_rest(
    chat: ChatSession,
    owner: User,
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workers = Workers(
        ("alpha", "beta"),
        family=ToolFamily.CLAUDE,
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
def test_a_user_turn_reads_the_results_that_a_claude_root_holds(
    chat: ChatSession,
    owner: User,
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A user turn reads the held results at its first step; the wait on the
    agent that still runs holds its result for one follow-up."""
    workers = Workers(("alpha", "beta"), family=ToolFamily.CLAUDE)
    _start(chat, owner, workers, monkeypatch)
    _finish(db_session, chat, workers, "alpha")
    assert read_chat_inbox(db_session, chat.id).next_turn is None
    _send(chat, owner, "A question")
    _settled(db_session, chat.id, 2)
    assert _root_answers(db_session, chat.id)[-1].message == "Answer with alpha"
    _finish(db_session, chat, workers, "beta")
    _settled(db_session, chat.id, 3)
    [follow_up] = _follow_ups(db_session, chat.id)
    assert follow_up.message == "Answer with alpha, beta"


@pytest.mark.usefixtures("idle_turn_work")
def test_an_interrupted_claude_agent_releases_the_wait(
    chat: ChatSession,
    owner: User,
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An interrupted run leaves no result, so the wait holds only the other
    agent, and its result alone starts the follow-up."""
    workers = Workers(("alpha", "beta"), family=ToolFamily.CLAUDE)
    _start(chat, owner, workers, monkeypatch)
    beta = _finish(db_session, chat, workers, "beta")
    assert read_chat_inbox(db_session, chat.id).next_turn is None
    _interrupt(db_session, chat, "alpha")
    _settled(db_session, chat.id, 2)
    [follow_up] = _follow_ups(db_session, chat.id)
    assert _accepted_results(db_session, follow_up) == [beta.id]


@pytest.mark.usefixtures("idle_turn_work")
def test_a_running_claude_response_holds_none_of_its_agents_results(
    chat: ChatSession,
    owner: User,
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A response reads its agents' results as they finish while it runs; its
    wait on them starts when it ends."""
    held_while_running: list[list[AgentWait]] = []

    def finish_alpha_while_running() -> None:
        _finish(db_session, chat, workers, "alpha")
        db_session.expire_all()
        held_while_running.append(
            agent_waits(
                db_session, chat.id, get_selected_branch(db_session, chat.id)[1]
            )
        )

    workers = Workers(
        ("alpha", "beta"),
        family=ToolFamily.CLAUDE,
        before_wait=finish_alpha_while_running,
    )
    _start(chat, owner, workers, monkeypatch)
    assert held_while_running == [[]]
    [answer] = _root_answers(db_session, chat.id)
    [wait] = agent_waits(
        db_session, chat.id, get_selected_branch(db_session, chat.id)[1]
    )
    assert wait.response_id == answer.id
    assert wait.agent_ids == frozenset(
        response.chat_session_id
        for response in _worker_responses(db_session, chat.id).values()
    )
    # Alpha finished during the response's last model call, so the wait
    # holds its result with beta's.
    _finish(db_session, chat, workers, "beta")
    _settled(db_session, chat.id, 2)
    [follow_up] = _follow_ups(db_session, chat.id)
    assert follow_up.message == "Answer with alpha, beta"


@pytest.mark.usefixtures("idle_turn_work")
def test_each_claude_response_waits_for_its_own_agents(
    chat: ChatSession,
    owner: User,
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A later response starts more agents while the first response's agents
    still run: each response's wait holds only its own agents, so each
    gives one follow-up with its own results."""
    workers = Workers(
        ("alpha", "beta"), family=ToolFamily.CLAUDE, later=("gamma", "delta")
    )
    _start(chat, owner, workers, monkeypatch)
    alpha = _finish(db_session, chat, workers, "alpha")
    _send(chat, owner, LATER_QUESTION)
    for name in ("gamma", "delta"):
        assert workers.started[name].wait(WAIT_TIMEOUT_S)
    _settled(db_session, chat.id, 2)
    # The user turn read alpha's result; beta still holds the first wait.
    gamma = _finish(db_session, chat, workers, "gamma")
    beta = _finish(db_session, chat, workers, "beta")
    _settled(db_session, chat.id, 3)
    [first] = _follow_ups(db_session, chat.id)
    assert _accepted_results(db_session, first) == [beta.id]
    assert read_chat_inbox(db_session, chat.id).next_turn is None
    delta = _finish(db_session, chat, workers, "delta")
    _settled(db_session, chat.id, 4)
    second = _follow_ups(db_session, chat.id)[1]
    assert _accepted_results(db_session, second) == sorted([gamma.id, delta.id])
    assert alpha.id not in _accepted_results(db_session, second)
