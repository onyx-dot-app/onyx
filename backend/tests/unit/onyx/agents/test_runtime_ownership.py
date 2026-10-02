"""Execution cleanup, restoration, and concurrent result acceptance remain independent."""

import threading
from threading import Event
from unittest.mock import patch

import pytest

from onyx.agents.agent_coordination import (
    AgentCoordinator,
)
from onyx.agents.events import AgentEvent
from onyx.agents.execution_records import ExecutionStatus, RunFailureKind, RunStatus
from onyx.agents.models import (
    AgentInfo,
    PreparedStep,
    RunState,
    StepInput,
    StepRecord,
    StepResult,
)
from onyx.agents.runtime import Agent, Run, RunFailed
from onyx.agents.tools import AgentTool, ToolInvocation, ToolProgress
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
from onyx.utils.threadpool_concurrency import start_thread_future
from tests.unit.onyx.agents.fakes import FakeAgentDirectory, FakeModelClient, run_agent
from tests.unit.onyx.agents.test_child_coordination import parent_agent


def test_first_step_failure_is_recorded_and_agent_can_retry() -> None:
    attempts = 0

    def decide(_state: StepInput) -> PreparedStep:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise RuntimeError("Workspace unavailable")
        return PreparedStep()

    agent = Agent(
        FakeModelClient(
            lambda *_: AssistantMessage(content=[TextContent(text="Recovered")])
        ),
        prepare_step=decide,
    )
    handles: list[Run] = []
    with pytest.raises(RunFailed):
        run_agent(agent, max_steps=1, runs=handles)
    assert handles[0].snapshot().status == RunStatus.ERROR
    assert (
        agent.start(background=False, max_steps=1).result().output.text == "Recovered"
    )
    assert attempts == 2


@pytest.mark.parametrize("in_discovery", [False, True])
def test_archive_lookup_does_not_restore_an_agent(in_discovery: bool) -> None:
    resolutions: list[str] = []
    archived = RunState(
        agent_id="research",
        run_id="saved",
        status=RunStatus.COMPLETE,
        steps=[
            StepRecord(
                message=AssistantMessage(content=[TextContent(text="Saved")]),
                generation_status=ExecutionStatus.COMPLETE,
                tools={},
            )
        ],
    )

    def restore(agent_id: str, _parent_id: str) -> Agent:
        resolutions.append(agent_id)
        return Agent(
            FakeModelClient(
                lambda *_: AssistantMessage(content=[TextContent(text="New")])
            ),
            agent_id=agent_id,
            previous_run_id=archived.run_id,
        )

    def inspect(invocation: ToolInvocation) -> ToolResult:
        discovered = invocation.agents.discovery()
        assert [info.latest_run_id for info in discovered] == (
            ["saved"] if in_discovery else []
        )
        saved = invocation.agents.wait_run("saved", timeout=2)
        assert saved is not None and saved.output.text == "Saved"
        assert resolutions == []
        next_id = invocation.agents.start_run("research", messages=[], max_steps=1)
        result = invocation.agents.wait_run(next_id, timeout=2)
        assert result is not None and result.output.text == "New"
        assert resolutions == ["research"]
        return ToolResult(content="Done")

    parent = parent_agent(inspect)
    info = AgentInfo(
        id="research",
        path="/root/research",
        parent_id=parent.id,
        description="Research",
        restoration_config=None,
        latest_run_id="saved",
        status=RunStatus.COMPLETE,
    )
    coordinator = AgentCoordinator(
        agents=[info] if in_discovery else [],
        directory=FakeAgentDirectory(
            lookup_agent=lambda agent_id, parent_id: (
                info if agent_id == info.id and parent_id == parent.id else None
            ),
            restore_agent=restore,
            read_run=lambda run_id, parent_id: (
                archived if run_id == "saved" and parent_id == parent.id else None
            ),
        ),
    )
    handles: list[Run] = []
    run_agent(parent, max_steps=2, coordinator=coordinator, runs=handles)
    assert handles[0].snapshot().child_runs[0].previous_run_id == "saved"


