"""The run finish hook sets the final results of tool calls for every outcome."""

import threading
import time
from collections.abc import Callable
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
    RunFailureKind,
    RunState,
    RunStatus,
    ToolResultAmendment,
)
from onyx.agents.runtime import Agent, Run
from onyx.agents.tools import AgentTool, ToolInvocation
from onyx.llm.cancellation import AgentCancelled, CancellationSignal
from onyx.llm.interfaces import GenerationContext
from onyx.llm.models import (
    AssistantMessage,
    GenerationRequest,
    TextContent,
    ToolCall,
    ToolDefinition,
    ToolResult,
    ToolResultMessage,
)
from onyx.tracing.flows import LLMFlow
from tests.unit.onyx.agents.fakes import FakeModelClient, FakeRunStore

CALL_ID = "cell"


class FinishHook:
    """Records each call and amends the first recorded tool result."""

    def __init__(
        self,
        *,
        fail: bool = False,
        call_id: str = CALL_ID,
        wait_until: datetime | None = None,
    ) -> None:
        self.calls: list[list[ToolResultMessage]] = []
        self.fail = fail
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
        if self.fail:
            raise RuntimeError("finish hook failed")
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
    hook = FinishHook(fail=True)
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
