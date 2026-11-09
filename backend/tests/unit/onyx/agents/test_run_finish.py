"""The run finish hook sets the final results of tool calls for every outcome."""

import threading
import time
from collections.abc import Callable, Sequence
from datetime import datetime, timedelta, timezone

import pytest

from onyx.agents.agent_coordination import AgentCoordinator
from onyx.agents.events import (
    AgentEndEvent,
    AgentEvent,
    MessageEndEvent,
    ToolResultAmendedEvent,
)
from onyx.agents.models import (
    ExecutionStatus,
    PreparedStep,
    ReleaseFailed,
    RunFailureKind,
    RunState,
    RunStatus,
    ToolCallContext,
    ToolResultAmendment,
)
from onyx.agents.runtime import Agent, Run
from onyx.agents.tools import (
    AgentTool,
    InputMode,
    PendingToolInput,
    ToolInvocation,
)
from onyx.llm.cancellation import AgentCancelled, CancellationSignal
from onyx.llm.interfaces import GenerationContext
from onyx.llm.model_response import (
    ChatCompletionDeltaToolCall,
    Delta,
    ResponseFunctionCall,
)
from onyx.llm.models import (
    AssistantMessage,
    GenerationRequest,
    Message,
    TextContent,
    ToolCall,
    ToolDefinition,
    ToolResult,
    ToolResultMessage,
    UserMessage,
)
from onyx.tracing.flows import LLMFlow
from tests.unit.onyx.agents.fakes import FakeModelClient, FakeRunStore, ScriptedLLM

CALL_ID = "cell"


class FinishHook:
    """Records each call and amends the first recorded tool result."""

    def __init__(
        self,
        *,
        error: BaseException | None = None,
        call_id: str = CALL_ID,
        wait_until: datetime | None = None,
    ) -> None:
        self.calls: list[list[ToolResultMessage]] = []
        # Raised instead of returning amendments.
        self.error = error
        self.call_id = call_id
        # The call returns only after this time passes.
        self.wait_until = wait_until
        # When each call started and returned.
        self.spans: list[tuple[datetime, datetime]] = []

    def __call__(self, results: list[ToolResultMessage]) -> list[ToolResultAmendment]:
        self.calls.append(results)
        started = datetime.now(timezone.utc)
        while self.wait_until is not None and (
            datetime.now(timezone.utc) <= self.wait_until
        ):
            time.sleep(0.01)
        self.spans.append((started, datetime.now(timezone.utc)))
        if self.error is not None:
            raise self.error
        return [
            ToolResultAmendment(
                call_id=self.call_id, result=ToolResult(content="closed")
            )
        ]


def _agent(
    *,
    reply: Callable[[GenerationRequest, CancellationSignal], AssistantMessage],
    execute: Callable[[ToolInvocation], ToolResult],
    hook: FinishHook,
) -> Agent:
    return Agent(
        FakeModelClient(reply),
        generation_context=GenerationContext(flow=LLMFlow.CHAT_RESPONSE),
        tools=[
            AgentTool(
                definition=ToolDefinition(name="cell", description="", parameters={}),
                execute=execute,
            )
        ],
        on_finish=hook,
    )


def _call_then(
    after_tool: Callable[[], AssistantMessage],
) -> Callable[[GenerationRequest, CancellationSignal], AssistantMessage]:
    def reply(
        request: GenerationRequest, _signal: CancellationSignal
    ) -> AssistantMessage:
        if request.messages and isinstance(request.messages[-1], ToolResultMessage):
            return after_tool()
        return AssistantMessage(
            content=[ToolCall(id=CALL_ID, name="cell", arguments={})]
        )

    return reply


def _answer() -> AssistantMessage:
    return AssistantMessage(content=[TextContent(text="done")])


def _fail() -> AssistantMessage:
    raise ValueError("model failed")


def _run(
    agent: Agent,
    *,
    cancellation: CancellationSignal | None = None,
    deadline_at: datetime | None = None,
) -> tuple[Run, list[AgentEvent], list[RunState]]:
    events: list[AgentEvent] = []
    saved: list[RunState] = []
    run = agent.start(
        max_steps=10,
        cancellation=cancellation,
        coordinator=AgentCoordinator(
            store=FakeRunStore(save=lambda run: saved.append(run.snapshot()))
        ),
        on_event=events.append,
        deadline_at=deadline_at,
    )
    run.wait_for_completion(timeout=10)
    assert run.wait_for_idle(timeout=10)
    return run, events, saved


