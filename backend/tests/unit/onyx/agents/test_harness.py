"""Exercise the runtime without Onyx rendering, storage, or a provider."""

import threading
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from types import TracebackType

import pytest
from pydantic import JsonValue, ValidationError

from onyx.agents.events import AgentEvent, AgentEventType
from onyx.agents.runtime import Agent, AgentContext, AgentHooks
from onyx.agents.tools import AgentTool, ToolExecutionMode, ToolUpdate
from onyx.llm.cancellation import (
    AgentCancelled,
    CancellationSignal,
    current_cancellation,
)
from onyx.llm.models import (
    AssistantMessage,
    GenerationRequest,
    TextContent,
    ToolCall,
    ToolResult,
    ToolResultMessage,
    UserMessage,
)
from tests.unit.onyx.agents.fakes import FakeModelClient


def scripted(*messages: AssistantMessage) -> FakeModelClient:
    replies = iter(messages)
    return FakeModelClient(lambda _context, _signal: next(replies))


def answer(text: str = "done") -> AssistantMessage:
    return AssistantMessage(content=[TextContent(text=text)])


def calls(count: int = 1, *, name: str = "echo") -> AssistantMessage:
    return AssistantMessage(
        content=[
            ToolCall(id=str(index), name=name, arguments={"value": index})
            for index in range(count)
        ]
    )


def echo(
    execute: Callable[
        [str, dict[str, JsonValue], CancellationSignal, ToolUpdate], ToolResult
    ]
    | None = None,
    *,
    sequential: bool = False,
) -> AgentTool:
    return AgentTool(
        name="echo",
        description="Echo",
        parameters={"type": "object"},
        execute=execute
        or (lambda _id, args, _signal, _update: ToolResult(content=str(args["value"]))),
        execution_mode=ToolExecutionMode.SEQUENTIAL
        if sequential
        else ToolExecutionMode.PARALLEL,
    )


def test_cancelled_turn_retains_completed_tools_for_resume() -> None:
    signal = CancellationSignal()
    agent = Agent(
        scripted(calls(2), answer()),
        context=AgentContext(tools=[echo(sequential=True)]),
    )
    completed: list[str] = []

    def cancel_after_first_result(event: AgentEvent) -> None:
        assert current_cancellation() is signal
        if event.type == "tool_end" and event.tool_call:
            completed.append(event.tool_call.id)
            signal.cancel()

    unsubscribe = agent.subscribe(cancel_after_first_result)
    with pytest.raises(AgentCancelled):
        agent.run(max_turns=2, cancellation=signal)
    unsubscribe()

    results = [
        message
        for message in agent.context.messages
        if isinstance(message, ToolResultMessage)
    ]
    assert completed == ["0"]
    assert [(result.tool_call_id, result.is_error) for result in results] == [
        ("0", False),
        ("1", True),
    ]
    assert results[0].content == "0"
    resumed = agent.run(max_turns=1)
    assert resumed.output.text == "done"
    assert resumed.messages[1:3] == results


@pytest.mark.parametrize("sequential", [False, True])
def test_all_calls_execute_in_order_with_bounded_concurrency(sequential: bool) -> None:
    context = AgentContext(tools=[echo(sequential=sequential)])
    agent = Agent(scripted(calls(9), answer()), context=context, max_parallel_tools=2)
    events: list[AgentEvent] = []
    agent.subscribe(events.append)
    result = agent.run(messages=[UserMessage(content="run")], max_turns=2)
    assert result.turns == 2
    assert result.stop_reason == "complete"
    results = [
        message for message in result.messages if isinstance(message, ToolResultMessage)
    ]
    assert [message.content for message in results] == [str(i) for i in range(9)]
    assert [event.type for event in events].count(AgentEventType.TOOL_END) == 9
    assert events[0].type == "agent_start"
    last_event = events[-1]
    assert last_event.type == "agent_end"
    assert last_event.outcome == "complete"
    assert context.messages == []
    assert current_cancellation() is None