@pytest.mark.parametrize("kind", ["model", "tool"])
def test_cancelled_work_remains_tracked_without_reserving_agent(kind: str) -> None:
    entered, release = Event(), Event()
    effects: list[str] = []

    def generate(
        _request: GenerationRequest, _signal: CancellationSignal
    ) -> AssistantMessage:
        if entered.is_set():
            return AssistantMessage(content=[TextContent(text="New answer")])
        entered.set()
        assert release.wait(5)
        return AssistantMessage(content=[TextContent(text="Late")])

    def tool(_invocation: ToolInvocation) -> ToolResult:
        entered.set()
        assert release.wait(5)
        effects.append("Old side effect")
        _invocation.update(ToolProgress(content="Late"))
        return ToolResult(content="Late")

    agent = (
        Agent(FakeModelClient(generate))
        if kind == "model"
        else Agent(
            FakeModelClient(
                lambda *_: AssistantMessage(
                    content=[TextContent(text="New answer")]
                    if entered.is_set()
                    else [ToolCall(id="blocked", name="blocked", arguments={})]
                )
            ),
            tools=[
                AgentTool(
                    definition=ToolDefinition(
                        name="blocked", description="Wait", parameters={}
                    ),
                    execute=tool,
                )
            ],
        )
    )

    def exercise() -> None:
        coordinator = AgentCoordinator()
        run = agent.start(max_steps=1, coordinator=coordinator)
        try:
            assert entered.wait(2)
            run.cancel()
            with pytest.raises(AgentCancelled):
                run.result(timeout=3)
            assert not run.wait_for_idle(timeout=0.01)
            run._reusable.result(timeout=2)
            assert coordinator.active_run(agent.id) is None
            snapshot = run.snapshot()
            following = agent.start(max_steps=1, coordinator=coordinator)
            assert following.result(timeout=2).output.text == "New answer"
            assert following.wait_for_idle(timeout=2)
            assert not run.wait_for_idle(timeout=0)
            assert not effects
            assert not coordinator.close(timeout=0.01)
        finally:
            release.set()
        assert run.wait_for_idle(timeout=3)
        assert coordinator.close(timeout=3)
        assert run.snapshot() == snapshot
        assert agent.state.messages[-1].text == "New answer"
        assert effects == (["Old side effect"] if kind == "tool" else [])

    exercise()


def test_generation_deadline_retains_worker_and_rejects_late_output() -> None:
    entered, release = Event(), Event()

    def generate(
        _request: GenerationRequest, _signal: CancellationSignal
    ) -> AssistantMessage:
        entered.set()
        assert release.wait(5)
        return AssistantMessage(content=[TextContent(text="Late")])

    agent = Agent(
        FakeModelClient(generate),
        generation_context=GenerationContext(total_timeout_s=0.1),
    )
    run = agent.start(max_steps=1)
    try:
        assert entered.wait(2)
        with pytest.raises(RunFailed):
            run.result(timeout=2)
        snapshot = run.snapshot()
        assert snapshot.status == RunStatus.ERROR
        assert snapshot.failure is not None
        assert snapshot.failure.kind == RunFailureKind.LLM_TIMEOUT
        assert not run.wait_for_idle(0)
        run._reusable.result(timeout=2)
    finally:
        release.set()
    assert run.wait_for_idle(2)
    assert run.snapshot() == snapshot


