"""Children share execution semantics and retain identity across parent runs."""

import gc
import threading
import time
import weakref
from collections.abc import Callable, Generator
from concurrent.futures import Future
from contextvars import ContextVar
from unittest.mock import patch

import pytest

from onyx.agents.agent_coordination import (
    AgentCoordinator,
    RunCoordination,
)
from onyx.agents.events import AgentEvent, MessageEndEvent
from onyx.agents.execution_records import RunFailureKind, RunStatus
from onyx.agents.models import AgentInfo, PreparedStep, RunState, StepInput
from onyx.agents.runtime import Agent, Run, RunFailed, RunNotTransferable, RunReleased
from onyx.agents.tools import (
    AgentControl,
    AgentTool,
    ChildRunWait,
    HumanToolAnswer,
    InputDecision,
    InputMode,
    PendingToolInput,
    SpawnResult,
    ToolInvocation,
)
from onyx.chat.checkpoint import CheckpointBinding
from onyx.chat.presentation import project_response
from onyx.llm.cancellation import AgentCancelled, CancellationSignal
from onyx.llm.exceptions import LLMTimeoutError
from onyx.llm.interfaces import GenerationContext
from onyx.llm.models import (
    AssistantMessage,
    GenerationDoneEvent,
    GenerationEvent,
    GenerationRequest,
    TextContent,
    TextDeltaEvent,
    ToolCall,
    ToolResult,
    UserMessage,
)
from onyx.utils.threadpool_concurrency import start_thread_future
from tests.unit.onyx.agents.checkpoint_storage import CheckpointStorage
from tests.unit.onyx.agents.fakes import (
    FakeAgentDirectory,
    FakeModelClient,
    FakeRunOwnership,
    FakeRunStore,
    run_agent,
)


def parent_agent(
    execute: Callable[[ToolInvocation], ToolResult], *, agent_id: str | None = None
) -> Agent:
    responses = iter(
        [
            AssistantMessage(
                content=[ToolCall(id="first", name="coordinate", arguments={})]
            ),
            AssistantMessage(content=[TextContent(text="first finished")]),
            AssistantMessage(
                content=[ToolCall(id="second", name="coordinate", arguments={})]
            ),
            AssistantMessage(content=[TextContent(text="second finished")]),
        ]
    )
    return Agent(
        FakeModelClient(lambda *_: next(responses)),
        agent_id=agent_id,
        tools=[
            AgentTool(
                name="coordinate",
                description="Coordinate child work",
                parameters={},
                execute=execute,
            )
        ],
    )


@pytest.mark.parametrize(
    "failure,kind",
    [
        (LLMTimeoutError("private input"), RunFailureKind.LLM_TIMEOUT),
        (ValueError("private input"), RunFailureKind.EXECUTION),
    ],
)
def test_saved_failure_matches_live_failure(
    failure: Exception, kind: RunFailureKind
) -> None:
    def fail(
        _request: GenerationRequest, _signal: CancellationSignal
    ) -> AssistantMessage:
        raise failure

    child = Agent(FakeModelClient(fail))
    handles = []
    with pytest.raises(RunFailed) as live:
        run_agent(child, max_steps=1, runs=handles)
    transcript = handles[0].snapshot()
    assert live.value.failure.kind == kind
    assert "private input" not in transcript.model_dump_json()

    def retrieve(invocation: ToolInvocation) -> ToolResult:
        with pytest.raises(RunFailed) as saved:
            invocation.agents.wait_run(transcript.run_id, timeout=2)
        assert saved.value.failure == live.value.failure
        return ToolResult(content="inspected")

    parent = parent_agent(retrieve)
    coordinator = AgentCoordinator(
        agents=[
            AgentInfo(
                id=child.id,
                path="/root/research",
                parent_id=parent.id,
                description="Research",
                restoration_config=None,
            )
        ],
        directory=FakeAgentDirectory(read_run=lambda *_: transcript),
    )
    run_agent(parent, max_steps=2, coordinator=coordinator)


def test_child_reuse_preserves_old_records_and_rejects_stale_tool_capabilities() -> (
    None
):
    requests: list[list[str]] = []
    budgets: list[int] = []
    spawned: SpawnResult | None = None
    prior_control: AgentControl | None = None
    initial = UserMessage(content="first task")

    def generate(
        request: GenerationRequest, _signal: CancellationSignal
    ) -> AssistantMessage:
        requests.append([message.text for message in request.messages])
        return AssistantMessage(content=[TextContent(text=f"answer {len(requests)}")])

    def prepare(state: StepInput) -> PreparedStep:
        if state.step.index == 0:
            budgets.append(state.step.limit)
        return PreparedStep()

    child = Agent(FakeModelClient(generate), prepare_step=prepare)

    def coordinate(invocation: ToolInvocation) -> ToolResult:
        nonlocal spawned, prior_control
        if spawned is None:
            prior_control = invocation.agents
            spawned = invocation.agents.spawn_agent(
                child,
                name="research",
                description="Facts",
                messages=[initial],
                max_steps=2,
            )
            initial.content = "changed caller copy"
            result = invocation.agents.wait_run(spawned.run_id, timeout=3)
            assert result is not None and result.output.text == "answer 1"
            result.output.content.clear()
        else:
            assert prior_control is not None
            with pytest.raises(RuntimeError):
                prior_control.start_run(child.id, messages=[], max_steps=1)
            previous = invocation.agents.wait_run(spawned.run_id, timeout=0)
            assert previous is not None and previous.output.text == "answer 1"
            next_id = invocation.agents.start_run(
                child.id, messages=[UserMessage(content="second task")], max_steps=1
            )
            result = invocation.agents.wait_run(next_id, timeout=3)
            assert result is not None and result.output.text == "answer 2"
        return ToolResult(content="child finished")

    def exercise() -> None:
        parent = parent_agent(coordinate)
        coordinator = AgentCoordinator()
        first = parent.start(max_steps=2, coordinator=coordinator)
        first.result()
        assert first.wait_for_idle(timeout=3)
        before = first.snapshot()
        second = parent.start(max_steps=2, coordinator=coordinator)
        second.result()
        assert second.wait_for_idle(timeout=3)
        assert first.snapshot() == before
        after = second.snapshot()
        assert before.child_runs[0].input_messages[0].text == "first task"
        assert after.child_runs[0].input_messages[0].text == "second task"
        assert after.child_runs[0].previous_run_id == before.child_runs[0].run_id
        assert before.child_runs[0].parent_tool_call_id == "first"
        assert after.child_runs[0].parent_message_id == f"{second.id}:0"
        assert coordinator.discovery(parent.id)[0].id == child.id
        assert coordinator.close(timeout=3)

    exercise()
    assert budgets == [2, 1]
    assert requests == [["first task"], ["first task", "answer 1", "second task"]]


def test_busy_child_rejects_new_input_and_unknown_identity() -> None:
    entered, release = threading.Event(), threading.Event()
    requests: list[list[str]] = []

    def generate(
        request: GenerationRequest, signal: CancellationSignal
    ) -> AssistantMessage:
        requests.append([message.text for message in request.messages])
        entered.set()
        while not release.wait(0.01):
            signal.check()
        return AssistantMessage(content=[TextContent(text="finished")])

    child = Agent(FakeModelClient(generate))

    def coordinate(invocation: ToolInvocation) -> ToolResult:
        spawned = invocation.agents.spawn_agent(
            child,
            name="research",
            description="Facts",
            messages=[UserMessage(content="accepted")],
            max_steps=1,
        )
        assert entered.wait(2)
        assert invocation.agents.wait_run(spawned.run_id, timeout=0) is None
        with pytest.raises(RuntimeError):
            invocation.agents.start_run(
                child.id, messages=[UserMessage(content="rejected")], max_steps=1
            )
        with pytest.raises(ValueError):
            invocation.agents.start_run("unknown", messages=[], max_steps=1)
        release.set()
        assert invocation.agents.wait_run(spawned.run_id, timeout=3) is not None
        return ToolResult(content="done")

    parent = parent_agent(coordinate)

    try:
        run_agent(parent, max_steps=2, coordinator=AgentCoordinator())
    finally:
        release.set()
    assert requests == [["accepted"]]


