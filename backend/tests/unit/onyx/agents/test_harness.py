"""Exercise the runtime without Onyx rendering, storage, or a provider."""

import threading
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor

import pytest
from pydantic import ValidationError

from onyx.agents.agent_coordination import AgentCoordinator
from onyx.agents.events import AgentEvent, AgentEventType
from onyx.agents.models import AgentState, PreparedStep, RunState
from onyx.agents.runtime import Agent, Run, RunFailed
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
    GenerationOptions,
    GenerationRequest,
    TextContent,
    ToolCall,
    ToolResult,
    ToolResultMessage,
    UserMessage,
)
from tests.unit.onyx.agents.fakes import (
    FakeModelClient,
    FakeRunOwnership,
    FakeRunStore,
    run_agent,
)


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
    runs: list[Run] = []
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
        tools=[echo(execute, sequential=True)],
    )
    with pytest.raises(AgentCancelled):
        run_agent(agent, runs=runs, max_steps=2, cancellation=signal)
    snapshot = runs[-1].snapshot()
    assert snapshot is not None
    results = [
        message
        for message in snapshot.messages
        if isinstance(message, ToolResultMessage)
    ]
    assert [(result.tool_call_id, result.text) for result in results] == [("0", "0")]
    assert run_agent(agent, runs=runs, max_steps=1).output.text == "done"
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
def test_all_calls_record_in_order_for_each_execution_mode(sequential: bool) -> None:
    runs: list[Run] = []
    context = AgentState()
    agent = Agent(
        scripted(calls(9), answer()),
        state=context,
        tools=[echo(sequential=sequential)],
    )
    events: list[AgentEvent] = []
    result = run_agent(
        agent,
        runs=runs,
        listener=events.append,
        messages=[UserMessage(content="run")],
        max_steps=2,
    )
    assert result.steps == 2
    assert result.stop_reason == "complete"
    results = [
        message
        for message in agent.state.messages
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


def test_observer_can_cancel_active_execution() -> None:
    signal = CancellationSignal()
    events: list[AgentEvent] = []

    def generate(
        _request: GenerationRequest, cancellation: CancellationSignal
    ) -> AssistantMessage:
        cancelled = threading.Event()
        with cancellation.on_cancel(cancelled.set):
            assert cancelled.wait(2)
        cancellation.check()
        raise AssertionError("Cancelled model must not return output")

    def observe(event: AgentEvent) -> None:
        events.append(event)
        if event.type == "message_start":
            signal.cancel()

    run = Agent(FakeModelClient(generate)).start(
        max_steps=1,
        cancellation=signal,
        on_event=observe,
    )
    try:
        with pytest.raises(AgentCancelled):
            run.result(timeout=3)
    finally:
        run.cancel()
        assert run.wait_for_idle(timeout=3)
    assert events[-1].type == "agent_end"
    assert events[-1].outcome == "cancelled"


@pytest.mark.parametrize(
    "invalid", ["unknown", "arguments", "incomplete", "truncated", "disabled"]
)
def test_invalid_calls_get_paired_errors(invalid: str) -> None:
    runs: list[Run] = []
    message = calls(name="missing") if invalid == "unknown" else calls()
    if invalid == "arguments":
        message.tool_calls[0].argument_error = "Bad arguments"
    if invalid == "incomplete":
        message.tool_calls[0].arguments_complete = False
        message.tool_calls[0].raw_arguments = '{"value":'
    if invalid == "truncated":
        message.stop_reason = "length"
    options = GenerationOptions()
    if invalid == "disabled":
        from onyx.llm.models import ToolChoiceOptions

        options.tool_choice = ToolChoiceOptions.NONE
    agent = Agent(scripted(message, answer()), tools=[echo()], options=options)
    run_agent(agent, runs=runs, max_steps=2)
    tool_result = agent.state.messages[1]
    assert isinstance(tool_result, ToolResultMessage)
    assert tool_result.is_error and tool_result.tool_call_id == "0"


def test_context_transform_does_not_rewrite_durable_history() -> None:
    runs: list[Run] = []
    agent = Agent(
        scripted(answer()),
        state=AgentState(messages=[UserMessage(content="original")]),
        prepare_step=lambda _state: PreparedStep(
            assemble_messages=lambda _messages: []
        ),
    )
    run_agent(agent, runs=runs, max_steps=1)
    assert isinstance(agent.state.messages[0], UserMessage)
    assert agent.state.messages[0].content == "original"


def test_tool_hooks_can_block_transform_and_report_progress() -> None:
    runs: list[Run] = []

    def execute(invocation: ToolInvocation) -> ToolResult:
        invocation.update(ToolProgress(content="working"))
        return ToolResult(content="raw")

    agent = Agent(
        scripted(calls(2), answer()),
        tools=[echo(execute)],
        before_tool_call=lambda context: (
            ToolResult(content="blocked", is_error=True)
            if context.call.id == "1"
            else None
        ),
        after_tool_call=lambda _context, result: result.model_copy(
            update={"content": str(result.content) + "!"}
        ),
    )
    events: list[AgentEvent] = []
    run_agent(agent, runs=runs, listener=events.append, max_steps=2)
    assert [
        item.content
        for item in agent.state.messages
        if isinstance(item, ToolResultMessage)
    ] == ["raw!", "blocked!"]
    assert sorted(
        event.progress.content for event in events if event.type == "tool_update"
    ) == ["blocked", "raw", "working"]


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

    def execute(invocation: ToolInvocation) -> ToolResult:
        signals.append(invocation.cancellation)
        submission = invocation.agents.spawn_agent(
            Agent(FakeModelClient(child_model)),
            name="child",
            description="Run the child task",
            max_steps=1,
            messages=[UserMessage(content="Child task")],
        )
        invocation.agents.wait_run(submission.run_id)
        raise AssertionError("parent must cancel")

    agent = Agent(
        scripted(calls()),
        tools=[AgentTool(name="echo", description="", parameters={}, execute=execute)],
    )

    def exercise() -> None:
        coordinator = AgentCoordinator()
        run = agent.start(max_steps=2, coordinator=coordinator)
        try:
            assert started.wait(3)
            assert not run.wait_for_idle(timeout=0)
            with pytest.raises(RuntimeError, match="already running"):
                agent.start(max_steps=1)
            run.cancel()
            with pytest.raises(AgentCancelled):
                run.result(timeout=3)
            assert run.wait_for_idle(timeout=3)
        finally:
            run.cancel()
            coordinator.close(timeout=3)
        assert len(signals) == 2
        assert all(signal.cancelled for signal in signals)
        snapshot = run.snapshot()
        assert snapshot.child_runs[0].input_messages[0].text == "Child task"
        assert snapshot.child_runs[0].status == "cancelled"

    exercise()


def test_limits_and_exception_lifecycle() -> None:
    runs: list[Run] = []
    agent = Agent(scripted(calls()), tools=[echo()])
    events: list[AgentEvent] = []
    assert (
        run_agent(agent, runs=runs, listener=events.append, max_steps=1).stop_reason
        == "limit"
    )
    with pytest.raises(ValidationError):
        run_agent(agent, runs=runs, listener=events.append, max_steps=0)
    events: list[AgentEvent] = []

    def fail(
        _context: GenerationRequest, _signal: CancellationSignal
    ) -> AssistantMessage:
        raise ValueError("provider failure")

    agent = Agent(FakeModelClient(fail))
    with pytest.raises(RunFailed):
        run_agent(agent, runs=runs, listener=events.append, max_steps=1)
    last_event = events[-1]
    assert last_event.type == "agent_end"
    assert last_event.outcome == "error"
    assert runs[-1].wait_for_idle(timeout=0)


def test_incomplete_model_stream_cannot_complete_an_agent_turn() -> None:
    runs: list[Run] = []
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
                yield TextDeltaEvent(content_index=0, text="partial")
            finally:
                closed.append(True)

    agent = Agent(IncompleteClient(lambda *_: answer()))
    with pytest.raises(RunFailed):
        run_agent(agent, runs=runs, max_steps=1)
    assert closed == [True]
    snapshot = runs[-1].snapshot()
    assert snapshot is not None and snapshot.status == "error"
    assert snapshot.messages[-1].text == "partial"


def test_cancellation_closes_active_client_stream() -> None:
    runs: list[Run] = []
    from collections.abc import Generator

    from onyx.llm.interfaces import GenerationContext
    from onyx.llm.models import (
        GenerationDoneEvent,
        GenerationEvent,
        TextDeltaEvent,
    )

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
                yield TextDeltaEvent(content_index=0, text="partial")
                with signal.on_cancel(cancelled.set):
                    assert cancelled.wait(2)
                signal.check()
                yield GenerationDoneEvent(message=answer("complete"))
            finally:
                closed.append(True)

    agent = Agent(StreamingClient(lambda *_: answer()))
    with pytest.raises(AgentCancelled):
        run_agent(
            agent,
            runs=runs,
            max_steps=1,
            cancellation=signal,
            listener=lambda event: (
                signal.cancel() if event.type == "message_update" else None
            ),
        )
    assert closed == [True]
    snapshot = runs[-1].snapshot()
    assert snapshot is not None and snapshot.status == "cancelled"
    assert snapshot.messages[-1].text == "partial"


@pytest.mark.parametrize("override", [False, True])
def test_configured_cancellation_applies_unless_run_overrides_it(
    override: bool,
) -> None:
    runs: list[Run] = []
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
        generation_context=GenerationContext(cancellation=configured),
    )
    if override:
        active = CancellationSignal()
        assert (
            run_agent(agent, runs=runs, max_steps=1, cancellation=active).output.text
            == "done"
        )
        assert called == [active]
    else:
        with pytest.raises(AgentCancelled):
            run_agent(agent, runs=runs, max_steps=1)
        assert called == []


