"""Exercise the runtime without Onyx rendering, storage, or a provider."""

import threading
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor

import pytest
from pydantic import ValidationError

from onyx.agents.events import AgentEvent, AgentEventType
from onyx.agents.runtime import Agent, AgentContext, AgentHooks, AgentStep, StepResult
from onyx.agents.tools import (
    AgentTool,
    ToolExecutionMode,
    ToolInvocation,
    ToolProgress,
)
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
    execute: Callable[[ToolInvocation], ToolResult] | None = None,
    *,
    sequential: bool = False,
) -> AgentTool:
    return AgentTool(
        name="echo",
        description="Echo",
        parameters={"type": "object"},
        execute=execute
        or (lambda invocation: ToolResult(content=str(invocation.arguments["value"]))),
        execution_mode=ToolExecutionMode.SEQUENTIAL
        if sequential
        else ToolExecutionMode.PARALLEL,
    )


def test_cancelled_turn_retains_completed_tools_for_resume() -> None:
    signal = CancellationSignal()
    requests: list[GenerationRequest] = []

    def generate(
        request: GenerationRequest, _signal: CancellationSignal
    ) -> AssistantMessage:
        requests.append(request)
        return calls(2) if len(requests) == 1 else answer()

    def execute(invocation: ToolInvocation) -> ToolResult:
        if invocation.call_id == "1":
            signal.cancel()
            signal.check()
        return ToolResult(content=invocation.call_id)

    agent = Agent(
        FakeModelClient(generate),
        context=AgentContext(tools=[echo(execute, sequential=True)]),
    )
    with pytest.raises(AgentCancelled):
        agent.run(max_steps=2, cancellation=signal)
    snapshot = agent.snapshot()
    assert snapshot is not None
    results = [
        message
        for message in snapshot.messages
        if isinstance(message, ToolResultMessage)
    ]
    assert [(result.tool_call_id, result.text) for result in results] == [("0", "0")]
    assert agent.run(max_steps=1).output.text == "done"
    replayed = requests[-1].messages
    tool_calls = [
        call.id
        for message in replayed
        if isinstance(message, AssistantMessage)
        for call in message.tool_calls
    ]
    tool_results = [
        message.tool_call_id
        for message in replayed
        if isinstance(message, ToolResultMessage)
    ]
    assert tool_calls == tool_results == ["0"]