@pytest.mark.parametrize(
    "event_type",
    [
        "turn_start",
        "message_start",
        "message_end",
        "tool_start",
        "tool_end",
        "turn_end",
    ],
)
def test_cancellation_stops_before_next_operation(event_type: str) -> None:
    signal = CancellationSignal()
    executed: list[str] = []

    def execute(
        call_id: str,
        _args: dict[str, JsonValue],
        _signal: CancellationSignal,
        _update: ToolUpdate,
    ) -> ToolResult:
        executed.append(call_id)
        return ToolResult(content="ok")

    agent = Agent(
        scripted(calls(), answer()), context=AgentContext(tools=[echo(execute)])
    )
    events: list[AgentEvent] = []

    def observe(event: AgentEvent) -> None:
        events.append(event)
        if event.type == event_type:
            signal.cancel()

    agent.subscribe(observe)
    with pytest.raises(AgentCancelled):
        agent.run(max_turns=3, cancellation=signal)
    last_event = events[-1]
    assert last_event.type == "agent_end"
    assert last_event.outcome == "cancelled"
    assert agent.wait_for_idle(0)
    if event_type in {"turn_start", "message_start", "message_end", "tool_start"}:
        assert executed == []


@pytest.mark.parametrize("invalid", ["unknown", "arguments", "truncated", "disabled"])
def test_invalid_calls_get_paired_errors(invalid: str) -> None:
    message = calls(name="missing") if invalid == "unknown" else calls()
    if invalid == "arguments":
        message.tool_calls[0].argument_error = "Bad arguments"
    if invalid == "truncated":
        message.stop_reason = "length"
    context = AgentContext(tools=[echo()])
    if invalid == "disabled":
        from onyx.llm.models import ToolChoiceOptions

        context.options.tool_choice = ToolChoiceOptions.NONE
    result = Agent(scripted(message, answer()), context=context).run(max_turns=2)
    tool_result = result.messages[1]
    assert isinstance(tool_result, ToolResultMessage)
    assert tool_result.is_error and tool_result.tool_call_id == "0"


def test_context_transform_does_not_rewrite_durable_history() -> None:
    agent = Agent(
        scripted(answer()),
        context=AgentContext(messages=[UserMessage(content="original")]),
        hooks=AgentHooks(
            transform_context=lambda context, _turn: context.model_copy(
                update={"messages": []}
            )
        ),
    )
    result = agent.run(max_turns=1)
    assert isinstance(result.messages[0], UserMessage)
    assert result.messages[0].content == "original"


def test_steering_and_follow_up_have_distinct_boundaries() -> None:
    agent = Agent(
        scripted(calls(), answer("first"), answer("second")),
        context=AgentContext(tools=[echo()]),
    )

    def enqueue(event: AgentEvent) -> None:
        if event.type == "agent_start":
            agent.follow_up(UserMessage(content="later"))
            agent.steer(UserMessage(content="now"), expected_execution_id=event.run_id)

    agent.subscribe(enqueue)
    result = agent.run(max_turns=4)
    assert result.turns == 3
    assert [
        message.content
        for message in result.messages
        if isinstance(message, UserMessage)
    ] == ["now", "later"]
    assert isinstance(result.messages[-2], UserMessage)


def test_tool_hooks_can_block_transform_and_report_progress() -> None:
    def execute(
        _id: str,
        _args: dict[str, JsonValue],
        _signal: CancellationSignal,
        update: ToolUpdate,
    ) -> ToolResult:
        update(ToolResult(content="working"))
        return ToolResult(content="raw")

    agent = Agent(
        scripted(calls(2), answer()),
        context=AgentContext(tools=[echo(execute)]),
        hooks=AgentHooks(
            before_tool_call=lambda context: (
                ToolResult(content="blocked", is_error=True)
                if context.call.id == "1"
                else None
            ),
            after_tool_call=lambda _context, result: result.model_copy(
                update={"content": str(result.content) + "!"}
            ),
        ),
    )
    events: list[AgentEvent] = []
    agent.subscribe(events.append)
    result = agent.run(max_turns=2)
    assert [
        item.content for item in result.messages if isinstance(item, ToolResultMessage)
    ] == ["raw!", "blocked!"]
    assert len([event for event in events if event.type == "tool_update"]) == 1