def test_failed_tool_status_survives_successful_agent_completion() -> None:
    runs: list[Run] = []
    agent = Agent(
        scripted(calls(), answer("Explained tool failure")),
        tools=[
            echo(lambda _invocation: ToolResult(content="unavailable", is_error=True))
        ],
    )
    events: list[AgentEvent] = []
    result = run_agent(agent, runs=runs, listener=events.append, max_steps=2)
    assert result.output.text == "Explained tool failure"
    assert result.stop_reason == "complete"
    snapshot = runs[-1].snapshot()
    assert snapshot is not None and snapshot.status == "complete"
    operations = [
        execution for step in snapshot.steps for execution in step.tools.values()
    ]
    assert operations and all(operation.status == "error" for operation in operations)
    ends = [event for event in events if event.type == "tool_end"]
    assert len(ends) == len(operations)
    assert all(event.result.is_error for event in ends)


def test_each_run_accepts_explicit_input_and_preserves_prior_history() -> None:
    runs: list[Run] = []
    requests: list[list[str]] = []

    def generate(
        request: GenerationRequest, _signal: CancellationSignal
    ) -> AssistantMessage:
        requests.append([message.text for message in request.messages])
        return answer(f"answer {len(requests)}")

    supplied = UserMessage(content="first task")
    agent = Agent(FakeModelClient(generate))
    first = run_agent(agent, runs=runs, messages=[supplied], max_steps=1)
    first_snapshot = runs[-1].snapshot()
    assert first_snapshot is not None
    supplied.content = "modified caller input"
    first.output.content.clear()
    second = run_agent(
        agent, runs=runs, messages=[UserMessage(content="second task")], max_steps=1
    )
    assert first.run_id != second.run_id
    assert requests == [["first task"], ["first task", "answer 1", "second task"]]
    assert first_snapshot.input_messages[0].text == "first task"
    assert [message.text for message in first_snapshot.messages] == ["answer 1"]
    assert [message.text for message in agent.state.messages] == [
        "first task",
        "answer 1",
        "second task",
        "answer 2",
    ]