def test_archive_timeout_does_not_cancel_parent_or_release_its_work_early() -> None:
    entered, release, finished = Event(), Event(), Event()

    def read(_run_id: str, _parent_id: str) -> RunState | None:
        entered.set()
        try:
            assert release.wait(3)
            return None
        finally:
            finished.set()

    def inspect(invocation: ToolInvocation) -> ToolResult:
        try:
            assert invocation.agents.wait_run("saved", timeout=0) is None
            assert not entered.is_set()
            assert invocation.agents.wait_run("saved", timeout=0.05) is None
            assert entered.is_set() and not finished.is_set()
            assert not invocation.cancellation.cancelled
        finally:
            release.set()
        return ToolResult(content="timed out")

    parent = parent_agent(inspect)

    run_agent(
        parent,
        max_steps=2,
        coordinator=AgentCoordinator(directory=FakeAgentDirectory(read_run=read)),
    )
    assert finished.is_set()


def test_loaded_agent_bound_is_shared_across_parent_runs() -> None:
    def spawn(invocation: ToolInvocation) -> ToolResult:
        invocation.agents.spawn_agent(
            Agent(
                FakeModelClient(
                    lambda *_: AssistantMessage(content=[TextContent(text="Done")])
                )
            ),
            name="duplicate label",
            description="Task",
            messages=[],
            max_steps=1,
        )
        return ToolResult(content="Done")

    def exercise() -> None:
        parent = parent_agent(spawn)
        coordinator = AgentCoordinator()
        first = parent.start(max_steps=2, coordinator=coordinator)
        first.result()
        assert first.wait_for_idle(timeout=3)
        second = parent.start(max_steps=2, coordinator=coordinator)
        second.result()
        assert second.wait_for_idle(timeout=3)
        errors = [
            message
            for message in second.snapshot().messages
            if isinstance(message, ToolResultMessage) and message.is_error
        ]
        assert len(errors) == 1
        assert "loaded agent limit exceeded" in errors[0].content
        assert len(coordinator.discovery(parent.id)) == 1
        assert coordinator.close(timeout=3)

    with patch("onyx.agents.agent_coordination.MAX_LOADED_AGENTS", 1):
        exercise()


@pytest.mark.parametrize("cancelled", [False, True])
def test_parallel_result_survives_another_tool_failure(cancelled: bool) -> None:
    accepted = Event()

    def execute(invocation: ToolInvocation) -> ToolResult:
        if invocation.call_id == "first":
            assert accepted.wait(3)
            if cancelled:
                raise AgentCancelled()
            raise RuntimeError("First tool failed")
        return ToolResult(content="Completed side effect")

    def observe(event: AgentEvent) -> None:
        if event.type == "tool_update" and event.tool_call.id == "second":
            accepted.set()

    agent = Agent(
        FakeModelClient(
            lambda *_: AssistantMessage(
                content=[
                    ToolCall(id=name, name="work", arguments={})
                    for name in ["first", "second"]
                ]
            )
        ),
        tools=[
            AgentTool(
                definition=ToolDefinition(
                    name="work", description="Work", parameters={}
                ),
                execute=execute,
            )
        ],
    )
    handles: list[Run] = []
    if cancelled:
        with pytest.raises(AgentCancelled):
            run_agent(agent, max_steps=1, runs=handles, listener=observe)
    else:
        run_agent(agent, max_steps=1, runs=handles, listener=observe)
    snapshot = handles[0].snapshot()
    results = [
        message
        for message in snapshot.messages
        if isinstance(message, ToolResultMessage)
    ]
    assert [
        (result.tool_call_id, result.text) for result in results if not result.is_error
    ] == [("second", "Completed side effect")]
    if not cancelled:
        assert snapshot.steps[0].tools["first"].status == "error"
        assert any(
            result.is_error and "First tool failed" in result.text for result in results
        )
    assert snapshot.steps[0].tools["second"].status == RunStatus.COMPLETE