def _assert_amended(
    run: Run, events: list[AgentEvent], saved: list[RunState], outcome: RunStatus
) -> None:
    amended = [event for event in events if isinstance(event, ToolResultAmendedEvent)]
    assert [event.result.text for event in amended] == ["closed"]
    assert amended[0].tool_call.id == CALL_ID
    end = next(event for event in events if isinstance(event, AgentEndEvent))
    assert events.index(amended[0]) < events.index(end)
    assert end.outcome == outcome
    # The response is saved with the amended result.
    assert len(saved) == 1
    for state in (saved[0], run.snapshot()):
        result = state.steps[0].tools[CALL_ID].result
        assert result is not None and result.text == "closed"
        assert result.tool_call_id == CALL_ID


def test_finish_hook_amends_result_when_run_completes() -> None:
    hook = FinishHook()
    agent = _agent(
        reply=_call_then(_answer),
        execute=lambda _invocation: ToolResult(content="running"),
        hook=hook,
    )
    run, events, saved = _run(agent)
    assert run.status == RunStatus.COMPLETE
    assert len(hook.calls) == 1
    assert [result.text for result in hook.calls[0]] == ["running"]
    _assert_amended(run, events, saved, RunStatus.COMPLETE)


def test_finish_hook_amends_result_when_model_fails() -> None:
    hook = FinishHook()
    agent = _agent(
        reply=_call_then(_fail),
        execute=lambda _invocation: ToolResult(content="running"),
        hook=hook,
    )
    run, events, saved = _run(agent)
    assert run.status == RunStatus.ERROR
    assert len(hook.calls) == 1
    _assert_amended(run, events, saved, RunStatus.ERROR)


@pytest.mark.parametrize("stop", ["user", "user_then_deadline_passes", "deadline"])
def test_finish_hook_amends_result_when_run_is_cancelled(stop: str) -> None:
    # A Stop wins over a deadline that passes while the run finishes.
    hook = FinishHook()
    second_step = threading.Event()
    cancellation = CancellationSignal()

    def wait_for_stop(
        _request: GenerationRequest, signal: CancellationSignal
    ) -> AssistantMessage:
        stopped = threading.Event()
        with signal.on_cancel(stopped.set):
            second_step.set()
            stopped.wait(10)
        signal.check()
        return _answer()

    def reply(
        request: GenerationRequest, signal: CancellationSignal
    ) -> AssistantMessage:
        if request.messages and isinstance(request.messages[-1], ToolResultMessage):
            return wait_for_stop(request, signal)
        return AssistantMessage(
            content=[ToolCall(id=CALL_ID, name="cell", arguments={})]
        )

    agent = _agent(
        reply=reply,
        execute=lambda _invocation: ToolResult(content="running"),
        hook=hook,
    )
    deadline_at: datetime | None = None
    if stop != "deadline":
        threading.Thread(
            target=lambda: second_step.wait(10) and cancellation.cancel(), daemon=True
        ).start()
        if stop == "user_then_deadline_passes":
            # The Stop comes at the second step, within milliseconds; the deadline
            # passes while the finish hook runs.
            deadline_at = datetime.now(timezone.utc) + timedelta(seconds=1.5)
            hook.wait_until = deadline_at
        run, events, saved = _run(
            agent, cancellation=cancellation, deadline_at=deadline_at
        )
        if deadline_at is not None:
            [(hook_started, hook_ended)] = hook.spans
            assert hook_started < deadline_at < hook_ended
    else:
        run, events, saved = _run(
            agent,
            deadline_at=datetime.now(timezone.utc) + timedelta(seconds=0.5),
        )
    assert run.status == RunStatus.CANCELLED
    assert len(hook.calls) == 1
    _assert_amended(run, events, saved, RunStatus.CANCELLED)
    # A deadline is reported as such; a requested stop has no failure.
    end = next(event for event in events if isinstance(event, AgentEndEvent))
    failure = saved[0].failure
    if stop != "deadline":
        assert failure is None and end.failure is None
    else:
        assert failure is not None and failure.kind == RunFailureKind.DEADLINE
        assert end.failure == failure
    # The partial answer ends before the amendment, as the saved order has it.
    partial_end = next(
        index
        for index, event in enumerate(events)
        if isinstance(event, MessageEndEvent) and event.step_index == 1
    )
    amended = next(
        index
        for index, event in enumerate(events)
        if isinstance(event, ToolResultAmendedEvent)
    )
    assert partial_end < amended


