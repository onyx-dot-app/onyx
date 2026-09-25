import threading
import time
from concurrent.futures import ThreadPoolExecutor

import pytest

from onyx.agents.agent_coordination import AgentCoordinator
from onyx.agents.events import AgentEvent
from onyx.agents.runtime import Agent, Run, RunFailed
from onyx.agents.tools import AgentTool, ToolInvocation
from onyx.llm.cancellation import (
    AgentCancelled,
    CancellationSignal,
    cancellation_scope,
    current_cancellation,
)
from onyx.llm.models import (
    AssistantMessage,
    GenerationRequest,
    TextContent,
    ToolCall,
    ToolResult,
    ToolResultMessage,
)
from tests.unit.onyx.agents.fakes import FakeModelClient, run_agent


def test_nested_child_runs_complete_without_parent_deadlock() -> None:

    def nested(depth: int) -> Agent:
        if depth == 0:
            return Agent(
                FakeModelClient(
                    lambda *_: AssistantMessage(content=[TextContent(text="leaf")])
                )
            )

        def execute(invocation: ToolInvocation) -> ToolResult:
            submission = invocation.agents.spawn_agent(
                nested(depth - 1),
                name="child",
                description="Run child work",
                max_steps=2,
                messages=[],
            )
            child = invocation.agents.wait_run(submission.run_id)
            assert child is not None
            return ToolResult(content=child.output.text)

        def reply(
            request: GenerationRequest, _signal: CancellationSignal
        ) -> AssistantMessage:
            if request.messages and isinstance(request.messages[-1], ToolResultMessage):
                return AssistantMessage(
                    content=[TextContent(text=request.messages[-1].text)]
                )
            return AssistantMessage(
                content=[ToolCall(id="child", name="child", arguments={})]
            )

        return Agent(
            FakeModelClient(reply),
            tools=[
                AgentTool(
                    name="child",
                    description="",
                    parameters={},
                    execute=execute,
                )
            ],
        )

    root = nested(3)
    events: list[AgentEvent] = []
    runs: list[Run] = []
    assert (
        run_agent(
            root,
            max_steps=2,
            runs=runs,
            listener=events.append,
            coordinator=AgentCoordinator(),
        ).output.text
        == "leaf"
    )
    snapshot = runs[-1].snapshot()
    assert snapshot is not None
    assert len([event for event in events if event.type == "agent_start"]) == 4
    assert [
        event.progress.content for event in events if event.type == "tool_update"
    ] == ["leaf"] * 3
    for _ in range(3):
        assert len(snapshot.child_runs) == 1
        child = snapshot.child_runs[0]
        assert child.parent_run_id == snapshot.run_id
        assert child.status == "complete"
        end_index = next(
            index
            for index, event in enumerate(events)
            if event.type == "agent_end" and event.run_id == child.run_id
        )
        tool_end_index = next(
            index
            for index, event in enumerate(events)
            if event.type == "tool_end" and event.run_id == snapshot.run_id
        )
        assert end_index < tool_end_index
        assert events[end_index].parent_run_id == snapshot.run_id
        assert events[end_index].parent_tool_call_id == "child"
        snapshot = child