@pytest.mark.parametrize("sequential", [False, True])
def test_all_calls_execute_in_order_with_bounded_concurrency(sequential: bool) -> None:
    context = AgentContext(tools=[echo(sequential=sequential)])
    agent = Agent(
        scripted(calls(9), answer()), context=context, max_parallel_operations=2
    )
    events: list[AgentEvent] = []
    agent.subscribe(events.append)
    result = agent.run(messages=[UserMessage(content="run")], max_steps=2)
    assert result.steps == 2
    assert result.stop_reason == "complete"
    results = [
        message
        for message in agent.context.messages
        if isinstance(message, ToolResultMessage)
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
        "step_start",
        "message_start",
        "message_end",
        "tool_start",
        "tool_end",
        "step_end",
    ],
)
def test_cancellation_stops_before_next_operation(
    event_type: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    signal = CancellationSignal()
    executed: list[str] = []

    def execute(invocation: ToolInvocation) -> ToolResult:
        executed.append(invocation.call_id)
        return ToolResult(content="ok")

    agent = Agent(
        scripted(calls(), answer()), context=AgentContext(tools=[echo(execute)])
    )
    events: list[AgentEvent] = []

    original_emit = Agent._emit

    def emit(self: Agent, event: AgentEvent) -> None:
        original_emit(self, event)
        events.append(event)
        if event.type == event_type:
            signal.cancel()

    monkeypatch.setattr(Agent, "_emit", emit)
    with pytest.raises(AgentCancelled):
        agent.run(max_steps=3, cancellation=signal)
    last_event = events[-1]
    assert last_event.type == "agent_end"
    assert last_event.outcome == "cancelled"
    assert agent.wait_for_idle(0)
    if event_type in {"step_start", "message_start", "message_end", "tool_start"}:
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
    agent = Agent(scripted(message, answer()), context=context)
    agent.run(max_steps=2)
    tool_result = agent.context.messages[1]
    assert isinstance(tool_result, ToolResultMessage)
    assert tool_result.is_error and tool_result.tool_call_id == "0"


def test_context_transform_does_not_rewrite_durable_history() -> None:
    agent = Agent(
        scripted(answer()),
        context=AgentContext(messages=[UserMessage(content="original")]),
        hooks=AgentHooks(
            prepare_step=lambda context, _turn: context.model_copy(
                update={"messages": []}
            )
        ),
    )
    agent.run(max_steps=1)
    assert isinstance(agent.context.messages[0], UserMessage)
    assert agent.context.messages[0].content == "original"


def test_steering_and_follow_up_have_distinct_boundaries() -> None:
    agent = Agent(
        scripted(calls(), answer("first"), answer("second")),
        context=AgentContext(tools=[echo()]),
    )

    def enqueue(event: AgentEvent) -> None:
        if event.type == "agent_start":
            agent.follow_up(UserMessage(content="later"))
            agent.steer(UserMessage(content="now"), expected_run_id=event.run_id)

    agent.subscribe(enqueue)
    result = agent.run(max_steps=4)
    assert result.steps == 3
    assert [
        message.content
        for message in agent.context.messages
        if isinstance(message, UserMessage)
    ] == ["now", "later"]
    assert isinstance(agent.context.messages[-2], UserMessage)


def test_tool_hooks_can_block_transform_and_report_progress() -> None:
    def execute(invocation: ToolInvocation) -> ToolResult:
        invocation.update(ToolProgress(content="working"))
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
    agent.run(max_steps=2)
    assert [
        item.content
        for item in agent.context.messages
        if isinstance(item, ToolResultMessage)
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

    async def execute(invocation: ToolInvocation) -> ToolResult:
        signals.append(invocation.cancellation)
        await invocation.run_child(
            Agent(FakeModelClient(child_model)),
            max_steps=1,
            messages=[UserMessage(content="Child task")],
        )
        raise AssertionError("parent must cancel")

    agent = Agent(
        scripted(calls()),
        max_parallel_operations=1,
        context=AgentContext(
            tools=[
                AgentTool(
                    name="echo", description="", parameters={}, execute_async=execute
                )
            ]
        ),
    )
    errors: list[BaseException] = []

    def run() -> None:
        try:
            agent.run(max_steps=2)
        except BaseException as error:
            errors.append(error)

    thread = threading.Thread(target=run)
    thread.start()
    try:
        assert started.wait(3)
        assert not agent.wait_for_idle(0)
        with pytest.raises(RuntimeError, match="already running"):
            agent.run(max_steps=1)
        agent.abort()
        assert agent.wait_for_idle(3)
    finally:
        agent.abort()
        thread.join(3)
    assert len(errors) == 1 and isinstance(errors[0], AgentCancelled)
    assert len(signals) == 2
    assert all(signal.cancelled for signal in signals)
    snapshot = agent.snapshot()
    assert snapshot is not None
    assert snapshot.children[0].input_messages[0].text == "Child task"
    assert snapshot.children[0].status == "cancelled"


def test_limits_and_exception_lifecycle() -> None:
    agent = Agent(scripted(calls()), context=AgentContext(tools=[echo()]))
    assert agent.run(max_steps=1).stop_reason == "limit"
    with pytest.raises(ValidationError):
        agent.run(max_steps=0)
    events: list[AgentEvent] = []

    def fail(
        _context: GenerationRequest, _signal: CancellationSignal
    ) -> AssistantMessage:
        raise ValueError("provider failure")

    agent = Agent(FakeModelClient(fail))
    agent.subscribe(events.append)
    with pytest.raises(ValueError, match="provider failure"):
        agent.run(max_steps=1)
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
        agent.run(max_steps=1)
    assert closed == [True]
    snapshot = agent.snapshot()
    assert snapshot is not None and snapshot.status == "error"
    assert snapshot.messages[-1].text == "partial"


def test_cancellation_closes_active_client_stream() -> None:
    from collections.abc import Generator

    from onyx.llm.interfaces import GenerationContext
    from onyx.llm.models import GenerationDoneEvent, GenerationEvent, TextDeltaEvent

    closed: list[bool] = []
    cancelled = threading.Event()
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
                with signal.on_cancel(cancelled.set):
                    assert cancelled.wait(2)
                signal.check()
                yield GenerationDoneEvent(message=answer("complete"))
            finally:
                closed.append(True)

    agent = Agent(StreamingClient(lambda *_: answer()))
    agent.subscribe(
        lambda event: signal.cancel() if event.type == "message_update" else None
    )
    with pytest.raises(AgentCancelled):
        agent.run(max_steps=1, cancellation=signal)
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
        assert agent.run(max_steps=1, cancellation=active).output.text == "done"
        assert called == [active]
    else:
        with pytest.raises(AgentCancelled):
            agent.run(max_steps=1)
        assert called == []


def test_follow_ups_are_separate_and_steering_takes_priority() -> None:
    consumed: list[str] = []
    removal_results: list[bool] = []
    queued: list[str] = []

    def prepare(context: AgentContext, step: AgentStep) -> AgentContext:
        if step.index == 0:
            queued.extend(
                [
                    agent.follow_up(UserMessage(content="a")),
                    agent.follow_up(UserMessage(content="b")),
                ]
            )
        return context

    def after_step(result: StepResult) -> None:
        if result.step.index == 0:
            run_id = agent.active_run_id
            assert run_id is not None
            queued.insert(
                0, agent.steer(UserMessage(content="now"), expected_run_id=run_id)
            )

    def observe(event: AgentEvent) -> None:
        if event.type == "input_consumed":
            consumed.append(event.input_id)
            removal_results.append(agent.remove_pending_input(event.input_id))

    agent = Agent(
        scripted(answer("first"), answer("steered"), answer("a"), answer("b")),
        hooks=AgentHooks(prepare_step=prepare, after_step=after_step),
    )
    agent.subscribe(observe)
    agent.run(messages=[UserMessage(content="start")], max_steps=4)
    assert [message.text for message in agent.context.messages] == [
        "start",
        "first",
        "now",
        "steered",
        "a",
        "a",
        "b",
        "b",
    ]
    snapshot = agent.snapshot()
    assert snapshot is not None
    assert snapshot.input_messages[0].text == "start"
    assert [message.text for message in snapshot.messages] == [
        "first",
        "now",
        "steered",
        "a",
        "a",
        "b",
        "b",
    ]
    assert consumed == queued
    assert removal_results == [False] * 3
    assert agent.pending_inputs == []


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
        result = pool.submit(agent.run, max_steps=2)
        try:
            assert entered.wait(5)
            run_id = agent.active_run_id
            assert run_id
            input_id = agent.steer(
                UserMessage(content="discard"), expected_run_id=run_id
            )
            assert agent.remove_pending_input(input_id)
            assert not agent.remove_pending_input(input_id)
        finally:
            release.set()
        assert result.result(timeout=5).steps == 1
    assert agent.pending_inputs == []


@pytest.mark.parametrize("outcome", ["limit", "cancelled", "error"])
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

    ids: list[str] = []

    def prepare(context: AgentContext, _turn: AgentStep) -> AgentContext:
        ids.append(agent.follow_up(UserMessage(content="pending")))
        return context

    agent = Agent(
        FakeModelClient(generate),
        hooks=AgentHooks(
            prepare_step=prepare,
            after_step=lambda _: False if outcome == "complete" else None,
        ),
    )
    if outcome in {"error", "cancelled"}:
        with pytest.raises((ValueError, AgentCancelled)):
            agent.run(max_steps=1)
    else:
        assert agent.run(max_steps=1).stop_reason == outcome
    snapshot = agent.snapshot()
    assert snapshot is not None
    assert snapshot.input_messages == []
    assert not any(isinstance(message, UserMessage) for message in snapshot.messages)
    pending = agent.pending_inputs
    assert [item.id for item in pending] == ids
    assert isinstance(pending[0].message, UserMessage)
    pending[0].message.content = "modified copy"
    assert agent.pending_inputs[0].message.content == "pending"
    agent.hooks = AgentHooks()
    agent.llm = scripted(answer("next execution"))
    agent.run(max_steps=1)
    assert [item.id for item in agent.pending_inputs] == ids
    assert not any(
        isinstance(message, UserMessage) for message in agent.context.messages
    )
    assert agent.remove_pending_input(ids[0])


def test_steering_rejects_idle_and_stale_execution() -> None:
    def prepare(context: AgentContext, _turn: AgentStep) -> AgentContext:
        with pytest.raises(RuntimeError, match="does not match"):
            agent.steer(UserMessage(content="stale"), expected_run_id="old")
        return context

    agent = Agent(scripted(answer()), hooks=AgentHooks(prepare_step=prepare))
    with pytest.raises(RuntimeError, match="no active"):
        agent.steer(UserMessage(content="idle"), expected_run_id="old")
    agent.run(max_steps=1)
    with pytest.raises(RuntimeError, match="no active"):
        agent.steer(UserMessage(content="late"), expected_run_id="old")
    assert agent.pending_inputs == []


def test_steering_waits_for_active_tools() -> None:
    entered = threading.Event()
    release = threading.Event()
    consumed: list[str] = []

    def execute(_invocation: ToolInvocation) -> ToolResult:
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
        future = pool.submit(agent.run, max_steps=2)
        try:
            assert entered.wait(5)
            run_id = agent.active_run_id
            assert run_id
            input_id = agent.steer(
                UserMessage(content="new direction"), expected_run_id=run_id
            )
            assert consumed == []
        finally:
            release.set()
        future.result(timeout=5)
    assert consumed == [input_id]
    assert isinstance(agent.context.messages[1], ToolResultMessage)
    assert isinstance(agent.context.messages[2], UserMessage)
    assert agent.context.messages[2].content == "new direction"


def test_removal_before_continuation_prevents_an_empty_generation() -> None:
    boundary = threading.Event()
    resume = threading.Event()
    input_ids: list[str] = []

    def after_step(_result: StepResult) -> None:
        input_ids.append(agent.follow_up(UserMessage(content="next")))
        boundary.set()
        assert resume.wait(5)

    agent = Agent(scripted(answer("first")), hooks=AgentHooks(after_step=after_step))
    with ThreadPoolExecutor(max_workers=1) as workers:
        future = workers.submit(agent.run, max_steps=3)
        try:
            assert boundary.wait(2)
            assert agent.remove_pending_input(input_ids[0])
        finally:
            resume.set()
        assert future.result(timeout=2).steps == 1
    assert agent.pending_inputs == []


def test_failed_tool_status_survives_successful_agent_completion() -> None:
    agent = Agent(
        scripted(calls(), answer("Explained tool failure")),
        context=AgentContext(
            tools=[
                echo(
                    lambda _invocation: ToolResult(content="unavailable", is_error=True)
                )
            ]
        ),
    )
    events: list[AgentEvent] = []
    agent.subscribe(events.append)
    result = agent.run(max_steps=2)
    assert result.output.text == "Explained tool failure"
    assert result.stop_reason == "complete"
    snapshot = agent.snapshot()
    assert snapshot is not None and snapshot.status == "complete"
    operations = [
        operation for operation in snapshot.operations if operation.tool_call_id
    ]
    assert operations and all(operation.status == "error" for operation in operations)
    transcript = snapshot.transcript()
    assert [operation.status for operation in transcript.operations] == [
        operation.status for operation in snapshot.operations
    ]
    ends = [event for event in events if event.type == "tool_end"]
    assert len(ends) == len(operations)
    assert all(event.result.is_error for event in ends)
