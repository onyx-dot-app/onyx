"""Thread ownership, nesting, and context isolation without worker admission."""

import threading
from concurrent.futures import Future
from contextvars import ContextVar

import pytest

from onyx.agents import concurrency, runtime
from onyx.agents.agent_coordination import AgentCoordinator
from onyx.agents.concurrency import ExecutionWork
from onyx.agents.events import AgentEvent, AgentStartEvent
from onyx.agents.runtime import Agent, RunFailed
from onyx.agents.tool_execution import ToolBatch
from onyx.agents.tools import AgentTool, ToolInvocation
from onyx.llm.cancellation import AgentCancelled, CancellationSignal
from onyx.llm.models import AssistantMessage, TextContent, ToolCall, ToolResult
from onyx.utils.threadpool_concurrency import start_thread_future
from tests.unit.onyx.agents.fakes import FakeModelClient


def test_distinct_jobs_start_independently_and_preserve_context() -> None:
    tenant = ContextVar("test_worker_tenant", default="unset")
    release = threading.Event()
    entered = threading.Barrier(13)
    work = ExecutionWork()

    def operation() -> str:
        entered.wait(timeout=3)
        assert release.wait(3)
        return tenant.get()

    jobs: list[Future[str]] = []
    try:
        for index in range(12):
            token = tenant.set(str(index))
            try:
                jobs.append(work.start(operation))
            finally:
                tenant.reset(token)
        entered.wait(timeout=3)
        assert not work.tracker.wait_idle(timeout=0)
    finally:
        release.set()
    assert [job.result(3) for job in jobs] == [str(index) for index in range(12)]
    assert work.tracker.wait_idle(2)
    assert tenant.get() == "unset"


def test_provider_completion_remains_tracked_after_worker_returns() -> None:
    work = ExecutionWork()
    signal = CancellationSignal()
    provider_done: Future[None] = Future()
    work.blocking(lambda: signal.track_operation(provider_done), signal)
    signal.cancel()
    assert not work.tracker.wait_idle(0)
    provider_done.set_result(None)
    assert work.tracker.wait_idle(1)


@pytest.mark.parametrize("fails", [False, True])
def test_cancelled_job_keeps_ownership_and_reports_late_failure(
    fails: bool, caplog: pytest.LogCaptureFixture
) -> None:
    work = ExecutionWork()
    signal = CancellationSignal()
    entered, release = threading.Event(), threading.Event()

    def operation() -> None:
        entered.set()
        assert release.wait(3)
        if fails:
            raise ValueError("late worker failure")

    waiting = start_thread_future(
        lambda: work.blocking(operation, signal), name="test-wait"
    )
    try:
        assert entered.wait(2)
        signal.cancel()
        with pytest.raises(AgentCancelled):
            waiting.result(2)
        assert not work.tracker.wait_idle(0)
    finally:
        release.set()
    assert work.tracker.wait_idle(2)
    assert sum(
        record.message == "Agent worker failed after its caller stopped waiting"
        for record in caplog.records
    ) == int(fails)


def test_nested_parallel_children_and_grandchildren_keep_context() -> None:
    tenant = ContextVar("test_nested_tenant", default="root")
    barrier = threading.Barrier(6)
    observed: list[str] = []
    lock = threading.Lock()

    def leaf_reply(*_: object) -> AssistantMessage:
        barrier.wait(timeout=3)
        with lock:
            observed.append(tenant.get())
        return AssistantMessage(content=[TextContent(text=tenant.get())])

    def delegate(invocation: ToolInvocation) -> ToolResult:
        token = tenant.set(invocation.call_id)
        try:
            child = Agent(FakeModelClient(leaf_reply))
            spawned = invocation.agents.spawn_agent(
                child, name=invocation.call_id, description="", messages=[], max_steps=1
            )
            result = invocation.agents.wait_run(spawned.run_id, timeout=4)
            assert result is not None
            return ToolResult(content=result.output.text)
        finally:
            tenant.reset(token)

    def parent_tool(invocation: ToolInvocation) -> ToolResult:
        child = Agent(
            FakeModelClient(
                lambda *_: AssistantMessage(
                    content=[
                        ToolCall(
                            id=f"{invocation.call_id}-{i}", name="leaf", arguments={}
                        )
                        for i in range(2)
                    ]
                )
            ),
            tools=[
                AgentTool(name="leaf", description="", parameters={}, execute=delegate)
            ],
        )
        spawned = invocation.agents.spawn_agent(
            child, name=invocation.call_id, description="", messages=[], max_steps=1
        )
        assert invocation.agents.wait_run(spawned.run_id, timeout=5) is not None
        return ToolResult(content="done")

    root = Agent(
        FakeModelClient(
            lambda *_: AssistantMessage(
                content=[
                    ToolCall(id=str(i), name="parent", arguments={}) for i in range(3)
                ]
            )
        ),
        tools=[
            AgentTool(name="parent", description="", parameters={}, execute=parent_tool)
        ],
    )
    run = root.start(max_steps=1, coordinator=AgentCoordinator())
    run.result(6)
    assert run.wait_for_idle(2)
    assert sorted(observed) == [f"{i}-{j}" for i in range(3) for j in range(2)]
    assert tenant.get() == "root"