@pytest.mark.parametrize("cancel_child", [False, True])
def test_timed_out_wait_does_not_observe_a_later_child_failure(
    cancel_child: bool,
) -> None:
    release = Event()
    child_started = Event()

    def fail(
        _request: GenerationRequest, _signal: CancellationSignal
    ) -> AssistantMessage:
        child_started.set()
        assert release.wait(3)
        raise ValueError("Child failed")

    def delegate(invocation: ToolInvocation) -> ToolResult:
        submission = invocation.agents.spawn_agent(
            Agent(FakeModelClient(fail)),
            name="child",
            description="Task",
            messages=[],
            max_steps=1,
        )
        assert invocation.agents.wait_run(submission.run_id, timeout=0) is None
        assert child_started.wait(3)
        if cancel_child:
            invocation.agents.cancel_run(submission.run_id)
        release.set()
        return ToolResult(content="parent continues")

    handles: list[Run] = []
    parent = parent_agent(delegate)
    try:
        if cancel_child:
            result = run_agent(
                parent, max_steps=2, runs=handles, coordinator=AgentCoordinator()
            )
            assert result.output.text == "first finished"
            assert handles[0].snapshot().child_runs[0].status == RunStatus.CANCELLED
        else:
            with pytest.raises(RunFailed):
                run_agent(
                    parent, max_steps=2, runs=handles, coordinator=AgentCoordinator()
                )
            assert handles[0].snapshot().child_runs[0].status == RunStatus.ERROR
    finally:
        release.set()


def test_tool_timeout_cancels_the_tool_and_saves_failure() -> None:
    cleaned_up = Event()

    def blocked(invocation: ToolInvocation) -> ToolResult:
        try:
            cancelled = threading.Event()
            with invocation.cancellation.on_cancel(cancelled.set):
                assert cancelled.wait(3)
                invocation.cancellation.check()
            return ToolResult(content="Unreachable")
        finally:
            cleaned_up.set()

    handles: list[Run] = []
    with patch("onyx.agents.runtime.OPERATION_TIMEOUT_SECONDS", 0.1):
        with pytest.raises(RunFailed):
            run_agent(parent_agent(blocked), max_steps=2, runs=handles)
    assert cleaned_up.is_set()
    assert handles[0].snapshot().status == RunStatus.ERROR


def test_child_cancel_does_not_need_a_free_blocking_worker() -> None:
    entered, release = Event(), Event()

    def blocked(
        _request: GenerationRequest, signal: CancellationSignal
    ) -> AssistantMessage:
        entered.set()
        with signal.on_cancel(release.set):
            assert release.wait(5)
        signal.check()
        return AssistantMessage(content=[TextContent(text="Late")])

    def delegate(invocation: ToolInvocation) -> ToolResult:
        submitted = invocation.agents.spawn_agent(
            Agent(FakeModelClient(blocked)),
            name="blocked",
            description="Task",
            messages=[],
            max_steps=1,
        )
        try:
            assert entered.wait(2)
            assert invocation.agents.wait_run(submitted.run_id, timeout=0) is None
            invocation.agents.cancel_run(submitted.run_id)
            with pytest.raises(AgentCancelled):
                invocation.agents.wait_run(submitted.run_id, timeout=1)
        finally:
            release.set()
        return ToolResult(content="Done")

    parent = parent_agent(delegate)

    assert (
        run_agent(parent, max_steps=2, coordinator=AgentCoordinator()).output.text
        == "first finished"
    )


def test_child_restart_does_not_wait_for_its_timed_out_archive_read() -> None:
    entered, release = Event(), Event()
    calls = 0

    def read(_run_id: str, _parent_id: str) -> RunState | None:
        entered.set()
        assert release.wait(5)
        return None

    def inspect(invocation: ToolInvocation) -> ToolResult:
        nonlocal calls
        calls += 1
        if calls == 1:
            assert invocation.agents.wait_run("archived", timeout=0.05) is None
        return ToolResult(content="Done")

    child = parent_agent(inspect)

    def delegate(invocation: ToolInvocation) -> ToolResult:
        submitted = invocation.agents.spawn_agent(
            child, name="research", description="Task", messages=[], max_steps=2
        )
        assert invocation.agents.wait_run(submitted.run_id, timeout=2) is not None
        assert entered.is_set()
        restarting = start_thread_future(
            name="test-restart",
            operation=lambda: invocation.agents.start_run(
                child.id, messages=[], max_steps=2
            ),
        )
        run_id = restarting.result(2)
        assert invocation.agents.wait_run(run_id, timeout=2) is not None
        assert not release.is_set()
        release.set()
        return ToolResult(content="Done")

    try:
        run_agent(
            parent_agent(delegate),
            max_steps=2,
            coordinator=AgentCoordinator(directory=FakeAgentDirectory(read_run=read)),
        )
    finally:
        release.set()
    assert calls == 2