def test_failed_finish_hook_keeps_the_outcome_and_recorded_results() -> None:
    hook = FinishHook(error=RuntimeError("finish hook failed"))
    agent = _agent(
        reply=_call_then(_answer),
        execute=lambda _invocation: ToolResult(content="running"),
        hook=hook,
    )
    run, events, saved = _run(agent)
    assert run.status == RunStatus.COMPLETE
    assert not any(isinstance(event, ToolResultAmendedEvent) for event in events)
    result = saved[0].steps[0].tools[CALL_ID].result
    assert result is not None and result.text == "running"


def test_finish_hook_stopped_by_cancellation_still_ends_the_run() -> None:
    hook = FinishHook(error=AgentCancelled())
    cancellation = CancellationSignal()

    def reply(
        request: GenerationRequest, signal: CancellationSignal
    ) -> AssistantMessage:
        if request.messages and isinstance(request.messages[-1], ToolResultMessage):
            # The user stops the run at its second step.
            cancellation.cancel()
            signal.check()
        return AssistantMessage(
            content=[ToolCall(id=CALL_ID, name="cell", arguments={})]
        )

    agent = _agent(
        reply=reply,
        execute=lambda _invocation: ToolResult(content="running"),
        hook=hook,
    )
    run, events, saved = _run(agent, cancellation=cancellation)
    assert run.status == RunStatus.CANCELLED
    assert len(hook.calls) == 1
    end = next(event for event in events if isinstance(event, AgentEndEvent))
    assert end.outcome == RunStatus.CANCELLED
    assert not any(isinstance(event, ToolResultAmendedEvent) for event in events)
    assert len(saved) == 1
    result = saved[0].steps[0].tools[CALL_ID].result
    assert result is not None and result.text == "running"


def test_amendment_of_unknown_call_is_skipped() -> None:
    agent = _agent(
        reply=_call_then(_answer),
        execute=lambda _invocation: ToolResult(content="running"),
        hook=FinishHook(call_id="missing"),
    )
    run, events, saved = _run(agent)
    assert run.status == RunStatus.COMPLETE
    assert not any(isinstance(event, ToolResultAmendedEvent) for event in events)
    result = saved[0].steps[0].tools[CALL_ID].result
    assert result is not None and result.text == "running"


def _without_tool_steps(messages: Sequence[Message]) -> list[Message]:
    """The request as compaction leaves it: earlier steps' calls are gone."""
    return [message for message in messages if isinstance(message, UserMessage)]


@pytest.mark.parametrize("compacted", [False, True])
def test_an_amendment_reaches_its_call_when_the_provider_repeats_call_ids(
    compacted: bool,
) -> None:
    repeated = Delta(
        tool_calls=[
            ChatCompletionDeltaToolCall(
                index=0,
                id="call_0",
                function=ResponseFunctionCall(name="cell", arguments="{}"),
            )
        ]
    )
    llm = ScriptedLLM([repeated, repeated, Delta(content="done")])
    step = iter(["first", "second"])

    def close_first(results: list[ToolResultMessage]) -> list[ToolResultAmendment]:
        return [
            ToolResultAmendment(
                call_id=results[0].tool_call_id, result=ToolResult(content="closed")
            )
        ]

    agent = Agent(
        llm,
        generation_context=GenerationContext(flow=LLMFlow.CHAT_RESPONSE),
        tools=[
            AgentTool(
                definition=ToolDefinition(name="cell", description="", parameters={}),
                execute=lambda _invocation: ToolResult(content=next(step)),
            )
        ],
        on_finish=close_first,
        prepare_step=(
            lambda _input: PreparedStep(assemble_messages=_without_tool_steps)
        )
        if compacted
        else None,
    )
    run, _events, saved = _run(agent)
    assert run.status == RunStatus.COMPLETE
    if compacted:
        assert all(
            message.role != "assistant"
            for request in llm.requests
            for message in request["prompt"]
        )
    calls = [step.message.tool_calls[0] for step in saved[0].steps[:2]]
    assert calls[0].id != calls[1].id
    results = [
        step.tools[call.id].result
        for step, call in zip(saved[0].steps[:2], calls, strict=True)
    ]
    assert [result.text if result else None for result in results] == [
        "closed",
        "second",
    ]