def test_abort_reaches_nested_agent_and_waits_for_idle() -> None:
    started = threading.Event()
    done = threading.Event()
    signals: list[CancellationSignal] = []

    def child_model(
        _context: GenerationRequest, signal: CancellationSignal
    ) -> AssistantMessage:
        signals.append(signal)
        with signal.on_cancel(done.set):
            started.set()
            assert done.wait(3)
            signal.check()
        raise AssertionError("child must cancel")

    def execute(
        _id: str,
        _args: dict[str, JsonValue],
        signal: CancellationSignal,
        _update: ToolUpdate,
    ) -> ToolResult:
        signals.append(signal)
        Agent(FakeModelClient(child_model)).run(max_turns=1)
        raise AssertionError("parent must cancel")

    agent = Agent(scripted(calls()), context=AgentContext(tools=[echo(execute)]))
    errors: list[BaseException] = []

    def run() -> None:
        try:
            agent.run(max_turns=2)
        except BaseException as error:
            errors.append(error)

    thread = threading.Thread(target=run)
    thread.start()
    try:
        assert started.wait(3)
        assert not agent.wait_for_idle(0)
        with pytest.raises(RuntimeError, match="already running"):
            agent.run(max_turns=1)
        agent.abort()
        assert agent.wait_for_idle(3)
    finally:
        agent.abort()
        thread.join(3)
    assert len(errors) == 1 and isinstance(errors[0], AgentCancelled)
    assert signals[0] is signals[1]


def test_limits_and_exception_lifecycle() -> None:
    agent = Agent(scripted(calls()), context=AgentContext(tools=[echo()]))
    assert agent.run(max_turns=1).stop_reason == "limit"
    with pytest.raises(ValidationError):
        agent.run(max_turns=0)
    events: list[AgentEvent] = []

    def fail(
        _context: GenerationRequest, _signal: CancellationSignal
    ) -> AssistantMessage:
        raise ValueError("provider failure")

    agent = Agent(FakeModelClient(fail))
    agent.subscribe(events.append)
    with pytest.raises(ValueError, match="provider failure"):
        agent.run(max_turns=1)
    last_event = events[-1]
    assert last_event.type == "agent_end"
    assert last_event.outcome == "error"
    assert agent.wait_for_idle(0)


def test_network_cancellation_waits_for_cleanup() -> None:
    import asyncio

    from onyx.llm.cancellation import _network_loop

    entered = threading.Event()
    cleanup_started = threading.Event()
    allow_cleanup = threading.Event()
    returned = threading.Event()
    signal = CancellationSignal()

    async def operation() -> None:
        try:
            entered.set()
            await asyncio.Event().wait()
        finally:
            cleanup_started.set()
            while not allow_cleanup.is_set():
                await asyncio.sleep(0.01)

    def run() -> None:
        try:
            _network_loop().call(operation(), signal, timeout=5)
        except AgentCancelled:
            returned.set()

    worker = threading.Thread(target=run)
    worker.start()
    try:
        assert entered.wait(3)
        signal.cancel()
        assert cleanup_started.wait(3)
        assert not returned.is_set()
        allow_cleanup.set()
        assert returned.wait(3)
    finally:
        signal.cancel()
        allow_cleanup.set()
        worker.join(3)


def test_incomplete_model_stream_cannot_complete_an_agent_turn() -> None:
    from collections.abc import Generator

    from onyx.llm.interfaces import GenerationContext
    from onyx.llm.models import GenerationEvent, TextDeltaEvent

    closed: list[bool] = []

    class IncompleteClient(FakeModelClient):
        def stream(
            self, request: GenerationRequest, context: GenerationContext | None = None
        ) -> Generator[GenerationEvent, None, None]:
            del request, context
            try:
                yield TextDeltaEvent(
                    message=answer("partial"), content_index=0, text="partial"
                )
            finally:
                closed.append(True)

    agent = Agent(IncompleteClient(lambda *_: answer()))
    with pytest.raises(RuntimeError, match="without a completed message"):
        agent.run(max_turns=1)
    assert closed == [True]
    snapshot = agent.snapshot()
    assert snapshot is not None and snapshot.status == "error"
    assert snapshot.messages[-1].text == "partial"


def test_cancellation_closes_active_client_stream() -> None:
    from collections.abc import Generator

    from onyx.llm.interfaces import GenerationContext
    from onyx.llm.models import GenerationDoneEvent, GenerationEvent, TextDeltaEvent

    closed: list[bool] = []
    signal = CancellationSignal()

    class StreamingClient(FakeModelClient):
        def stream(
            self, request: GenerationRequest, context: GenerationContext | None = None
        ) -> Generator[GenerationEvent, None, None]:
            del request
            assert context is not None and context.cancellation is signal
            try:
                yield TextDeltaEvent(
                    message=answer("partial"), content_index=0, text="partial"
                )
                yield GenerationDoneEvent(message=answer("complete"))
            finally:
                closed.append(True)

    agent = Agent(StreamingClient(lambda *_: answer()))
    agent.subscribe(
        lambda event: signal.cancel() if event.type == "message_update" else None
    )
    with pytest.raises(AgentCancelled):
        agent.run(max_turns=1, cancellation=signal)
    assert closed == [True]
    snapshot = agent.snapshot()
    assert snapshot is not None and snapshot.status == "cancelled"
    assert snapshot.messages[-1].text == "partial"