@pytest.mark.parametrize("should_continue", [False, True])
def test_completed_step_decides_completion_before_budget_limit(
    should_continue: bool,
) -> None:
    prepared: list[int] = []
    completed: list[int] = []

    def prepare(state: StepInput) -> PreparedStep:
        prepared.append(state.step.index)
        return PreparedStep()

    def after_step(result: StepResult) -> bool:
        completed.append(result.step.index)
        return should_continue

    agent = Agent(
        FakeModelClient(
            lambda *_: AssistantMessage(content=[TextContent(text="Answer")])
        ),
        prepare_step=prepare,
        after_step=after_step,
    )
    run = agent.start(max_steps=1)
    result = run.result()
    assert run.wait_for_idle(2)
    assert prepared == [0]
    assert completed == [0]
    assert result.stop_reason == (
        RunStatus.LIMIT if should_continue else RunStatus.COMPLETE
    )


def test_final_validation_failure_preserves_completed_output() -> None:
    def validate(_result: StepResult) -> bool:
        raise ValueError("Missing required section")

    run = Agent(
        FakeModelClient(
            lambda *_: AssistantMessage(content=[TextContent(text="Partial answer")])
        ),
        after_step=validate,
    ).start(max_steps=1)
    with pytest.raises(RunFailed):
        run.result()
    assert run.wait_for_idle(2)
    assert run.snapshot().status == RunStatus.ERROR
    assert run.snapshot().messages[-1].text == "Partial answer"


@pytest.mark.parametrize("coordinated", [False, True])
@pytest.mark.parametrize("timeout", [False, True])
def test_new_run_does_not_wait_for_discarded_generation(
    coordinated: bool, timeout: bool
) -> None:
    entered, release = Event(), Event()
    calls = 0

    def generate(
        _request: GenerationRequest, _signal: CancellationSignal
    ) -> AssistantMessage:
        nonlocal calls
        calls += 1
        if calls == 1:
            entered.set()
            assert release.wait(5)
            return AssistantMessage(content=[TextContent(text="Discarded")])
        return AssistantMessage(content=[TextContent(text="New answer")])

    coordinator = AgentCoordinator() if coordinated else None
    agent = Agent(
        FakeModelClient(generate),
        generation_context=GenerationContext(total_timeout_s=0.1 if timeout else None),
    )
    old = agent.start(max_steps=1, coordinator=coordinator)
    try:
        assert entered.wait(2)
        if not timeout:
            old.cancel()
        with pytest.raises(RunFailed if timeout else AgentCancelled):
            old.result(timeout=2)
        old._reusable.result(timeout=2)
        saved = old.snapshot()
        assert not old.wait_for_idle(timeout=0)
        new = agent.start(max_steps=1, coordinator=coordinator)
        assert new.result(timeout=2).output.text == "New answer"
        assert new.wait_for_idle(2)
        assert new.previous_run_id == old.id
        if coordinator is not None:
            assert not coordinator.close(timeout=0)
    finally:
        release.set()
    assert old.wait_for_idle(2)
    assert old.snapshot() == saved
    assert agent.state.messages[-1].text == "New answer"
    if coordinator is not None:
        assert coordinator.close(timeout=2)