def test_busy_run_rejects_input_without_changing_history() -> None:
    runs: list[Run] = []
    entered, release = threading.Event(), threading.Event()

    def generate(
        _request: GenerationRequest, _signal: CancellationSignal
    ) -> AssistantMessage:
        entered.set()
        assert release.wait(3)
        return answer()

    agent = Agent(FakeModelClient(generate))
    with ThreadPoolExecutor(max_workers=1) as workers:
        running = workers.submit(
            lambda: agent.start(
                background=False,
                messages=[UserMessage(content="accepted")],
                max_steps=1,
            ).result()
        )
        try:
            assert entered.wait(2)
            with pytest.raises(RuntimeError, match="already running"):
                run_agent(
                    agent,
                    runs=runs,
                    messages=[UserMessage(content="rejected")],
                    max_steps=1,
                )
        finally:
            release.set()
        running.result(timeout=2)
    assert [message.text for message in agent.state.messages] == ["accepted", "done"]
    # The rejected attempt must not leave the agent unusable.
    assert agent.start(background=False, max_steps=1).result().output.text == "done"


def test_current_thread_start_completes_storage_before_return() -> None:
    caller = threading.current_thread()
    visited: list[str] = []

    def generate(
        _request: GenerationRequest, _signal: CancellationSignal
    ) -> AssistantMessage:
        assert threading.current_thread() is caller
        visited.append("model")
        return answer()

    def save(_snapshot: RunState) -> None:
        assert threading.current_thread() is caller
        visited.append("save")

    def release(_run_id: str) -> None:
        assert threading.current_thread() is caller
        visited.append("release")

    coordinator = AgentCoordinator(
        store=FakeRunStore(save=lambda run: save(run.snapshot())),
        ownership=FakeRunOwnership(release=release),
    )

    run = Agent(FakeModelClient(generate)).start(
        background=False, max_steps=1, coordinator=coordinator
    )
    assert run.result(0).output.text == "done"
    assert coordinator.completion(run.id).result(0).run_id == run.id
    assert visited == ["model", "save", "release"]
    assert coordinator.close(3)