def test_thread_start_failure_releases_job_ownership(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    work = ExecutionWork()

    def fail(*_args: object, **_kwargs: object) -> None:
        raise RuntimeError("cannot start thread")

    with monkeypatch.context() as patch:
        patch.setattr(concurrency, "start_thread_future", fail)
        with pytest.raises(RuntimeError, match="cannot start thread"):
            work.start(lambda: None)
    assert work.tracker.wait_idle(timeout=0)
    assert work.blocking(lambda: "usable", CancellationSignal()) == "usable"


def test_child_thread_start_failure_rolls_back_registration(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    child = Agent(
        FakeModelClient(
            lambda *_: AssistantMessage(content=[TextContent(text="child")])
        )
    )
    coordinator = AgentCoordinator()
    original = runtime.start_thread_with_context

    def delegate(invocation: ToolInvocation) -> ToolResult:
        def fail(*_args: object, **_kwargs: object) -> None:
            raise RuntimeError("cannot start child")

        with monkeypatch.context() as patch:
            patch.setattr(runtime, "start_thread_with_context", fail)
            with pytest.raises(RuntimeError, match="cannot start child"):
                invocation.agents.spawn_agent(
                    child, name="child", description="", messages=[], max_steps=1
                )
        assert coordinator.registration(child.id) is None
        assert coordinator.active_run(child.id) is None
        assert child.id not in coordinator._state.latest
        spawned = invocation.agents.spawn_agent(
            child, name="child", description="", messages=[], max_steps=1
        )
        assert invocation.agents.wait_run(spawned.run_id, timeout=2) is not None
        return ToolResult(content="recovered")

    root = Agent(
        FakeModelClient(
            lambda *_: AssistantMessage(
                content=[ToolCall(id="call", name="delegate", arguments={})]
            )
        ),
        tools=[
            AgentTool(name="delegate", description="", parameters={}, execute=delegate)
        ],
    )
    run = root.start(max_steps=1, coordinator=coordinator)
    run.result(3)
    assert run.wait_for_idle(2)
    assert runtime.start_thread_with_context is original


def test_preparation_preserves_outer_provider_ownership() -> None:
    work = ExecutionWork()
    signal = CancellationSignal()
    completion: Future[None] = Future()
    try:
        with signal.on_operation(work.track_operation):
            work.blocking(lambda: None, signal)
            signal.track_operation(completion)
        assert not work.tracker.wait_idle(0)
    finally:
        completion.set_result(None)
    assert work.tracker.wait_idle(1)


def test_cancelled_callback_retains_late_provider_cleanup() -> None:
    work = ExecutionWork()
    signal = CancellationSignal()
    entered, release, registered = (
        threading.Event(),
        threading.Event(),
        threading.Event(),
    )
    completion: Future[None] = Future()

    def callback() -> None:
        entered.set()
        assert release.wait(3)
        signal.track_operation(completion)
        registered.set()

    with signal.on_operation(work.track_operation):
        waiting = start_thread_future(
            lambda: work.blocking(callback, signal), name="test-preparation"
        )
        assert entered.wait(2)
        signal.cancel()
        with pytest.raises(AgentCancelled):
            waiting.result(2)
    try:
        release.set()
        assert registered.wait(2)
        assert not work.tracker.wait_idle(0)
    finally:
        release.set()
        completion.set_result(None)
    assert work.tracker.wait_idle(2)


def test_terminal_snapshot_rejects_late_tool_result(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tool_entered, release_tool, recorded = (
        threading.Event(),
        threading.Event(),
        threading.Event(),
    )

    def late(_invocation: ToolInvocation) -> ToolResult:
        tool_entered.set()
        assert release_tool.wait(5)
        return ToolResult(content="late result")

    def fail(_invocation: ToolInvocation) -> ToolResult:
        assert tool_entered.wait(5)
        raise ValueError("sibling failed")

    agent = Agent(
        FakeModelClient(
            lambda *_: AssistantMessage(
                content=[
                    ToolCall(id="late", name="late", arguments={}),
                    ToolCall(id="fail", name="fail", arguments={}),
                ]
            )
        ),
        tools=[
            AgentTool(name="late", description="", parameters={}, execute=late),
            AgentTool(name="fail", description="", parameters={}, execute=fail),
        ],
    )
    original_record = ToolBatch._record_tool_result

    def record_result(
        execution: ToolBatch,
        result: ToolResult,
        call: ToolCall,
    ) -> None:
        try:
            original_record(execution, result, call)
        finally:
            recorded.set()

    monkeypatch.setattr(ToolBatch, "_record_tool_result", record_result)
    run = agent.start(max_steps=1)
    try:
        with pytest.raises(RunFailed):
            run.result(3)
        terminal = run.snapshot()
        release_tool.set()
        assert recorded.wait(3)
        assert run.snapshot() == terminal
    finally:
        release_tool.set()
        assert run.wait_for_idle(3)
    with pytest.raises(RunFailed):
        run.result(1)
    assert agent.state.messages == run.snapshot().messages


def test_discovery_reads_run_status_without_holding_coordinator_lock(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from onyx.agents.execution_records import RunStatus
    from onyx.agents.models import AgentInfo
    from onyx.agents.runtime import Run

    status_entered, release_status = threading.Event(), threading.Event()
    release_model = threading.Event()

    def reply(*_: object) -> AssistantMessage:
        assert release_model.wait(5)
        return AssistantMessage(content=[TextContent(text="done")])

    agent = Agent(FakeModelClient(reply))
    coordinator = AgentCoordinator(
        agents=[
            AgentInfo(
                id=agent.id,
                path="/root/child",
                parent_id="root",
                description="",
                restoration_config=None,
            )
        ]
    )
    run = agent.start(max_steps=1, coordinator=coordinator)

    def status(current: Run) -> RunStatus:
        status_entered.set()
        assert release_status.wait(5)
        return current.snapshot().status

    monkeypatch.setattr(Run, "status", property(status))
    discovery = start_thread_future(
        lambda: coordinator.discovery("root"), name="test-discovery"
    )
    try:
        assert status_entered.wait(2)
        registration = start_thread_future(
            lambda: coordinator.registration(agent.id), name="test-registration"
        )
        assert registration.result(1) is not None
    finally:
        release_status.set()
        release_model.set()
        discovery.result(3)
        assert run.wait_for_idle(3)


def test_delivery_reuses_one_thread_between_events(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from collections.abc import Callable
    from contextvars import Context

    from onyx.agents.events import AgentStartEvent

    original = concurrency.start_thread_with_context
    started: list[str | None] = []

    def start(
        target: Callable[[], None],
        *,
        name: str | None = None,
        daemon: bool = False,
        context: Context | None = None,
    ) -> threading.Thread:
        started.append(name)
        return original(target, name=name, daemon=daemon, context=context)

    monkeypatch.setattr(concurrency, "start_thread_with_context", start)
    delivery = concurrency.EventDelivery()
    received = threading.Event()
    delivery.subscribe(lambda _event: received.set())
    try:
        for _ in range(20):
            received.clear()
            delivery.publish(AgentStartEvent(agent_id="agent", run_id="run"))
            assert received.wait(2)
    finally:
        delivery.close()
    assert delivery.tracker.wait_idle(timeout=0)
    assert started == ["agent-events"]


def test_parent_listener_failure_keeps_child_result_and_idle() -> None:
    from onyx.agents.events import AgentEvent

    def fail(_event: AgentEvent) -> None:
        raise ValueError("delivery failed")

    agent = Agent(
        FakeModelClient(
            lambda *_: AssistantMessage(content=[TextContent(text="answer")])
        )
    )
    parent = concurrency.EventDelivery()
    parent.subscribe(fail)
    run = agent.start(max_steps=1, _event_parent=parent)
    assert run.result(2).output.text == "answer"
    assert run.wait_for_idle(2)
    assert parent.failed.is_set()
    assert not run.delivery_failed
    parent.close()


def test_paused_delivery_drains_late_child_events_without_retaining_worker() -> None:
    entered = threading.Event()
    release = threading.Event()
    received: list[str] = []
    delivery = concurrency.EventDelivery()

    def receive(event: AgentEvent) -> None:
        if event.run_id == "parent":
            entered.set()
            assert release.wait(2)
        received.append(event.run_id)

    delivery.subscribe(receive)
    try:
        delivery.publish(AgentStartEvent(run_id="parent"))
        assert entered.wait(2)
        delivery.pause()
        delivery.publish(AgentStartEvent(run_id="child"))
        release.set()
        assert delivery.tracker.wait_idle(2)
        assert received == ["parent", "child"]
        delivery.resume()
        delivery.publish(AgentStartEvent(run_id="resumed"))
    finally:
        release.set()
        delivery.close()
    assert received == ["parent", "child", "resumed"]


def test_shared_dispatcher_keeps_channel_context_and_independent_completion() -> None:
    tenant = ContextVar("test_delivery_tenant", default="unset")
    dispatcher = concurrency.EventDispatcher()
    token = tenant.set("first")
    first = concurrency.EventDelivery(dispatcher)
    tenant.set("second")
    second = concurrency.EventDelivery(dispatcher)
    tenant.reset(token)
    entered = threading.Event()
    release = threading.Event()
    received: list[tuple[str, str, int]] = []
    drained_contexts: list[str] = []

    def receive(event: AgentEvent) -> None:
        assert first.is_dispatch_thread
        assert second.is_dispatch_thread
        received.append((event.run_id, tenant.get(), threading.get_ident()))
        if event.run_id == "blocked":
            entered.set()
            assert release.wait(3)

    first.subscribe(receive)
    second.subscribe(receive)
    try:
        first.publish(AgentStartEvent(run_id="first"))
        second.publish(AgentStartEvent(run_id="blocked"))
        assert entered.wait(2)
        first.close()
        assert first.tracker.wait_idle(timeout=0)
        assert not second.tracker.wait_idle(timeout=0)
        second.tracker.on_idle(lambda: drained_contexts.append(tenant.get()))
        assert not first.failed.is_set()
        second.publish(AgentStartEvent(run_id="last"))
        release.set()
        second.close()
        assert [(run, context) for run, context, _ in received] == [
            ("first", "first"),
            ("blocked", "second"),
            ("last", "second"),
        ]
        assert len({worker for _, _, worker in received}) == 1
        assert drained_contexts == ["second"]
    finally:
        release.set()
        first.close()
        second.close()
        dispatcher.close()


def test_shared_dispatcher_bounds_combined_backlog(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(concurrency, "EVENT_QUEUE_CAPACITY", 1)
    dispatcher = concurrency.EventDispatcher()
    first = concurrency.EventDelivery(dispatcher)
    second = concurrency.EventDelivery(dispatcher)
    entered = threading.Event()
    release = threading.Event()
    received: list[str] = []

    def receive(event: AgentEvent) -> None:
        if event.run_id == "blocked":
            entered.set()
            assert release.wait(3)
        received.append(event.run_id)

    first.subscribe(receive)
    second.subscribe(receive)
    try:
        first.publish(AgentStartEvent(run_id="blocked"))
        assert entered.wait(2)
        second.publish(AgentStartEvent(run_id="accepted"))
        first.publish(AgentStartEvent(run_id="overflow"))
        assert first.failed.is_set()
        assert not second.failed.is_set()
        release.set()
        first.close()
        second.close()
        assert received == ["blocked", "accepted"]
        assert first.tracker.wait_idle(timeout=0)
        assert second.tracker.wait_idle(timeout=0)
    finally:
        release.set()
        first.close()
        second.close()
        dispatcher.close()


def test_child_events_use_one_queue_entry_and_reach_late_parent_listener() -> None:
    dispatcher = concurrency.EventDispatcher()
    parent = concurrency.EventDelivery(dispatcher)
    child = concurrency.EventDelivery(parent=parent)
    entered = threading.Event()
    release = threading.Event()
    local: list[str] = []
    ancestors: list[str] = []

    def block_first(event: AgentEvent) -> None:
        if event.run_id == "parent":
            entered.set()
            assert release.wait(2)

    parent.subscribe(block_first)
    child.subscribe(lambda event: local.append(event.run_id))
    try:
        parent.publish(AgentStartEvent(agent_id="parent", run_id="parent"))
        assert entered.wait(2)
        child.publish(AgentStartEvent(agent_id="child", run_id="child"))
        with dispatcher._condition:
            assert len(dispatcher._queue) == 1
        parent.subscribe(lambda event: ancestors.append(event.run_id))
        release.set()
        assert child.tracker.wait_idle(2)
        assert parent.tracker.wait_idle(2)
        assert local == ["child"]
        assert ancestors == ["child"]
    finally:
        release.set()
        child.close()
        parent.close()
        dispatcher.close()