def test_cancelled_parent_keeps_child_identity_for_later_turn() -> None:
    entered = threading.Event()
    spawned: SpawnResult | None = None

    def reply(
        request: GenerationRequest, signal: CancellationSignal
    ) -> AssistantMessage:
        if request.messages[-1].text == "first":
            entered.set()
            while not signal.cancelled:
                threading.Event().wait(0.01)
            signal.check()
        return AssistantMessage(content=[TextContent(text="replacement")])

    child = Agent(FakeModelClient(reply))

    def coordinate(invocation: ToolInvocation) -> ToolResult:
        nonlocal spawned
        if spawned is None:
            spawned = invocation.agents.spawn_agent(
                child,
                name="same name",
                description="Facts",
                messages=[UserMessage(content="first")],
                max_steps=1,
            )
            invocation.agents.wait_run(spawned.run_id, timeout=3)
        else:
            next_id = invocation.agents.start_run(
                child.id, messages=[UserMessage(content="second")], max_steps=1
            )
            result = invocation.agents.wait_run(next_id, timeout=3)
            assert result is not None and result.output.text == "replacement"
        return ToolResult(content="done")

    def exercise() -> None:
        parent = parent_agent(coordinate)
        coordinator = AgentCoordinator()
        first = parent.start(max_steps=2, coordinator=coordinator)
        assert entered.wait(3)
        first.cancel()
        with pytest.raises(AgentCancelled):
            first.result()
        assert first.wait_for_idle(timeout=3)
        record = first.snapshot()
        assert record.child_runs[0].status == RunStatus.CANCELLED
        second = parent.start(max_steps=2, coordinator=coordinator)
        second.result()
        assert second.wait_for_idle(timeout=3)
        assert first.snapshot() == record
        assert coordinator.close(timeout=3)

    exercise()


def test_immediate_restart_waits_for_terminal_child_delivery_to_drain() -> None:
    entered, release = threading.Event(), threading.Event()
    child = Agent(
        FakeModelClient(lambda *_: AssistantMessage(content=[TextContent(text="done")]))
    )

    class ObservedCoordinator(AgentCoordinator):
        def bind(self, run: Run) -> RunCoordination:
            binding = super().bind(run)
            if run.agent_id == child.id:

                def observe(_event: AgentEvent) -> None:
                    entered.set()
                    assert release.wait(3)

                run.subscribe(observe)
            return binding

    def delegate(invocation: ToolInvocation) -> ToolResult:
        submitted = invocation.agents.spawn_agent(
            child, name="research", description="Task", messages=[], max_steps=1
        )
        assert invocation.agents.wait_run(submitted.run_id, timeout=2) is not None
        assert entered.wait(2)
        restarting = start_thread_future(
            operation=lambda: invocation.agents.start_run(
                child.id, messages=[UserMessage(content="again")], max_steps=1
            ),
            name="test-restart",
        )
        time.sleep(0.03)
        assert not restarting.done()
        release.set()
        run_id = restarting.result(2)
        assert run_id != submitted.run_id
        assert invocation.agents.wait_run(run_id, timeout=2) is not None
        return ToolResult(content="done")

    try:
        run_agent(
            parent_agent(delegate), max_steps=2, coordinator=ObservedCoordinator()
        )
    finally:
        release.set()


def test_parent_join_allows_child_to_start_nested_work() -> None:
    parent_answered = threading.Event()

    def nested(invocation: ToolInvocation) -> ToolResult:
        assert parent_answered.wait(3)
        leaf = Agent(
            FakeModelClient(
                lambda *_: AssistantMessage(content=[TextContent(text="leaf")])
            )
        )
        submitted = invocation.agents.spawn_agent(
            leaf, name="leaf", description="Nested work", messages=[], max_steps=1
        )
        result = invocation.agents.wait_run(submitted.run_id, timeout=2)
        assert result is not None
        return ToolResult(content=result.output.text)

    def delegate(invocation: ToolInvocation) -> ToolResult:
        child = parent_agent(nested)
        invocation.agents.spawn_agent(
            child, name="research", description="Research", messages=[], max_steps=2
        )
        return ToolResult(content="started")

    def observe(event: AgentEvent) -> None:
        if (
            isinstance(event, MessageEndEvent)
            and event.parent_run_id is None
            and event.step_index == 1
        ):
            parent_answered.set()

    parent = parent_agent(delegate)

    handles: list[Run] = []
    run_agent(
        parent,
        max_steps=2,
        coordinator=AgentCoordinator(),
        runs=handles,
        listener=observe,
    )
    record = handles[0].snapshot()
    assert record.status == RunStatus.COMPLETE
    assert record.child_runs[0].child_runs[0].messages[-1].text == "leaf"


def test_cancelled_parent_waits_for_child_terminal_record_before_snapshot() -> None:
    def exercise() -> None:
        entered = threading.Event()
        cleanup_started = threading.Event()
        release_cleanup = threading.Event()

        def pending(invocation: ToolInvocation) -> ToolResult:
            entered.set()
            try:
                cancelled = threading.Event()
                with invocation.cancellation.on_cancel(cancelled.set):
                    assert cancelled.wait(3)
                    invocation.cancellation.check()
            finally:
                cleanup_started.set()
                assert release_cleanup.wait(3)
            return ToolResult(content="done")

        child = Agent(
            FakeModelClient(
                lambda *_: AssistantMessage(
                    content=[ToolCall(id="work", name="work", arguments={})]
                )
            ),
            tools=[
                AgentTool(name="work", description="", parameters={}, execute=pending)
            ],
        )

        def delegate(invocation: ToolInvocation) -> ToolResult:
            spawned = invocation.agents.spawn_agent(
                child, name="child", description="Work", messages=[], max_steps=1
            )
            invocation.agents.wait_run(spawned.run_id, timeout=3)
            return ToolResult(content="done")

        coordinator = AgentCoordinator()
        with (
            patch("onyx.agents.agent_coordination.CLEANUP_SECONDS", 0.01),
            patch("onyx.agents.agent_coordination.CHILD_TERMINAL_TIMEOUT_SECONDS", 0.5),
        ):
            run = parent_agent(delegate).start(max_steps=2, coordinator=coordinator)
            try:
                assert entered.wait(2)
                run.cancel()
                assert cleanup_started.wait(2)
                time.sleep(0.03)
                with pytest.raises(AgentCancelled):
                    run.result(2)
                assert not run.wait_for_idle(0)
            finally:
                release_cleanup.set()
            with pytest.raises(AgentCancelled):
                run.result(timeout=2)
            assert run.snapshot().child_runs[0].status == RunStatus.CANCELLED
            assert run.wait_for_idle(timeout=2)
            assert coordinator.close(timeout=2)

    exercise()


def test_child_terminal_timeout_fails_parent_and_retains_cleanup_ownership() -> None:
    def exercise() -> None:
        entered = threading.Event()
        spawned_child = threading.Event()
        release_cleanup = threading.Event()

        def pending(
            _request: GenerationRequest, _signal: CancellationSignal
        ) -> AssistantMessage:
            entered.set()
            assert release_cleanup.wait(3)
            return AssistantMessage(content=[TextContent(text="late")])

        child = Agent(FakeModelClient(pending))

        def delegate(invocation: ToolInvocation) -> ToolResult:
            spawned = invocation.agents.spawn_agent(
                child, name="child", description="Work", messages=[], max_steps=1
            )
            spawned_child.set()
            invocation.agents.wait_run(spawned.run_id, timeout=3)
            return ToolResult(content="done")

        parent = parent_agent(delegate)
        coordinator = AgentCoordinator()
        with patch(
            "onyx.agents.agent_coordination.CHILD_TERMINAL_TIMEOUT_SECONDS", 0.01
        ):
            run = parent.start(max_steps=2, coordinator=coordinator)
            try:
                assert entered.wait(2)
                assert spawned_child.wait(2)
                run.cancel()
                with pytest.raises(RunFailed):
                    run.result(timeout=2)
                record = run.snapshot()
                assert record.status == RunStatus.ERROR
                assert record.child_runs[0].status == RunStatus.ERROR
                assert record.child_runs[0].failure is not None
                assert record.child_runs[0].failure.kind == RunFailureKind.EXECUTION
                assert not run.wait_for_idle(timeout=0.01)
                with pytest.raises(RuntimeError, match="running or draining"):
                    parent.start(max_steps=1, coordinator=coordinator)
            finally:
                release_cleanup.set()
            assert run.wait_for_idle(timeout=2)
            assert run.snapshot() == record
            following = parent.start(max_steps=1, coordinator=coordinator)
            following.result(timeout=2)
            assert following.wait_for_idle(timeout=2)
            assert coordinator.close(timeout=2)

    exercise()