def test_cancelled_child_does_not_block_independent_parent_work() -> None:

    entered = threading.Event()
    release = threading.Event()
    recovering = threading.Event()
    replacement_started = threading.Event()
    cancel_child = threading.Event()

    def blocked_tool(_invocation: ToolInvocation) -> ToolResult:
        entered.set()
        assert release.wait(5)
        return ToolResult(content="late")

    child = Agent(
        FakeModelClient(
            lambda *_: AssistantMessage(
                content=[ToolCall(id="block", name="block", arguments={})]
            )
        ),
        tools=[
            AgentTool(name="block", description="", parameters={}, execute=blocked_tool)
        ],
    )

    def execute(invocation: ToolInvocation) -> ToolResult:
        try:
            submission = invocation.agents.spawn_agent(
                child,
                name="child",
                description="Run child work",
                max_steps=1,
                messages=[],
            )
            while not cancel_child.is_set():
                time.sleep(0.01)
            invocation.agents.cancel_run(submission.run_id)
            invocation.agents.wait_run(submission.run_id)
        except AgentCancelled:
            recovering.set()
        replacement_started.set()
        return ToolResult(content="recovered")

    def reply(
        request: GenerationRequest, _signal: CancellationSignal
    ) -> AssistantMessage:
        if request.messages and isinstance(request.messages[-1], ToolResultMessage):
            return AssistantMessage(
                content=[TextContent(text=request.messages[-1].text)]
            )
        return AssistantMessage(
            content=[ToolCall(id="child", name="child", arguments={})]
        )

    root = Agent(
        FakeModelClient(reply),
        tools=[AgentTool(name="child", description="", parameters={}, execute=execute)],
    )
    with ThreadPoolExecutor(max_workers=1) as workers:
        result = workers.submit(
            lambda: run_agent(root, max_steps=2, coordinator=AgentCoordinator())
        )
        try:
            assert entered.wait(2)
            cancel_child.set()
            assert recovering.wait(2)
            assert replacement_started.wait(1)
        finally:
            release.set()
        assert result.result(timeout=2).output.text == "recovered"
    assert replacement_started.is_set()


def test_stop_cancels_a_cooperative_tool_wait() -> None:
    entered = threading.Event()
    exited = threading.Event()

    def execute(invocation: ToolInvocation) -> ToolResult:
        entered.set()
        try:
            cancelled = threading.Event()
            with invocation.cancellation.on_cancel(cancelled.set):
                assert cancelled.wait(3)
                invocation.cancellation.check()
        finally:
            exited.set()
        raise AssertionError("The wait must be cancelled")

    root = Agent(
        FakeModelClient(
            lambda *_: AssistantMessage(
                content=[ToolCall(id="wait", name="wait", arguments={})]
            )
        ),
        tools=[AgentTool(name="wait", description="", parameters={}, execute=execute)],
    )
    signal = CancellationSignal()
    with ThreadPoolExecutor(max_workers=1) as workers:
        result = workers.submit(
            lambda: run_agent(root, max_steps=1, cancellation=signal)
        )
        assert entered.wait(2)
        signal.cancel()
        with pytest.raises(AgentCancelled):
            result.result(timeout=2)
    assert exited.is_set()


def test_parallel_failure_cancels_a_blocked_earlier_call() -> None:
    entered = threading.Event()
    release = threading.Event()
    failed = ValueError("Tool implementation defect")

    def execute(invocation: ToolInvocation) -> ToolResult:
        if invocation.call_id == "blocked":

            def block() -> ToolResult:
                entered.set()
                assert release.wait(5)
                return ToolResult(content="late")

            return block()
        while not entered.is_set():
            time.sleep(0)
        raise failed

    root = Agent(
        FakeModelClient(
            lambda *_: AssistantMessage(
                content=[
                    ToolCall(id="blocked", name="work", arguments={}),
                    ToolCall(id="fails", name="work", arguments={}),
                ]
            )
        ),
        tools=[AgentTool(name="work", description="", parameters={}, execute=execute)],
    )

    def exercise() -> None:
        run = root.start(max_steps=1)
        try:
            assert entered.wait(2)
            with pytest.raises(RunFailed):
                run.result(timeout=2)
            assert not run.wait_for_idle(timeout=0)
        finally:
            release.set()
            assert run.wait_for_idle(timeout=2)
        snapshot = run.snapshot()
        assert snapshot.status == "error"
        assert all(
            step.generation_status != "running"
            and all(tool.status != "running" for tool in step.tools.values())
            for step in snapshot.steps
        )

    exercise()