def test_finish_hook_sets_the_result_of_a_call_that_stop_interrupted() -> None:
    hook = FinishHook()
    cancellation = CancellationSignal()
    running = threading.Event()

    def execute(invocation: ToolInvocation) -> ToolResult:
        stopped = threading.Event()
        with invocation.cancellation.on_cancel(stopped.set):
            running.set()
            stopped.wait(10)
        raise AgentCancelled()

    agent = _agent(reply=_call_then(_answer), execute=execute, hook=hook)
    threading.Thread(
        target=lambda: running.wait(10) and cancellation.cancel(), daemon=True
    ).start()
    run, events, saved = _run(agent, cancellation=cancellation)
    assert run.status == RunStatus.CANCELLED
    # The hook sees no recorded result for the interrupted call.
    assert hook.calls == [[]]
    _assert_amended(run, events, saved, RunStatus.CANCELLED)
    assert saved[0].steps[0].tools[CALL_ID].status == ExecutionStatus.CANCELLED


def test_suspend_hook_amends_results_before_the_run_suspends() -> None:
    hook = FinishHook()
    events: list[AgentEvent] = []

    def gate(context: ToolCallContext) -> PendingToolInput | None:
        if context.call.name != "approve":
            return None
        return PendingToolInput(
            request_id="permission", prompt="Proceed?", mode=InputMode.EXECUTE
        )

    def reply(
        request: GenerationRequest, _signal: CancellationSignal
    ) -> AssistantMessage:
        if any(isinstance(message, ToolResultMessage) for message in request.messages):
            return _answer()
        return AssistantMessage(
            content=[
                ToolCall(id=CALL_ID, name="cell", arguments={}),
                ToolCall(id="approve", name="approve", arguments={}),
            ]
        )

    agent = Agent(
        FakeModelClient(reply),
        generation_context=GenerationContext(flow=LLMFlow.CHAT_RESPONSE),
        tools=[
            AgentTool(
                definition=ToolDefinition(name=name, description="", parameters={}),
                execute=lambda _invocation: ToolResult(content="running"),
            )
            for name in ("cell", "approve")
        ],
        before_tool_call=gate,
        on_suspend=hook,
    )
    coordinator = AgentCoordinator()
    run = agent.start(max_steps=2, coordinator=coordinator, on_event=events.append)
    try:
        assert run.wait_until_settled(3).status == RunStatus.SUSPENDED
        assert run.wait_for_idle(3)
        assert [[result.text for result in results] for results in hook.calls] == [
            ["running"]
        ]
        amended = [e for e in events if isinstance(e, ToolResultAmendedEvent)]
        assert [(e.tool_call.id, e.result.text) for e in amended] == [
            (CALL_ID, "closed")
        ]
        # The captured state holds the amended result.
        result = run.snapshot().steps[0].tools[CALL_ID].result
        assert result is not None and result.text == "closed"
    finally:
        run.cancel()
        assert run.wait_for_idle(3)
        assert coordinator.close(3)


def test_suspend_hook_stopped_by_cancellation_finishes_the_run() -> None:
    cancellation = CancellationSignal()

    def stop(_results: list[ToolResultMessage]) -> list[ToolResultAmendment]:
        cancellation.cancel()
        raise AgentCancelled()

    finish = FinishHook()
    events: list[AgentEvent] = []

    def reply(
        _request: GenerationRequest, _signal: CancellationSignal
    ) -> AssistantMessage:
        return AssistantMessage(
            content=[ToolCall(id=CALL_ID, name="cell", arguments={})]
        )

    agent = Agent(
        FakeModelClient(reply),
        generation_context=GenerationContext(flow=LLMFlow.CHAT_RESPONSE),
        tools=[
            AgentTool(
                definition=ToolDefinition(name="cell", description="", parameters={}),
                execute=lambda _invocation: ToolResult(content="running"),
            )
        ],
        before_tool_call=lambda _context: PendingToolInput(
            request_id="permission", prompt="Proceed?", mode=InputMode.EXECUTE
        ),
        on_suspend=stop,
        on_finish=finish,
    )
    coordinator = AgentCoordinator()
    run = agent.start(
        max_steps=2,
        cancellation=cancellation,
        coordinator=coordinator,
        on_event=events.append,
    )
    try:
        assert run.wait_until_settled(3).status == RunStatus.CANCELLED
        assert run.wait_for_idle(3)
        assert len(finish.calls) == 1
        end = next(event for event in events if isinstance(event, AgentEndEvent))
        assert end.outcome == RunStatus.CANCELLED
    finally:
        assert run.wait_for_idle(3)
        assert coordinator.close(3)