@pytest.mark.parametrize("override", [False, True])
def test_configured_cancellation_applies_unless_run_overrides_it(
    override: bool,
) -> None:
    from onyx.llm.interfaces import GenerationContext

    configured = CancellationSignal()
    configured.cancel()
    called: list[CancellationSignal] = []

    def reply(
        _request: GenerationRequest, signal: CancellationSignal
    ) -> AssistantMessage:
        called.append(signal)
        return answer()

    agent = Agent(
        FakeModelClient(reply),
        context=AgentContext(execution=GenerationContext(cancellation=configured)),
    )
    if override:
        active = CancellationSignal()
        assert agent.run(max_turns=1, cancellation=active).output.text == "done"
        assert called == [active]
    else:
        with pytest.raises(AgentCancelled):
            agent.run(max_turns=1)
        assert called == []


def test_follow_ups_are_separate_and_steering_takes_priority() -> None:
    agent = Agent(
        scripted(answer("first"), answer("steered"), answer("a"), answer("b"))
    )
    consumed: list[str] = []
    removal_results: list[bool] = []
    queued: list[str] = []

    def observe(event: AgentEvent) -> None:
        if event.type == "agent_start":
            queued.append(agent.follow_up(UserMessage(content="a")))
            queued.append(agent.follow_up(UserMessage(content="b")))
        elif event.type == "message_end" and event.message.text == "first":
            queued.insert(
                0,
                agent.steer(
                    UserMessage(content="now"), expected_execution_id=event.run_id
                ),
            )
        elif event.type == "input_consumed":
            consumed.append(event.input_id)
            removal_results.append(agent.remove_pending_input(event.input_id))

    agent.subscribe(observe)
    result = agent.run(messages=[UserMessage(content="start")], max_turns=4)
    assert [
        message.text if isinstance(message, AssistantMessage) else message.content
        for message in result.messages
    ] == ["start", "first", "now", "steered", "a", "a", "b", "b"]
    assert consumed == queued
    assert removal_results == [False] * 3
    assert agent.pending_inputs == []
    transcript = agent.snapshot()
    assert transcript is not None
    assert [
        message.content
        for message in transcript.messages
        if isinstance(message, UserMessage)
    ] == ["now", "a", "b"]


def test_pending_input_removal_before_consumption() -> None:
    entered = threading.Event()
    release = threading.Event()

    def generate(
        _request: GenerationRequest, _signal: CancellationSignal
    ) -> AssistantMessage:
        entered.set()
        assert release.wait(5)
        return answer()

    agent = Agent(FakeModelClient(generate))
    with ThreadPoolExecutor() as pool:
        result = pool.submit(agent.run, max_turns=2)
        try:
            assert entered.wait(5)
            run_id = agent.execution_id
            assert run_id
            input_id = agent.steer(
                UserMessage(content="discard"), expected_execution_id=run_id
            )
            assert agent.remove_pending_input(input_id)
            assert not agent.remove_pending_input(input_id)
        finally:
            release.set()
        assert result.result(timeout=5).turns == 1
    assert agent.pending_inputs == []


@pytest.mark.parametrize("outcome", ["limit", "cancelled", "error", "complete"])
def test_unconsumed_inputs_stay_with_original_execution(outcome: str) -> None:
    def generate(
        _request: GenerationRequest, signal: CancellationSignal
    ) -> AssistantMessage:
        if outcome == "cancelled":
            signal.cancel()
            signal.check()
        if outcome == "error":
            raise ValueError("provider failed")
        return answer()

    agent = Agent(
        FakeModelClient(generate),
        hooks=AgentHooks(should_stop_after_turn=lambda _: outcome == "complete"),
    )
    ids: list[str] = []

    def enqueue(event: AgentEvent) -> None:
        if event.type == "agent_start":
            ids.append(agent.follow_up(UserMessage(content="pending")))

    unsubscribe = agent.subscribe(enqueue)
    if outcome in {"error", "cancelled"}:
        with pytest.raises((ValueError, AgentCancelled)):
            agent.run(max_turns=1)
    else:
        assert agent.run(max_turns=1).stop_reason == outcome
    unsubscribe()
    pending = agent.pending_inputs
    assert [item.id for item in pending] == ids
    assert isinstance(pending[0].message, UserMessage)
    pending[0].message.content = "modified copy"
    assert agent.pending_inputs[0].message.content == "pending"
    agent.model = scripted(answer("next execution"))
    agent.run(max_turns=1)
    assert [item.id for item in agent.pending_inputs] == ids
    assert not any(
        isinstance(message, UserMessage) for message in agent.context.messages
    )
    assert agent.remove_pending_input(ids[0])