@pytest.mark.parametrize("child_fails", [False, True])
def test_parent_completion_joins_unawaited_child_runs(child_fails: bool) -> None:
    child_error = ValueError("child failed")
    child_finished = threading.Event()

    def child_reply(
        _request: GenerationRequest, _signal: CancellationSignal
    ) -> AssistantMessage:
        child_finished.set()
        if child_fails:
            raise child_error
        return AssistantMessage(content=[TextContent(text="child complete")])

    child = Agent(FakeModelClient(child_reply))

    def execute(invocation: ToolInvocation) -> ToolResult:
        invocation.agents.spawn_agent(
            child, name="child", description="Run child work", max_steps=1, messages=[]
        )
        return ToolResult(content="parent tool complete")

    parent = Agent(
        FakeModelClient(
            lambda request, _signal: AssistantMessage(
                content=[TextContent(text="parent complete")]
                if request.messages
                else [ToolCall(id="child", name="child", arguments={})]
            )
        ),
        tools=[AgentTool(name="child", description="", parameters={}, execute=execute)],
    )
    runs: list[Run] = []
    coordinator = AgentCoordinator()
    if child_fails:
        with pytest.raises(RunFailed):
            run_agent(parent, max_steps=2, runs=runs, coordinator=coordinator)
    else:
        run_agent(parent, max_steps=2, runs=runs, coordinator=coordinator)
    assert child_finished.is_set()
    snapshot = runs[-1].snapshot()
    assert snapshot is not None
    assert snapshot.child_runs[0].status == ("error" if child_fails else "complete")
    assert snapshot.steps[-1].generation_status == "complete"


def test_cancelled_tool_cleanup_uses_its_own_live_signal() -> None:
    started = threading.Event()
    cleaned = threading.Event()

    def clean_up() -> None:
        signal = current_cancellation()
        assert signal is not None
        signal.check()
        cleaned.set()

    def execute(invocation: ToolInvocation) -> ToolResult:
        try:
            started.set()
            cancelled = threading.Event()
            with invocation.cancellation.on_cancel(cancelled.set):
                assert cancelled.wait(3)
                invocation.cancellation.check()
            raise AssertionError("tool must cancel")
        finally:
            with cancellation_scope(CancellationSignal()):
                clean_up()

    agent = Agent(
        FakeModelClient(
            lambda *_: AssistantMessage(
                content=[ToolCall(id="cleanup", name="cleanup", arguments={})]
            )
        ),
        tools=[
            AgentTool(name="cleanup", description="", parameters={}, execute=execute)
        ],
    )
    signal = CancellationSignal()
    with ThreadPoolExecutor(max_workers=1) as executor:
        task = executor.submit(
            lambda: run_agent(agent, max_steps=1, cancellation=signal)
        )
        try:
            assert started.wait(3)
            signal.cancel()
            with pytest.raises(AgentCancelled):
                task.result(timeout=3)
            assert cleaned.is_set()
        finally:
            signal.cancel()


def test_tool_failure_logs_unobserved_child_failure(
    caplog: pytest.LogCaptureFixture,
) -> None:
    child_error = ValueError("child failure")
    tool_error = RuntimeError("parent tool failure")
    child_started = threading.Event()
    child_completed = threading.Event()

    def fail_child(
        _request: GenerationRequest, _signal: CancellationSignal
    ) -> AssistantMessage:
        child_started.set()
        raise child_error

    child = Agent(FakeModelClient(fail_child))

    def execute(invocation: ToolInvocation) -> ToolResult:
        invocation.agents.spawn_agent(
            child, name="child", description="Run child work", max_steps=1, messages=[]
        )
        assert child_completed.wait(2)
        raise tool_error

    parent = Agent(
        FakeModelClient(
            lambda *_: AssistantMessage(
                content=[ToolCall(id="child", name="child", arguments={})]
            )
        ),
        tools=[AgentTool(name="child", description="", parameters={}, execute=execute)],
    )

    def on_event(event: AgentEvent) -> None:
        if event.type == "agent_end" and event.agent_id == child.id:
            child_completed.set()

    with pytest.raises(RunFailed):
        run_agent(
            parent, max_steps=1, coordinator=AgentCoordinator(), listener=on_event
        )
    failures = [
        record
        for record in caplog.records
        if record.exc_info is not None and record.exc_info[1] is child_error
    ]
    assert len(failures) == 1
    assert child_completed.is_set()