def test_failed_child_settlement_retains_accepted_partial_output(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    partial_accepted = threading.Event()
    release = threading.Event()

    class PartialModel(FakeModelClient):
        def stream(
            self, request: GenerationRequest, context: GenerationContext | None = None
        ) -> Generator[GenerationEvent, None, None]:
            assert request.messages[-1].text == "Find facts"
            assert context is not None and context.cancellation is not None
            message = AssistantMessage(
                content=[TextContent(text="Child partial output")]
            )
            yield TextDeltaEvent(content_index=0, text=message.text)
            partial_accepted.set()
            assert release.wait(3)
            yield GenerationDoneEvent(message=message)

    child = Agent(PartialModel(lambda _request, _signal: AssistantMessage()))

    def coordinate(invocation: ToolInvocation) -> ToolResult:
        invocation.agents.spawn_agent(
            child,
            name="research",
            description="Facts",
            messages=[UserMessage(content="Find facts")],
            max_steps=1,
        )
        assert partial_accepted.wait(2)
        return ToolResult(content="Child started")

    parent = parent_agent(coordinate)
    original_finish = RunCoordination.finish
    failed_coordinators: list[RunCoordination] = []

    def fail_parent_finish(
        coordination: RunCoordination, cancel: bool
    ) -> list[RunState]:
        if coordination.run.agent_id == parent.id:
            failed_coordinators.append(coordination)
            raise TimeoutError("Forced settlement timeout")
        return original_finish(coordination, cancel)

    monkeypatch.setattr(RunCoordination, "finish", fail_parent_finish)
    # Force the settlement failure path instead of suspending for this live child.
    monkeypatch.setattr(RunCoordination, "pending_children", lambda _coordination: [])
    coordinator = AgentCoordinator()
    run = parent.start(max_steps=2, coordinator=coordinator)
    try:
        with pytest.raises(RunFailed):
            run.result(2)
        snapshot = run.snapshot()
        assert snapshot.status == RunStatus.ERROR
        assert snapshot.messages[-1].text == "first finished"
        captured_child = snapshot.child_runs[0]
        assert captured_child.status == RunStatus.ERROR
        assert captured_child.messages[0].text == "Child partial output"
        assert captured_child.failure is not None
        assert captured_child.failure.kind == RunFailureKind.EXECUTION
        assert (
            captured_child.failure.message
            == "Child execution did not settle before its parent ended."
        )
        assert all(
            step.generation_status != "running"
            and all(tool.status != "running" for tool in step.tools.values())
            for step in captured_child.steps
        )
        projected = project_response(
            snapshot,
            response_id=42,
            tool_ids={"coordinate": 1},
            registrations=coordinator.registrations(),
        )
        assert projected.response is not None
        assert projected.response.messages[-1].text == "first finished"
        assert (
            projected.response.child_runs[0].messages[0].text == "Child partial output"
        )
    finally:
        release.set()
        monkeypatch.setattr(RunCoordination, "finish", original_finish)
        for coordination in failed_coordinators[:1]:
            original_finish(coordination, cancel=True)
        assert run.wait_for_idle(3)


def test_background_child_outlives_parent_and_reports_to_application() -> None:
    from onyx.agents.tools import AgentLifetime

    entered, release = threading.Event(), threading.Event()
    events: list[AgentEvent] = []
    completed: list[RunState] = []
    spawned: list[SpawnResult] = []

    def generate(
        _request: GenerationRequest, signal: CancellationSignal
    ) -> AssistantMessage:
        entered.set()
        while not release.wait(0.01):
            signal.check()
        return AssistantMessage(content=[TextContent(text="background finished")])

    child = Agent(FakeModelClient(generate))

    def delegate(invocation: ToolInvocation) -> ToolResult:
        spawned.append(
            invocation.agents.spawn_agent(
                child,
                name="background",
                description="Independent work",
                messages=[],
                max_steps=1,
                lifetime=AgentLifetime.BACKGROUND,
            )
        )
        assert entered.wait(2)
        return ToolResult(content="started")

    coordinator = AgentCoordinator(
        store=FakeRunStore(save=lambda run: completed.append(run.snapshot())),
    )
    parent = parent_agent(delegate)
    root_events: list[AgentEvent] = []
    run = parent.start(
        max_steps=2, coordinator=coordinator, on_event=root_events.append
    )
    try:
        run.result(3)
        assert run.wait_for_idle(3)
        assert run.snapshot().child_runs == []
        child_run = coordinator.child_run(spawned[0].run_id, parent.id)
        assert child_run is not None
        assert child_run.status == RunStatus.RUNNING
        assert coordinator.run(child_run.id) is child_run
        assert not coordinator.completion(child_run.id).done()
        info = coordinator.registration(child.id)
        assert info is not None
        same_scope = coordinator.view()
        assert same_scope.child_run(child_run.id, parent.id) is child_run
        other_scope = coordinator.view(
            directory=FakeAgentDirectory(lookup_agent=lambda *_: info)
        )
        with pytest.raises(ValueError, match="not available"):
            other_scope.child_run(child_run.id, parent.id)
        granted = coordinator.view(
            visible_run_ids=[child_run.id],
            directory=FakeAgentDirectory(lookup_agent=lambda *_: info),
        )
        assert granted.child_run(child_run.id, parent.id) is child_run
        child_run.subscribe(events.append)
        release.set()
        assert child_run.result(3).output.text == "background finished"
        assert child_run.wait_for_idle(3)
        assert coordinator.completion(child_run.id).result(3).run_id == child_run.id
        assert any(event.run_id == child_run.id for event in events)
        assert all(event.run_id == run.id for event in root_events)
        assert any(snapshot.run_id == child_run.id for snapshot in completed)
        assert coordinator.child_run(child_run.id, parent.id) is child_run
    finally:
        release.set()
        assert coordinator.close(3)


def test_completion_failure_is_retained_and_shutdown_waits_for_handler() -> None:
    entered, release = threading.Event(), threading.Event()

    def save(_snapshot: RunState) -> None:
        entered.set()
        assert release.wait(3)
        raise ValueError("storage unavailable")

    coordinator = AgentCoordinator(
        store=FakeRunStore(save=lambda run: save(run.snapshot()))
    )
    agent = Agent(
        FakeModelClient(lambda *_: AssistantMessage(content=[TextContent(text="done")]))
    )
    run = agent.start(max_steps=1, coordinator=coordinator)
    try:
        run.result(3)
        assert entered.wait(2)
        assert not run.wait_for_idle(0)
        assert not coordinator.close(0)
        release.set()
        with pytest.raises(ValueError, match="storage unavailable"):
            coordinator.completion(run.id).result(3)
        assert coordinator.close(3)
    finally:
        release.set()


def test_fresh_coordinator_view_rebinds_idle_child_and_checks_visibility() -> None:
    spawned: list[SpawnResult] = []
    restored: list[str] = []
    child = Agent(
        FakeModelClient(
            lambda *_: AssistantMessage(content=[TextContent(text="old binding")])
        )
    )

    def delegate(invocation: ToolInvocation) -> ToolResult:
        if not spawned:
            spawned.append(
                invocation.agents.spawn_agent(
                    child, name="child", description="", messages=[], max_steps=1
                )
            )
        else:
            run_id = invocation.agents.start_run(child.id, messages=[], max_steps=1)
            result = invocation.agents.wait_run(run_id, timeout=3)
            assert result is not None and result.output.text == "new binding"
        return ToolResult(content="done")

    coordinator = AgentCoordinator()
    parent = parent_agent(delegate)
    first = parent.start(max_steps=2, coordinator=coordinator)
    first.result(3)
    assert first.wait_for_idle(3)
    info = coordinator.registration(child.id)
    assert info is not None

    def restore(agent_id: str, parent_id: str) -> Agent:
        assert agent_id == child.id and parent_id == parent.id
        restored.append(agent_id)
        replacement = Agent(
            FakeModelClient(
                lambda *_: AssistantMessage(content=[TextContent(text="new binding")])
            ),
            agent_id=agent_id,
        )
        return replacement

    current = coordinator.view(
        directory=FakeAgentDirectory(
            lookup_agent=lambda *_: info, restore_agent=restore
        )
    )
    second = parent.start(max_steps=2, coordinator=current)
    second.result(3)
    assert second.wait_for_idle(3)
    assert restored == [child.id]
    assert current.run(first.id) is first
    hidden = coordinator.view(
        directory=FakeAgentDirectory(lookup_agent=lambda *_: None)
    )
    assert hidden.discovery(parent.id) == []
    with pytest.raises(ValueError, match="not available"):
        hidden.child_run(spawned[0].run_id, parent.id)
    assert coordinator.close(3)


def test_views_authorize_runs_independently_for_the_same_child() -> None:
    child = Agent(
        FakeModelClient(lambda *_: AssistantMessage(content=[TextContent(text="done")]))
    )
    run_ids: list[str] = []

    def delegate(invocation: ToolInvocation) -> ToolResult:
        if not run_ids:
            run_ids.append(
                invocation.agents.spawn_agent(
                    child, name="child", description="", messages=[], max_steps=1
                ).run_id
            )
        else:
            run_ids.append(
                invocation.agents.start_run(child.id, messages=[], max_steps=1)
            )
        invocation.agents.wait_run(run_ids[-1], timeout=3)
        return ToolResult(content="done")

    owner = AgentCoordinator()
    parent = parent_agent(delegate)
    for _ in range(2):
        run = parent.start(max_steps=2, coordinator=owner)
        run.result(3)
        assert run.wait_for_idle(3)
    first, second = (owner.run(run_id) for run_id in run_ids)
    info = owner.registration(child.id)
    assert info is not None
    first_info = info.model_copy(
        update={"latest_run_id": first.id, "status": first.status}
    )
    second_info = info.model_copy(
        update={"latest_run_id": second.id, "status": second.status}
    )
    branch_a = owner.view(
        directory=FakeAgentDirectory(
            lookup_agent=lambda *_: first_info,
            read_run=lambda run_id, _: first.snapshot() if run_id == first.id else None,
        )
    )
    branch_b = owner.view(
        directory=FakeAgentDirectory(
            lookup_agent=lambda *_: second_info,
            read_run=lambda run_id, _: (
                second.snapshot() if run_id == second.id else None
            ),
        )
    )
    try:
        for view, visible, hidden in (
            (branch_a, first, second),
            (branch_b, second, first),
        ):
            with pytest.raises(ValueError, match="not available"):
                view.child_run(hidden.id, parent.id)
            with pytest.raises(ValueError, match="not available"):
                view.saved_run(hidden.id, parent.id)
            assert view.saved_run(hidden.id, parent.id, load_archive=False) is None
            assert view.child_run(visible.id, parent.id) is visible
            assert view.saved_run(visible.id, parent.id).run_id == visible.id
        assert owner.view().loaded_child(child.id, parent.id) is child

        def reject_stale_context(invocation: ToolInvocation) -> ToolResult:
            with pytest.raises(ValueError, match="restoration is unavailable"):
                invocation.agents.start_run(child.id, messages=[], max_steps=1)
            return ToolResult(content="rejected")

        branch_parent = parent_agent(reject_stale_context, agent_id=parent.id)
        branch_run = branch_parent.start(max_steps=2, coordinator=branch_a)
        branch_run.result(3)
        assert branch_run.wait_for_idle(3)
        assert branch_a.discovery(parent.id)[0].latest_run_id == first.id
        assert branch_b.discovery(parent.id)[0].latest_run_id == second.id
        assert owner.child_run(first.id, parent.id) is first
        assert owner.child_run(second.id, parent.id) is second
    finally:
        assert owner.close(3)


def test_foreground_continuation_retains_consumed_background_history() -> None:
    from onyx.agents.tools import AgentLifetime

    child = Agent(
        FakeModelClient(lambda *_: AssistantMessage(content=[TextContent(text="done")]))
    )
    runs: list[str] = []

    def delegate(invocation: ToolInvocation) -> ToolResult:
        spawned = invocation.agents.spawn_agent(
            child,
            name="child",
            description="",
            messages=[],
            max_steps=1,
            lifetime=AgentLifetime.BACKGROUND,
        )
        runs.append(spawned.run_id)
        assert invocation.agents.wait_run(runs[-1], timeout=3) is not None
        runs.append(
            invocation.agents.start_run(
                child.id, messages=[], max_steps=1, lifetime=AgentLifetime.BACKGROUND
            )
        )
        assert invocation.agents.wait_run(runs[-1], timeout=3) is not None
        runs.append(invocation.agents.start_run(child.id, messages=[], max_steps=1))
        assert invocation.agents.wait_run(runs[-1], timeout=3) is not None
        return ToolResult(content="done")

    owner = AgentCoordinator()
    parent = parent_agent(delegate)
    run = parent.start(max_steps=2, coordinator=owner)
    try:
        run.result(3)
        assert run.wait_for_idle(3)
        snapshot = run.snapshot()
        assert [child.run_id for child in snapshot.child_runs] == runs
        assert [child.previous_run_id for child in snapshot.child_runs] == [
            None,
            *runs[:-1],
        ]
        assert all(child.parent_run_id == run.id for child in snapshot.child_runs)
    finally:
        assert owner.close(3)


def test_coordinator_shutdown_cancels_background_child_after_parent_failure() -> None:
    from onyx.agents.tools import AgentLifetime

    entered = threading.Event()
    spawned: list[SpawnResult] = []

    def generate(
        _request: GenerationRequest, signal: CancellationSignal
    ) -> AssistantMessage:
        entered.set()
        cancelled = threading.Event()
        with signal.on_cancel(cancelled.set):
            assert cancelled.wait(3)
            signal.check()
        return AssistantMessage()

    def delegate(invocation: ToolInvocation) -> ToolResult:
        spawned.append(
            invocation.agents.spawn_agent(
                Agent(FakeModelClient(generate)),
                name="background",
                description="",
                messages=[],
                max_steps=1,
                lifetime=AgentLifetime.BACKGROUND,
            )
        )
        assert entered.wait(2)
        raise ValueError("parent failed")

    coordinator = AgentCoordinator()
    run = parent_agent(delegate).start(max_steps=2, coordinator=coordinator)
    with pytest.raises(RunFailed):
        run.result(3)
    assert run.wait_for_idle(3)
    child = coordinator.run(spawned[0].run_id)
    assert child.status == RunStatus.RUNNING
    assert coordinator.close(3)
    with pytest.raises(AgentCancelled):
        child.result(0)
    assert child.wait_for_idle(0)


def test_parent_child_wait_releases_worker_while_sibling_continues() -> None:
    execution_context = ContextVar("execution_context", default="parent")
    sibling_entered, sibling_release = threading.Event(), threading.Event()
    spawned: list[SpawnResult] = []
    completed_children: list[str] = []
    question_messages = iter(
        [
            AssistantMessage(
                content=[ToolCall(id="question", name="question", arguments={})]
            ),
            AssistantMessage(content=[TextContent(text="answered")]),
        ]
    )

    def question_reply(
        _request: GenerationRequest, _signal: CancellationSignal
    ) -> AssistantMessage:
        execution_context.set("child")
        return next(question_messages)

    question = Agent(
        FakeModelClient(question_reply),
        tools=[
            AgentTool(
                name="question",
                description="",
                parameters={},
                execute=lambda _: PendingToolInput(
                    request_id="answer",
                    prompt="Continue?",
                    mode=InputMode.RESULT,
                ),
            )
        ],
    )

    def sibling_reply(
        _request: GenerationRequest, signal: CancellationSignal
    ) -> AssistantMessage:
        sibling_entered.set()
        while not sibling_release.wait(0.01):
            signal.check()
        return AssistantMessage(content=[TextContent(text="sibling finished")])

    def delegate(invocation: ToolInvocation) -> ChildRunWait:
        for name, child, steps in [
            ("question", question, 2),
            ("sibling", Agent(FakeModelClient(sibling_reply)), 1),
        ]:
            spawned.append(
                invocation.agents.spawn_agent(
                    child,
                    name=name,
                    description="",
                    messages=[],
                    max_steps=steps,
                )
            )
        return ChildRunWait(run_ids=[child.run_id for child in spawned])

    def complete(_invocation: ToolInvocation, snapshots: list[RunState]) -> ToolResult:
        assert execution_context.get() == "parent"
        completed_children.extend(snapshot.run_id for snapshot in snapshots)
        return ToolResult(content="children finished")

    parent_messages = iter(
        [
            AssistantMessage(
                content=[ToolCall(id="delegate", name="delegate", arguments={})]
            ),
            AssistantMessage(content=[TextContent(text="parent finished")]),
        ]
    )
    parent = Agent(
        FakeModelClient(lambda *_: next(parent_messages)),
        tools=[
            AgentTool(
                name="delegate",
                description="",
                parameters={},
                execute=delegate,
                complete_children=complete,
            )
        ],
    )
    coordinator = AgentCoordinator()
    run = parent.start(max_steps=2, coordinator=coordinator)
    try:
        assert sibling_entered.wait(2)
        assert run.wait_until_settled(2).status == RunStatus.SUSPENDED
        assert run.wait_for_idle(0)
        assert not run._completed.done()
        waiting_child = coordinator.run(spawned[0].run_id)
        assert waiting_child.wait_until_settled(2).status == RunStatus.SUSPENDED
        sibling = coordinator.run(spawned[1].run_id)
        assert sibling.status == RunStatus.RUNNING
        sibling_release.set()
        assert sibling.result(2).output.text == "sibling finished"
        assert waiting_child.status == RunStatus.SUSPENDED
        assert not run._completed.done()
        waiting_child.submit(
            HumanToolAnswer(
                request_id="answer",
                decision=InputDecision.RESULT,
                result=ToolResult(content="yes"),
            )
        )
        assert run.result(3).output.text == "parent finished"
        assert run.wait_for_idle(3)
        assert completed_children == [child.run_id for child in spawned]
    finally:
        sibling_release.set()
        assert coordinator.close(3)


def test_cold_restore_rejects_existing_owner_and_missing_child_rolls_back() -> None:
    from onyx.agents.tools import InputMode, PendingToolInput

    def create(agent_id: str | None = None) -> Agent:
        return Agent(
            FakeModelClient(
                lambda *_: AssistantMessage(
                    content=[ToolCall(id="q", name="q", arguments={})]
                )
            ),
            agent_id=agent_id,
            tools=[
                AgentTool(
                    name="q",
                    description="",
                    parameters={},
                    execute=lambda _: PendingToolInput(
                        request_id="question",
                        prompt="Question",
                        mode=InputMode.RESULT,
                    ),
                )
            ],
        )

    coordinator = AgentCoordinator()
    agent = create()
    run = agent.start(max_steps=2, coordinator=coordinator)
    try:
        snapshot = run.wait_until_settled(2)
        assert snapshot.status == RunStatus.SUSPENDED
        replacement = create(agent_id=agent.id)
        with pytest.raises(RuntimeError, match="already running or draining"):
            replacement.resume(snapshot, coordinator=coordinator)
        assert coordinator.run(run.id) is run
        assert coordinator.active_run(agent.id) is run
        assert run.status == RunStatus.SUSPENDED

        unrelated = AgentCoordinator()
        broken = snapshot.model_copy(deep=True)
        assert broken.progress is not None
        broken.progress.child_run_ids = ["missing-child"]
        with pytest.raises(ValueError, match="not available"):
            replacement.resume(broken, coordinator=unrelated)
        assert unrelated.active_run(agent.id) is None
        assert unrelated.close(0)
    finally:
        assert coordinator.close(3)


def test_cold_parent_restores_archived_handled_child_failure() -> None:
    from onyx.agents.models import AgentState
    from onyx.agents.tools import (
        ChildRunWait,
        HumanToolAnswer,
        InputDecision,
        InputMode,
        PendingToolInput,
    )

    codec = CheckpointStorage({})
    binding = CheckpointBinding(
        tenant_id="tenant", branch_id="branch", context_version="1"
    )

    def save_original() -> tuple[str, str, AgentInfo]:
        children: list[SpawnResult] = []

        def fail(
            _request: GenerationRequest, _signal: CancellationSignal
        ) -> AssistantMessage:
            raise ValueError("Child failed")

        def delegate(invocation: ToolInvocation) -> ChildRunWait:
            children.append(
                invocation.agents.spawn_agent(
                    Agent(FakeModelClient(fail)),
                    name="child",
                    description="",
                    messages=[],
                    max_steps=1,
                )
            )
            return ChildRunWait(run_ids=[children[0].run_id])

        replies = iter(
            [
                AssistantMessage(
                    content=[ToolCall(id="delegate", name="delegate", arguments={})]
                ),
                AssistantMessage(
                    content=[ToolCall(id="question", name="question", arguments={})]
                ),
            ]
        )
        parent = Agent(
            FakeModelClient(lambda *_: next(replies)),
            tools=[
                AgentTool(
                    name="delegate",
                    description="",
                    parameters={},
                    execute=delegate,
                    complete_children=lambda *_: ToolResult(content="Failure handled"),
                ),
                AgentTool(
                    name="question",
                    description="",
                    parameters={},
                    execute=lambda _: PendingToolInput(
                        request_id="answer", prompt="Continue?", mode=InputMode.RESULT
                    ),
                ),
            ],
        )
        owner = AgentCoordinator()
        run = parent.start(max_steps=3, coordinator=owner)
        try:
            # An intermediate suspension may wait for the child before asking the question.
            deadline = time.monotonic() + 3
            while True:
                record = run.wait_until_settled(max(0, deadline - time.monotonic()))
                if record.progress and "question" in record.progress.pending_tool_calls:
                    break
                assert time.monotonic() < deadline
                time.sleep(0.001)
            checkpoint = run.capture()
            child = owner.run(children[0].run_id).snapshot()
            assert child.status == RunStatus.ERROR
            info = owner.registration(children[0].agent_id)
            assert info is not None
            assert checkpoint.run_state.progress is not None
            assert checkpoint.run_state.progress.observed_child_run_ids == [
                child.run_id
            ]
            return (
                codec.save(checkpoint.run_state, checkpoint.agent_state, binding),
                codec.save(child, AgentState(), binding),
                info,
            )
        finally:
            assert owner.close(3)

    parent_json, child_json, info = save_original()
    restored = codec.load(parent_json, expected_binding=binding)
    archived_child = codec.load(child_json, expected_binding=binding).run_state

    def unexpected(_invocation: ToolInvocation) -> ToolResult:
        raise AssertionError("Completed or pending tool code must not repeat")

    parent = Agent(
        FakeModelClient(
            lambda *_: AssistantMessage(
                content=[TextContent(text="restored parent finished")]
            )
        ),
        agent_id=restored.run_state.agent_id,
        state=restored.agent_state,
        tools=[
            AgentTool(
                name="delegate",
                description="",
                parameters={},
                execute=unexpected,
                complete_children=lambda *_: ToolResult(content="Failure handled"),
            ),
            AgentTool(
                name="question", description="", parameters={}, execute=unexpected
            ),
        ],
    )
    owner = AgentCoordinator(
        agents=[info], directory=FakeAgentDirectory(read_run=lambda *_: archived_child)
    )
    resumed = parent.resume(restored.run_state, coordinator=owner)
    try:
        assert resumed.wait_until_settled(3).status == RunStatus.SUSPENDED
        resumed.submit(
            HumanToolAnswer(
                request_id="answer",
                decision=InputDecision.RESULT,
                result=ToolResult(content="yes"),
            )
        )
        assert resumed.result(3).output.text == "restored parent finished"
        assert resumed.wait_for_idle(3)
        assert resumed.snapshot().child_runs[0].status == RunStatus.ERROR
    finally:
        assert owner.close(3)


@pytest.mark.parametrize("cancel", [False, True])
def test_completion_cleanup_waits_for_terminal_and_parent_retains_it(
    cancel: bool,
) -> None:
    from onyx.agents.tools import (
        ChildRunWait,
        HumanToolAnswer,
        InputDecision,
        InputMode,
        PendingToolInput,
    )

    cleaning, release_cleanup = threading.Event(), threading.Event()
    children: list[SpawnResult] = []
    child_replies = iter(
        [
            AssistantMessage(
                content=[ToolCall(id="question", name="question", arguments={})]
            ),
            AssistantMessage(content=[TextContent(text="child finished")]),
        ]
    )
    child = Agent(
        FakeModelClient(lambda *_: next(child_replies)),
        tools=[
            AgentTool(
                name="question",
                description="",
                parameters={},
                execute=lambda _: PendingToolInput(
                    request_id="answer",
                    prompt="Continue?",
                    mode=InputMode.RESULT,
                ),
            )
        ],
    )

    def cleanup() -> None:
        cleaning.set()
        assert release_cleanup.wait(3)

    def delegate(invocation: ToolInvocation) -> ChildRunWait:
        children.append(
            invocation.agents.spawn_agent(
                child,
                name="child",
                description="",
                messages=[],
                max_steps=2,
            )
        )
        invocation.agents.add_completion_cleanup(children[0].run_id, cleanup)
        return ChildRunWait(run_ids=[children[0].run_id])

    replies = iter(
        [
            AssistantMessage(
                content=[ToolCall(id="delegate", name="delegate", arguments={})]
            ),
            AssistantMessage(content=[TextContent(text="parent finished")]),
        ]
    )
    parent = Agent(
        FakeModelClient(lambda *_: next(replies)),
        tools=[
            AgentTool(
                name="delegate",
                description="",
                parameters={},
                execute=delegate,
                complete_children=lambda *_: ToolResult(content="finished"),
            )
        ],
    )
    owner = AgentCoordinator()
    run = parent.start(max_steps=2, coordinator=owner)
    try:
        assert run.wait_until_settled(2).status == RunStatus.SUSPENDED
        child_run = owner.run(children[0].run_id)
        assert child_run.wait_until_settled(2).status == RunStatus.SUSPENDED
        assert run.wait_for_idle(0)
        assert not cleaning.is_set()
        if cancel:
            run.cancel()
            with pytest.raises(AgentCancelled):
                run.result(2)
        else:
            child_run.submit(
                HumanToolAnswer(
                    request_id="answer",
                    decision=InputDecision.RESULT,
                    result=ToolResult(content="yes"),
                )
            )
            run.result(2)
        assert cleaning.wait(2)
        assert not run.wait_for_idle(0)
        assert not owner.close(0)
        release_cleanup.set()
        assert run.wait_for_idle(2)
        assert owner.close(2)
    finally:
        release_cleanup.set()
        assert owner.close(3)


def test_completion_cleanup_falls_back_when_worker_start_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cleaned: list[str] = []
    owner = AgentCoordinator()
    agent = Agent(
        FakeModelClient(lambda *_: AssistantMessage(content=[TextContent(text="done")]))
    )
    run = agent.start(max_steps=1, coordinator=owner)
    run.result(2)
    assert run.wait_for_idle(2)

    def fail(_operation: Callable[[], object]) -> None:
        raise RuntimeError("Cannot create a thread")

    monkeypatch.setattr(owner._state.work, "start", fail)
    completion = owner.add_completion_cleanup(run.id, lambda: cleaned.append(run.id))
    completion.result(2)
    assert cleaned == [run.id]
    assert owner.close(2)


@pytest.mark.parametrize("early_answer", [False, True])
def test_child_handoff_preserves_parent_waiter_and_cleanup(early_answer: bool) -> None:
    import gc
    import weakref

    from onyx.agents.tools import (
        ChildRunWait,
        HumanToolAnswer,
        InputDecision,
        InputMode,
        PendingToolInput,
    )

    original = Agent(
        FakeModelClient(
            lambda *_: AssistantMessage(
                content=[ToolCall(id="q", name="q", arguments={})]
            )
        ),
        tools=[
            AgentTool(
                name="q",
                description="",
                parameters={},
                execute=lambda _: PendingToolInput(
                    request_id="answer", prompt="Question", mode=InputMode.RESULT
                ),
            )
        ],
    )
    child_ref = weakref.ref(original)
    child: Agent | None = original
    del original
    spawned: list[SpawnResult] = []
    cleaned: list[str] = []

    def delegate(invocation: ToolInvocation) -> ChildRunWait:
        assert child is not None
        spawned.append(
            invocation.agents.spawn_agent(
                child, name="child", description="", messages=[], max_steps=2
            )
        )
        invocation.agents.add_completion_cleanup(
            spawned[0].run_id, lambda: cleaned.append(spawned[0].run_id)
        )
        return ChildRunWait(run_ids=[spawned[0].run_id])

    replies = iter(
        [
            AssistantMessage(
                content=[ToolCall(id="delegate", name="delegate", arguments={})]
            ),
            AssistantMessage(content=[TextContent(text="parent finished")]),
        ]
    )
    parent = Agent(
        FakeModelClient(lambda *_: next(replies)),
        tools=[
            AgentTool(
                name="delegate",
                description="",
                parameters={},
                execute=delegate,
                complete_children=lambda *_: ToolResult(content="done"),
            )
        ],
    )
    owner = AgentCoordinator()
    root = parent.start(max_steps=2, coordinator=owner)
    try:
        assert root.wait_until_settled(2).status == RunStatus.SUSPENDED
        run = owner.run(spawned[0].run_id)
        assert run.wait_until_settled(2).status == RunStatus.SUSPENDED
        completion = owner.completion(run.id)
        assert child is not None
        saved = run.handoff()
        child = None
        gc.collect()
        assert child_ref() is None
        answer = HumanToolAnswer(
            request_id="answer",
            decision=InputDecision.RESULT,
            result=ToolResult(content="yes"),
        )
        if early_answer:
            assert saved.run_state.progress is not None
            saved.run_state.progress.human_tool_answers[answer.request_id] = answer
        replacement = Agent(
            FakeModelClient(
                lambda *_: AssistantMessage(
                    content=[TextContent(text="restored child finished")]
                )
            ),
            state=saved.agent_state,
            agent_id=saved.run_state.agent_id,
            tools=[
                AgentTool(
                    name="q",
                    description="",
                    parameters={},
                    execute=lambda _: ToolResult(content="must not run"),
                )
            ],
        )
        adopted = replacement.resume(saved.run_state, coordinator=owner)
        assert adopted is not run and adopted.id == run.id
        assert owner.completion(run.id) is completion
        if not early_answer:
            assert adopted.wait_until_settled(2).status == RunStatus.SUSPENDED
            adopted.submit(answer)
        assert root.result(3).output.text == "parent finished"
        assert root.wait_for_idle(3)
        assert adopted.status == RunStatus.COMPLETE
        assert cleaned == [run.id]
        assert completion.result(0).messages[-1].text == "restored child finished"
    finally:
        assert owner.close(3)


def test_coordinator_close_leaves_released_state_unchanged() -> None:
    from onyx.agents.tools import InputMode, PendingToolInput

    owner = AgentCoordinator()
    cleaned: list[str] = []
    agent = Agent(
        FakeModelClient(
            lambda *_: AssistantMessage(
                content=[ToolCall(id="q", name="q", arguments={})]
            )
        ),
        tools=[
            AgentTool(
                name="q",
                description="",
                parameters={},
                execute=lambda _: PendingToolInput(
                    request_id="answer", prompt="Question", mode=InputMode.RESULT
                ),
            )
        ],
    )
    run = agent.start(max_steps=2, coordinator=owner)
    owner.add_completion_cleanup(run.id, lambda: cleaned.append(run.id))
    assert run.wait_until_settled(2).status == RunStatus.SUSPENDED
    run.handoff()
    assert owner.close(3)
    with pytest.raises(RunReleased):
        run.result(0)
    assert owner.active_run(agent.id) is None
    assert run.status == RunStatus.SUSPENDED
    assert cleaned == [run.id]


def test_parent_handoff_releases_feature_and_preserves_child_dependency() -> None:
    owner = AgentCoordinator()
    child_started = threading.Event()
    release_child = threading.Event()
    submissions: list[SpawnResult] = []

    def child_reply(
        _request: GenerationRequest, _signal: CancellationSignal
    ) -> AssistantMessage:
        child_started.set()
        assert release_child.wait(5)
        return AssistantMessage(content=[TextContent(text="child finished")])

    def delegate(invocation: ToolInvocation) -> ChildRunWait:
        submission = invocation.agents.spawn_agent(
            Agent(FakeModelClient(child_reply)),
            name="child",
            description="",
            messages=[],
            max_steps=1,
        )
        submissions.append(submission)
        return ChildRunWait(run_ids=[submission.run_id])

    parent = Agent(
        FakeModelClient(
            lambda *_: AssistantMessage(
                content=[ToolCall(id="delegate", name="delegate", arguments={})]
            )
        ),
        tools=[
            AgentTool(
                name="delegate",
                description="",
                parameters={},
                execute=delegate,
                complete_children=lambda *_: ToolResult(content="child finished"),
            )
        ],
    )
    reference = weakref.ref(parent)
    run = parent.start(max_steps=2, coordinator=owner)
    try:
        assert child_started.wait(2)
        assert run.wait_until_settled(2).status == RunStatus.SUSPENDED
        with pytest.raises(RunNotTransferable, match="child runs must finish"):
            run.handoff()
        run.suspend()
        release_child.set()
        child_run = owner.run(submissions[0].run_id)
        assert child_run.result(2).output.text == "child finished"
        assert child_run.wait_for_idle(2)
        assert run.wait_until_settled(2).status == RunStatus.SUSPENDED
        saved = run.handoff()
        del parent
        gc.collect()
        assert reference() is None
        fresh_owner = AgentCoordinator(
            agents=owner.registrations(),
            directory=FakeAgentDirectory(read_run=lambda *_: child_run.snapshot()),
        )
        replacement = Agent(
            FakeModelClient(
                lambda *_: AssistantMessage(
                    content=[TextContent(text="parent finished")]
                )
            ),
            state=saved.agent_state,
            agent_id=saved.run_state.agent_id,
            tools=[
                AgentTool(
                    name="delegate",
                    description="",
                    parameters={},
                    execute=lambda _: pytest.fail("Completed spawn must not repeat"),
                    complete_children=lambda *_: ToolResult(content="child finished"),
                )
            ],
        )
        try:
            resumed = replacement.resume(saved.run_state, coordinator=fresh_owner)
            assert resumed.id == run.id
            assert resumed.result(2).output.text == "parent finished"
            assert resumed.wait_for_idle(2)
        finally:
            assert fresh_owner.close(3)
    finally:
        release_child.set()
        assert owner.close(3)


@pytest.mark.parametrize("status", [RunStatus.RUNNING, RunStatus.SUSPENDED])
def test_remote_run_wait_and_cancel_use_authorized_fresh_snapshots(
    status: RunStatus,
) -> None:
    child = Agent(
        FakeModelClient(
            lambda *_: AssistantMessage(content=[TextContent(text="remote done")])
        )
    )
    handles: list[Run] = []
    run_agent(child, max_steps=1, runs=handles)
    remote = handles[0].snapshot().model_copy(update={"status": status})
    reads: list[tuple[str, str]] = []
    cancellations: list[tuple[str, str]] = []
    complete = False

    def read(run_id: str, parent_id: str) -> RunState | None:
        reads.append((run_id, parent_id))
        if run_id != remote.run_id:
            return None
        if complete:
            return remote.model_copy(update={"status": RunStatus.COMPLETE})
        return remote.model_copy(deep=True)

    def execute(invocation: ToolInvocation) -> ToolResult:
        nonlocal complete
        assert coordinator.saved_run(remote.run_id, parent.id).status == status
        assert invocation.agents.wait_run(remote.run_id, timeout=0.02) is None
        invocation.agents.cancel_run(remote.run_id)
        assert cancellations == [(remote.run_id, parent.id)]
        complete = True
        assert invocation.agents.wait_run(remote.run_id, timeout=1) is not None
        invocation.agents.cancel_run(remote.run_id)
        assert len(cancellations) == 1
        archived = coordinator.restore_completed(
            remote.model_copy(update={"status": RunStatus.COMPLETE})
        )
        assert archived.result(0).output.text == "remote done"
        with pytest.raises(ValueError, match="Physical cleanup"):
            invocation.agents.add_completion_cleanup(
                remote.run_id, lambda: pytest.fail("archived cleanup")
            )
        with pytest.raises(ValueError, match="not available"):
            invocation.agents.cancel_run("hidden")
        return ToolResult(content="done")

    parent = parent_agent(execute)
    owner = AgentCoordinator(
        directory=FakeAgentDirectory(
            cancel_run=lambda *_: pytest.fail("stale callback")
        )
    )
    coordinator = owner.view(
        directory=FakeAgentDirectory(
            read_run=read, cancel_run=lambda *args: cancellations.append(args)
        )
    )
    coordinator.register(
        AgentInfo(
            id=child.id,
            path="/root/remote",
            parent_id=parent.id,
            description="remote",
            restoration_config=None,
        )
    )
    run_agent(parent, max_steps=2, coordinator=coordinator)
    assert len(reads) >= 5
    assert owner.close(timeout=3)


def test_registration_failure_prevents_model_and_thread_failure_rolls_back() -> None:
    invoked = threading.Event()

    def reply(
        _request: GenerationRequest, _signal: CancellationSignal
    ) -> AssistantMessage:
        invoked.set()
        return AssistantMessage(content=[])

    agent = Agent(FakeModelClient(reply))
    captured: list[Run] = []
    rolled_back: list[str] = []

    def fail_start(run: Run) -> None:
        assert agent.id == run.agent_id
        raise ValueError("registration failed")

    coordinator = AgentCoordinator(ownership=FakeRunOwnership(register=fail_start))
    with pytest.raises(ValueError, match="registration failed"):
        agent.start(max_steps=1, coordinator=coordinator)
    assert not invoked.is_set()
    assert coordinator.close(timeout=1)

    def start(run: Run) -> None:
        assert agent.id == run.agent_id
        captured.append(run)

    coordinator = AgentCoordinator(
        ownership=FakeRunOwnership(register=fail_start)
    ).view(ownership=FakeRunOwnership(register=start, abort_start=rolled_back.append))
    with patch(
        "onyx.agents.runtime.start_thread_with_context",
        side_effect=RuntimeError("thread failed"),
    ):
        with pytest.raises(RuntimeError, match="thread failed"):
            agent.start(max_steps=1, coordinator=coordinator)
    assert rolled_back == [captured[0].id]
    assert not invoked.is_set()
    assert coordinator.close(timeout=1)


def test_registration_releases_execution_locks_during_spawn_and_resume() -> None:
    checked: list[str] = []
    agents: dict[str, Agent] = {}
    coordinator: AgentCoordinator

    def register(run: Run) -> None:
        agent = agents[run.agent_id]

        def probe() -> None:
            with agent._lock, run._lock, coordinator._state.lock:
                binding = coordinator._state.bindings[run.id]
                with binding._lock:
                    parent_id = run.snapshot().parent_run_id
                    if parent_id is not None:
                        with coordinator._state.bindings[parent_id]._lock:
                            checked.append(run.id)
                    else:
                        checked.append(run.id)

        start_thread_future(probe, name="lock-probe").result(timeout=2)

    child = Agent(
        FakeModelClient(
            lambda *_: AssistantMessage(content=[TextContent(text="child")])
        )
    )

    def spawn(invocation: ToolInvocation) -> ToolResult:
        submitted = invocation.agents.spawn_agent(
            child, name="child", description="", max_steps=1, messages=[]
        )
        assert invocation.agents.wait_run(submitted.run_id, timeout=3) is not None
        return ToolResult(content="child done")

    parent = parent_agent(spawn)
    agents.update({parent.id: parent, child.id: child})
    coordinator = AgentCoordinator(ownership=FakeRunOwnership(register=register))
    run_agent(parent, max_steps=2, coordinator=coordinator)
    assert len(checked) == 2
    assert coordinator.close(timeout=3)

    tool = AgentTool(
        name="pause",
        description="",
        parameters={},
        execute=lambda _: PendingToolInput(
            request_id="pause", prompt="Continue?", mode=InputMode.RESULT
        ),
    )
    original = Agent(
        FakeModelClient(
            lambda *_: AssistantMessage(
                content=[ToolCall(id="pause", name="pause", arguments={})]
            )
        ),
        tools=[tool],
    )
    coordinator = AgentCoordinator(ownership=FakeRunOwnership(register=register))
    agents[original.id] = original
    run = original.start(max_steps=2, coordinator=coordinator)
    assert run.wait_until_settled(timeout=3).status == RunStatus.SUSPENDED
    assert run.wait_for_idle(timeout=3)
    checkpoint = run.handoff()
    restored = Agent(
        FakeModelClient(
            lambda *_: AssistantMessage(content=[TextContent(text="done")])
        ),
        tools=[tool],
        agent_id=original.id,
        state=checkpoint.agent_state,
    )
    agents[restored.id] = restored
    resumed = restored.resume(checkpoint.run_state, coordinator=coordinator)
    assert resumed is not run and resumed.id == run.id
    resumed.submit(
        HumanToolAnswer(
            request_id="pause",
            decision=InputDecision.RESULT,
            result=ToolResult(content="continue"),
        )
    )
    assert resumed.result(timeout=3).output.text == "done"
    assert len(checked) == 4
    assert coordinator.close(timeout=3)


def suspended_agent() -> Agent:
    return Agent(
        FakeModelClient(
            lambda *_: AssistantMessage(
                content=[ToolCall(id="ask", name="ask", arguments={})]
            )
        ),
        tools=[
            AgentTool(
                name="ask",
                description="",
                parameters={},
                execute=lambda _: PendingToolInput(
                    request_id="question", prompt="Continue?", mode=InputMode.RESULT
                ),
            )
        ],
    )


def test_released_run_has_no_local_cleanup_or_controls() -> None:
    coordinator = AgentCoordinator()
    agent = suspended_agent()
    run = agent.start(max_steps=2, coordinator=coordinator)
    assert run.wait_until_settled(3).status == RunStatus.SUSPENDED
    assert run.wait_for_idle(3)
    checkpoint = run.handoff()
    with pytest.raises(ValueError, match="not owned"):
        coordinator.add_completion_cleanup(run.id, lambda: pytest.fail("local cleanup"))
    run.cancel()
    with pytest.raises(RunReleased):
        run.result(0)
    assert coordinator.close(3)
    assert checkpoint.run_state.status == RunStatus.SUSPENDED


def test_saved_completion_notifies_dependencies_without_execution_locks() -> None:
    result_ready = threading.Event()
    snapshots: list[RunState] = []
    coordinator = AgentCoordinator(
        directory=FakeAgentDirectory(
            read_run_status=lambda *_: (
                RunStatus.COMPLETE if result_ready.is_set() else RunStatus.SUSPENDED
            ),
            read_run=lambda *_: snapshots[0],
        )
    )
    agent = suspended_agent()
    run = agent.start(max_steps=2, coordinator=coordinator)
    assert run.wait_until_settled(3).status == RunStatus.SUSPENDED
    assert run.wait_for_idle(3)
    checked = threading.Event()

    def completion(_future: Future[RunState]) -> None:
        def probe() -> None:
            with coordinator._state.lock:
                checked.set()

        start_thread_future(probe, name="completion-lock-probe").result(timeout=2)

    coordinator.completion(run.id).add_done_callback(completion)
    saved = run.handoff()
    snapshots.append(saved.run_state.model_copy(update={"status": RunStatus.COMPLETE}))
    result_ready.set()
    coordinator.observe_completion(run.id)
    try:
        assert checked.wait(3)
        assert coordinator.completion(run.id).result(3).status == RunStatus.COMPLETE
        with pytest.raises(ValueError, match="not owned"):
            coordinator.run(run.id)
    finally:
        assert coordinator.close(3)


def test_failed_resume_can_retry_with_a_new_execution() -> None:
    coordinator = AgentCoordinator()
    original = suspended_agent()
    run = original.start(max_steps=2, coordinator=coordinator)
    assert run.wait_until_settled(3).status == RunStatus.SUSPENDED
    assert run.wait_for_idle(3)
    saved = run.handoff()

    def reject_start(_run: Run) -> None:
        raise ValueError("Cannot construct execution resources")

    restored = Agent(
        FakeModelClient(
            lambda *_: AssistantMessage(content=[TextContent(text="done")])
        ),
        tools=original.tools,
        state=saved.agent_state,
        agent_id=original.id,
    )
    try:
        with pytest.raises(ValueError, match="execution resources"):
            restored.resume(
                saved.run_state,
                coordinator=coordinator.view(
                    ownership=FakeRunOwnership(register=reject_start)
                ),
            )
        with pytest.raises(ValueError, match="not owned"):
            coordinator.run(run.id)
        resumed = restored.resume(saved.run_state, coordinator=coordinator)
        assert resumed is not run and resumed.id == run.id
        resumed.submit(
            HumanToolAnswer(
                request_id="question",
                decision=InputDecision.RESULT,
                result=ToolResult(content="continue"),
            )
        )
        assert resumed.result(3).output.text == "done"
    finally:
        assert coordinator.close(3)


def test_cancelled_suspension_cannot_transfer_execution() -> None:
    coordinator = AgentCoordinator()
    agent = suspended_agent()
    run = agent.start(max_steps=2, coordinator=coordinator)
    assert run.wait_until_settled(3).status == RunStatus.SUSPENDED
    assert run.wait_for_idle(3)
    run.cancel()
    with pytest.raises(RunNotTransferable):
        run.handoff()
    assert coordinator.close(3)
    assert run.status == RunStatus.CANCELLED


def test_shutdown_reservation_prevents_handoff_before_cancellation_callbacks() -> None:
    coordinator = AgentCoordinator()
    agent = suspended_agent()
    run = agent.start(max_steps=2, coordinator=coordinator)
    assert run.wait_until_settled(3).status == RunStatus.SUSPENDED
    assert run.wait_for_idle(3)
    cancel = run.cancel

    def attempt_transfer_then_cancel() -> None:
        with pytest.raises(RunNotTransferable):
            run.handoff()
        cancel()

    with patch.object(run, "cancel", side_effect=attempt_transfer_then_cancel):
        assert coordinator.close(3)
    assert run.status == RunStatus.CANCELLED


@pytest.mark.parametrize("restore_on_other_branch", [False, True])
def test_restoring_history_preserves_branch_latest_run(
    restore_on_other_branch: bool,
) -> None:
    archived = RunState(
        run_id="old",
        agent_id="child",
        status=RunStatus.COMPLETE,
        steps=[],
    )
    current = AgentInfo(
        id="child",
        path="/root/child",
        parent_id="root",
        description="",
        restoration_config=None,
        latest_run_id="new",
        status=RunStatus.COMPLETE,
    )
    owner = AgentCoordinator()
    branch = owner.view(
        directory=FakeAgentDirectory(
            read_run=lambda run_id, _: archived if run_id == archived.run_id else None
        )
    )
    other = owner.view(directory=FakeAgentDirectory())
    branch.register(current)
    other.register(current.model_copy(update={"latest_run_id": archived.run_id}))
    try:
        if restore_on_other_branch:
            restored = other.restore_completed(archived)
            assert branch.child_run(archived.run_id, "root") is restored
        else:
            saved = branch.saved_run(archived.run_id, "root")
            restored = branch.restore_completed(saved)
        assert branch.child_run(archived.run_id, "root") is restored
        assert branch.completion(archived.run_id).result(0) == archived
        assert branch.discovery("root")[0].latest_run_id == current.latest_run_id
        assert other.discovery("root")[0].latest_run_id == archived.run_id
    finally:
        assert owner.close(3)


def test_same_scope_view_observes_completion_of_a_running_child() -> None:
    entered = threading.Event()
    finish = threading.Event()

    def reply(
        _request: GenerationRequest, _signal: CancellationSignal
    ) -> AssistantMessage:
        entered.set()
        assert finish.wait(3)
        return AssistantMessage(content=[TextContent(text="done")])

    child = Agent(FakeModelClient(reply))
    owner = AgentCoordinator(
        agents=[
            AgentInfo(
                id=child.id,
                path="/root/child",
                parent_id="root",
                description="",
                restoration_config=None,
                latest_run_id="previous",
                status=RunStatus.COMPLETE,
            )
        ]
    )
    try:
        run = child.start(max_steps=1, coordinator=owner)
        assert entered.wait(3)
        view = owner.view()
        assert view.discovery("root")[0].latest_run_id == run.id
        finish.set()
        assert run.result(3).output.text == "done"
        assert run.wait_for_idle(3)
        info = view.discovery("root")[0]
        assert info.latest_run_id == run.id
        assert info.status == RunStatus.COMPLETE
    finally:
        finish.set()
        assert owner.close(3)