def _release_failed() -> ReleaseFailed:
    """A release hook failure, as when before_tool_call raised for a program's
    call."""
    return ReleaseFailed(
        RuntimeError("the policy service is unavailable"),
        [ToolResultAmendment(call_id=CALL_ID, result=ToolResult(content="closed"))],
    )


@pytest.mark.parametrize("stopped", [False, True], ids=["no_stop", "stop"])
def test_a_finish_hook_failure_fails_the_run_unless_the_user_stopped_it(
    stopped: bool,
) -> None:
    hook = FinishHook(error=_release_failed())
    cancellation = CancellationSignal()

    def reply(
        request: GenerationRequest, signal: CancellationSignal
    ) -> AssistantMessage:
        if request.messages and isinstance(request.messages[-1], ToolResultMessage):
            if stopped:
                cancellation.cancel()
                signal.check()
            return _answer()
        return AssistantMessage(
            content=[ToolCall(id=CALL_ID, name="cell", arguments={})]
        )

    agent = _agent(
        reply=reply,
        execute=lambda _invocation: ToolResult(content="running"),
        hook=hook,
    )
    run, events, saved = _run(agent, cancellation=cancellation)
    outcome = RunStatus.CANCELLED if stopped else RunStatus.ERROR
    assert run.status == outcome
    assert len(hook.calls) == 1
    _assert_amended(run, events, saved, outcome)
    failure = saved[0].failure
    if stopped:
        assert failure is None
    else:
        assert failure is not None and failure.kind == RunFailureKind.EXECUTION


@pytest.mark.parametrize("stopped", [False, True], ids=["no_stop", "stop"])
def test_a_suspend_hook_failure_fails_the_run_unless_the_user_stopped_it(
    stopped: bool,
) -> None:
    cancellation = CancellationSignal()

    def suspend(_results: list[ToolResultMessage]) -> list[ToolResultAmendment]:
        if stopped:
            # The user stops the run while the hook runs.
            cancellation.cancel()
        raise _release_failed()

    finish = FinishHook(error=RuntimeError("no amendments"))
    events: list[AgentEvent] = []

    def reply(
        _request: GenerationRequest, _signal: CancellationSignal
    ) -> AssistantMessage:
        return AssistantMessage(
            content=[ToolCall(id=CALL_ID, name="cell", arguments={})]
        )

    agent = Agent(
        FakeModelClient(reply),
        generation_context=GenerationContext(flow=LLMFlow.CHAT_RESPONSE),
        tools=[
            AgentTool(
                definition=ToolDefinition(name="cell", description="", parameters={}),
                execute=lambda _invocation: ToolResult(content="running"),
            )
        ],
        before_tool_call=lambda _context: PendingToolInput(
            request_id="permission", prompt="Proceed?", mode=InputMode.EXECUTE
        ),
        on_suspend=suspend,
        on_finish=finish,
    )
    coordinator = AgentCoordinator()
    run = agent.start(
        max_steps=2,
        cancellation=cancellation,
        coordinator=coordinator,
        on_event=events.append,
    )
    outcome = RunStatus.CANCELLED if stopped else RunStatus.ERROR
    try:
        assert run.wait_until_settled(3).status == outcome
        assert run.wait_for_idle(3)
        end = next(event for event in events if isinstance(event, AgentEndEvent))
        assert end.outcome == outcome
        assert (end.failure is None) == stopped
    finally:
        assert run.wait_for_idle(3)
        assert coordinator.close(3)