@pytest.mark.parametrize("error_type", [RuntimeError, TimeoutError])
def test_release_failure_remains_observable_after_execution_drains(
    error_type: type[Exception],
) -> None:
    def release(_run_id: str) -> None:
        raise error_type("Ownership release failed")

    coordinator = AgentCoordinator(ownership=FakeRunOwnership(release=release))
    agent = Agent(FakeModelClient(lambda *_: answer()))
    run = agent.start(background=False, max_steps=1, coordinator=coordinator)
    assert run.result(0).output.text == "done"
    assert coordinator.completion(run.id).result(0).run_id == run.id
    assert run._idle.done()
    with pytest.raises(error_type, match="Ownership release failed"):
        run.wait_for_idle(0)
    with pytest.raises(error_type, match="Ownership release failed"):
        agent.start(max_steps=1, coordinator=coordinator)
    assert coordinator.close(0)


@pytest.mark.parametrize("replace_ownership", [False, True])
def test_coordinator_view_inherits_ownership_independently_of_store(
    replace_ownership: bool,
) -> None:
    events: list[str] = []
    owner = AgentCoordinator(
        ownership=FakeRunOwnership(
            register=lambda _run: events.append("owner.register"),
            release=lambda _run_id: events.append("owner.release"),
        )
    )
    view = owner.view(
        store=FakeRunStore(save=lambda _run: events.append("save")),
        ownership=FakeRunOwnership(
            register=lambda _run: events.append("view.register"),
            release=lambda _run_id: events.append("view.release"),
        )
        if replace_ownership
        else None,
    )
    try:
        run = Agent(FakeModelClient(lambda *_: answer())).start(
            background=False, max_steps=1, coordinator=view
        )
        assert run.result(0).output.text == "done"
        scope = "view" if replace_ownership else "owner"
        assert events == [f"{scope}.register", "save", f"{scope}.release"]
    finally:
        assert owner.close(3)