def test_steering_rejects_idle_and_stale_execution() -> None:
    agent = Agent(scripted(answer()))
    with pytest.raises(RuntimeError, match="no active"):
        agent.steer(UserMessage(content="idle"), expected_execution_id="old")
    with pytest.raises(RuntimeError, match="no active"):
        agent.follow_up(UserMessage(content="idle"))

    rejected: list[str] = []

    def observe(event: AgentEvent) -> None:
        if event.type == "agent_start":
            with pytest.raises(RuntimeError, match="does not match"):
                agent.steer(UserMessage(content="stale"), expected_execution_id="old")
            rejected.append("stale")
        elif event.type == "agent_end":
            with pytest.raises(RuntimeError, match="no active"):
                agent.steer(
                    UserMessage(content="late"), expected_execution_id=event.run_id
                )

            rejected.append("late")

    agent.subscribe(observe)
    agent.run(max_turns=1)
    assert rejected == ["stale", "late"]
    assert agent.pending_inputs == []


def test_steering_waits_for_active_tools() -> None:
    entered = threading.Event()
    release = threading.Event()
    consumed: list[str] = []

    def execute(
        _id: str,
        _args: dict[str, JsonValue],
        _signal: CancellationSignal,
        _update: ToolUpdate,
    ) -> ToolResult:
        entered.set()
        if not release.wait(5):
            raise TimeoutError("Tool was not released")
        return ToolResult(content="tool finished")

    agent = Agent(
        scripted(calls(), answer()), context=AgentContext(tools=[echo(execute)])
    )

    def observe(event: AgentEvent) -> None:
        if event.type == "input_consumed":
            consumed.append(event.input_id)

    agent.subscribe(observe)
    with ThreadPoolExecutor() as pool:
        future = pool.submit(agent.run, max_turns=2)
        try:
            assert entered.wait(5)
            run_id = agent.execution_id
            assert run_id
            input_id = agent.steer(
                UserMessage(content="new direction"), expected_execution_id=run_id
            )
            assert consumed == []
        finally:
            release.set()
        result = future.result(timeout=5)
    assert consumed == [input_id]
    assert isinstance(result.messages[1], ToolResultMessage)
    assert isinstance(result.messages[2], UserMessage)
    assert result.messages[2].content == "new direction"


def test_removal_at_continuation_boundary_cannot_trigger_empty_generation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    boundary = threading.Event()
    resume = threading.Event()
    agent = Agent(scripted(answer("first"), answer("second")))
    input_ids: list[str] = []
    consumed: list[str] = []

    class BoundaryLock:
        def __init__(self) -> None:
            self.lock = threading.RLock()
            self.depth = 0
            self.turn_ended = False
            self.releases = 0

        def __enter__(self) -> None:
            self.lock.acquire()
            self.depth += 1

        def __exit__(
            self,
            exc_type: type[BaseException] | None,
            exc: BaseException | None,
            traceback: TracebackType | None,
        ) -> None:
            self.depth -= 1
            at_boundary = False
            if self.depth == 0 and self.turn_ended:
                self.releases += 1
                at_boundary = self.releases == 2
            self.lock.release()
            if at_boundary:
                boundary.set()
                assert resume.wait(5)

    lock = BoundaryLock()
    monkeypatch.setattr(agent, "state_lock", lock)

    def observe(event: AgentEvent) -> None:
        if event.type == "turn_end" and event.turn == 0:
            input_ids.append(agent.follow_up(UserMessage(content="next")))
            lock.turn_ended = True
        elif event.type == "input_consumed":
            consumed.append(event.input_id)

    agent.subscribe(observe)
    with ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(agent.run, max_turns=3)
        try:
            assert boundary.wait(5)
            removed = agent.remove_pending_input(input_ids[0])
        finally:
            resume.set()
        result = future.result(timeout=5)
    assert result.turns == (1 if removed else 2)
    assert consumed == ([] if removed else input_ids)
