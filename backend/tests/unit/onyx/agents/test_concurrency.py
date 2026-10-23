"""Thread ownership, nesting, and context isolation without worker admission."""

import threading
from concurrent.futures import Future
from contextvars import ContextVar
from unittest.mock import patch

import pytest
from pydantic import BaseModel

from onyx.agents import concurrency, runtime
from onyx.agents.agent_coordination import AgentCoordinator
from onyx.agents.concurrency import ExecutionWork
from onyx.agents.events import (
    AgentEvent,
    AgentStartEvent,
    MessageUpdateEvent,
    ToolUpdateEvent,
)
from onyx.agents.execution_records import RunStatus
from onyx.agents.models import ToolCallContext
from onyx.agents.runtime import Agent, RunFailed
from onyx.agents.tool_execution import ToolBatch
from onyx.agents.tools import AgentTool, ToolInvocation, ToolProgress
from onyx.context.search.models import SearchDocsResponse
from onyx.llm.cancellation import AgentCancelled, CancellationSignal
from onyx.llm.models import (
    AssistantMessage,
    GenerationContentEvent,
    GenerationRequestParams,
    ReasoningEffort,
    TextContent,
    TextDeltaEvent,
    ThinkingBlock,
    ThinkingDeltaEvent,
    ToolCall,
    ToolCallDeltaEvent,
    ToolCallEndEvent,
    ToolDefinition,
    ToolResult,
)
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


def test_registered_completion_remains_tracked_after_cancellation() -> None:
    work = ExecutionWork()
    signal = CancellationSignal()
    provider_done: Future[None] = Future()
    work.track_operation(provider_done)
    signal.cancel()
    assert not work.tracker.wait_idle(0)
    provider_done.set_result(None)
    assert work.tracker.wait_idle(1)


def test_cancelled_wait_keeps_job_tracked_until_completion() -> None:
    work = ExecutionWork()
    signal = CancellationSignal()
    entered, release = threading.Event(), threading.Event()

    def operation() -> None:
        entered.set()
        assert release.wait(3)

    job = work.start(operation)
    waiting = start_thread_future(
        lambda: concurrency.wait_operation(job, signal), name="test-wait"
    )
    try:
        assert entered.wait(2)
        signal.cancel()
        with pytest.raises(AgentCancelled):
            waiting.result(2)
        assert not work.tracker.wait_idle(0)
    finally:
        release.set()
    job.result(2)
    assert work.tracker.wait_idle(2)


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
                AgentTool(
                    definition=ToolDefinition(
                        name="leaf", description="", parameters={}
                    ),
                    execute=delegate,
                )
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
            AgentTool(
                definition=ToolDefinition(name="parent", description="", parameters={}),
                execute=parent_tool,
            )
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
    assert work.start(lambda: "usable").result(2) == "usable"


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
            AgentTool(
                definition=ToolDefinition(
                    name="delegate", description="", parameters={}
                ),
                execute=delegate,
            )
        ],
    )
    run = root.start(max_steps=1, coordinator=coordinator)
    run.result(3)
    assert run.wait_for_idle(2)
    assert runtime.start_thread_with_context is original


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

    def before_call(context: ToolCallContext) -> None:
        if context.call.name == "fail":
            assert tool_entered.wait(5)
            raise ValueError("Tool hook failed")

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
            AgentTool(
                definition=ToolDefinition(name="late", description="", parameters={}),
                execute=late,
            ),
            AgentTool(
                definition=ToolDefinition(name="fail", description="", parameters={}),
                execute=lambda _: ToolResult(content="unused"),
            ),
        ],
    )
    agent.before_tool_call = before_call
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
    from onyx.agents.models import AgentInfo
    from onyx.agents.runtime import Run

    status_entered, release_status = threading.Event(), threading.Event()
    release_model = threading.Event()

    def reply(*_: object) -> AssistantMessage:
        assert release_model.wait(5)
        return AssistantMessage(content=[TextContent(text="done")])

    agent = Agent(FakeModelClient(reply))
    coordinator = AgentCoordinator()
    coordinator.register(
        AgentInfo(
            id=agent.id,
            path="/root/child",
            parent_id="root",
            description="",
            restoration_config=None,
        )
    )
    run = agent.start(max_steps=1, coordinator=coordinator)

    def status(current: Run) -> RunStatus:
        status_entered.set()
        assert release_status.wait(5)
        return current.snapshot().status

    monkeypatch.setattr(Run, "status", property(status))
    discovery = start_thread_future(
        lambda: coordinator.discover_children("root"), name="test-discovery"
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


def test_shared_dispatcher_drains_combined_burst_in_order() -> None:
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
        expected = [str(index) for index in range(4096)]
        for index, run_id in enumerate(expected):
            channel = first if index % 2 == 0 else second
            channel.publish(AgentStartEvent(run_id=run_id))
        assert dispatcher.has_pending_events
        assert not first.failed.is_set()
        assert not second.failed.is_set()
        release.set()
        first.close()
        second.close()
        assert received == ["blocked", *expected]
        assert not first.failed.is_set()
        assert not second.failed.is_set()
        assert not dispatcher.has_pending_events
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


def test_progress_delivery_isolates_producer_and_listeners() -> None:
    dispatcher = concurrency.EventDispatcher()
    delivery = concurrency.EventDelivery(dispatcher)
    entered = threading.Event()
    release = threading.Event()
    received: list[list[str]] = []

    def mutate(event: AgentEvent) -> None:
        if isinstance(event, AgentStartEvent):
            entered.set()
            assert release.wait(3)
        if isinstance(event, ToolUpdateEvent):
            details = event.progress.details
            assert isinstance(details, SearchDocsResponse)
            details.queries.append("listener mutation")

    def observe(event: AgentEvent) -> None:
        if isinstance(event, ToolUpdateEvent):
            details = event.progress.details
            assert isinstance(details, SearchDocsResponse)
            received.append(list(details.queries))

    delivery.subscribe(mutate)
    delivery.subscribe(observe)
    try:
        delivery.publish(AgentStartEvent(run_id="run"))
        assert entered.wait(2)
        details = SearchDocsResponse(
            search_docs=[], citation_mapping={}, queries=["first"]
        )
        delivery.publish(
            ToolUpdateEvent(
                run_id="run",
                message_id="message",
                step_index=0,
                tool_call=ToolCall(id="call", name="search", arguments={}),
                progress=ToolProgress(details=details),
            )
        )
        details.queries.append("producer mutation")
        release.set()
        delivery.close()
        assert received == [["first"]]
        assert details.queries == ["first", "producer mutation"]
    finally:
        release.set()
        delivery.close()
        dispatcher.close()


def test_child_delivery_copies_only_for_actual_listeners() -> None:
    dispatcher = concurrency.EventDispatcher()
    parent = concurrency.EventDelivery(dispatcher)
    child = concurrency.EventDelivery(parent=parent)
    grandchild = concurrency.EventDelivery(parent=child)
    received: list[str] = []
    parent.subscribe(lambda event: received.append(event.run_id))
    try:
        with patch.object(
            AgentStartEvent,
            "model_copy",
            autospec=True,
            side_effect=AgentStartEvent.model_copy,
        ) as copy_event:
            grandchild.publish(AgentStartEvent(run_id="grandchild"))
            assert grandchild.tracker.wait_idle(2)
            assert child.tracker.wait_idle(2)
            assert parent.tracker.wait_idle(2)
            assert received == ["grandchild"]
            # Queue ownership requires one copy; empty delivery channels require none.
            assert copy_event.call_count == 1
    finally:
        grandchild.close()
        child.close()
        parent.close()
        dispatcher.close()


@pytest.mark.parametrize(
    "update",
    [
        TextDeltaEvent(content_index=0, text="Answer"),
        TextDeltaEvent(content_index=0, text=""),
        ThinkingDeltaEvent(content_index=0, text="Reasoning"),
        ToolCallDeltaEvent(content_index=0, arguments_delta='{"query":'),
    ],
)
def test_deltas_are_shared_across_listeners_and_ancestors(
    update: GenerationContentEvent,
) -> None:
    event = MessageUpdateEvent(
        run_id="child", message_id="message", step_index=0, generation_event=update
    )
    dispatcher = concurrency.EventDispatcher()
    parent = concurrency.EventDelivery(dispatcher)
    child = concurrency.EventDelivery(parent=parent)
    received: list[AgentEvent] = []
    child.subscribe(received.append)
    child.subscribe(received.append)
    parent.subscribe(received.append)
    try:
        with (
            patch.object(
                BaseModel, "model_dump", side_effect=AssertionError("Unexpected dump")
            ) as dump,
            patch.object(
                BaseModel, "model_copy", side_effect=AssertionError("Unexpected copy")
            ) as copy,
        ):
            child.publish(event)
            assert child.tracker.wait_idle(2)
            assert parent.tracker.wait_idle(2)
            assert not child.failed.is_set()
            assert not parent.failed.is_set()
            assert len(received) == 3
            assert all(item is event for item in received)
            dump.assert_not_called()
            copy.assert_not_called()
    finally:
        child.close()
        parent.close()
        dispatcher.close()


@pytest.mark.parametrize(
    "update",
    [
        TextDeltaEvent(
            content_index=0,
            text="Answer",
            request_params=GenerationRequestParams(
                model_name="test",
                model_provider="test",
                reasoning_effort=ReasoningEffort.AUTO,
                max_tokens=None,
                sent_kwargs={"temperature": 0},
            ),
        ),
        ThinkingDeltaEvent(content_index=0, text="Reasoning", blocks=[]),
        ThinkingDeltaEvent(
            content_index=0,
            blocks=[ThinkingBlock(thinking="Reasoning", signature="signature")],
        ),
        ToolCallEndEvent(
            content_index=0, tool_call=ToolCall(id="call", name="search", arguments={})
        ),
    ],
)
def test_mutable_generation_payloads_are_isolated(
    update: GenerationContentEvent,
) -> None:
    event = MessageUpdateEvent(
        run_id="child", message_id="message", step_index=0, generation_event=update
    )
    expected = event.model_copy(deep=True)
    dispatcher = concurrency.EventDispatcher()
    parent = concurrency.EventDelivery(dispatcher)
    child = concurrency.EventDelivery(parent=parent)
    entered = threading.Event()
    release = threading.Event()
    received: list[MessageUpdateEvent] = []

    def mutate_payload(event: MessageUpdateEvent, value: str) -> None:
        payload = event.generation_event
        if isinstance(payload, TextDeltaEvent):
            assert payload.request_params is not None
            payload.request_params.sent_kwargs["mutation"] = value
        elif isinstance(payload, ThinkingDeltaEvent):
            assert payload.blocks is not None
            payload.blocks.append(ThinkingBlock(thinking=value))
        else:
            assert isinstance(payload, ToolCallEndEvent)
            payload.tool_call.arguments["mutation"] = value

    def mutate(event: AgentEvent) -> None:
        if isinstance(event, AgentStartEvent):
            entered.set()
            assert release.wait(3)
        elif isinstance(event, MessageUpdateEvent):
            mutate_payload(event, "listener")

    def observe(event: AgentEvent) -> None:
        if isinstance(event, MessageUpdateEvent):
            received.append(event)

    child.subscribe(mutate)
    child.subscribe(observe)
    parent.subscribe(observe)
    try:
        child.publish(AgentStartEvent(run_id="blocked"))
        assert entered.wait(2)
        child.publish(event)
        mutate_payload(event, "producer")
        release.set()
        assert child.tracker.wait_idle(2)
        assert parent.tracker.wait_idle(2)
        assert not child.failed.is_set()
        assert not parent.failed.is_set()
        assert received == [expected, expected]
        assert received[0] is not received[1]
    finally:
        release.set()
        child.close()
        parent.close()
        dispatcher.close()


@pytest.mark.parametrize("extend_envelope", [False, True])
def test_extended_events_keep_snapshot_isolation(extend_envelope: bool) -> None:
    class AnnotatedDelta(TextDeltaEvent):
        notes: list[str]

    class AnnotatedUpdate(MessageUpdateEvent):
        notes: list[str]

    event: MessageUpdateEvent
    if extend_envelope:
        extended = AnnotatedUpdate(
            run_id="run",
            message_id="message",
            step_index=0,
            generation_event=TextDeltaEvent(content_index=0, text="Answer"),
            notes=[],
        )
        event = extended
        notes = extended.notes
    else:
        update = AnnotatedDelta(content_index=0, text="Answer", notes=[])
        event = MessageUpdateEvent(
            run_id="run", message_id="message", step_index=0, generation_event=update
        )
        notes = update.notes
    expected = event.model_copy(deep=True)
    delivery = concurrency.EventDelivery()
    entered = threading.Event()
    release = threading.Event()
    received: list[AgentEvent] = []

    def observe(event: AgentEvent) -> None:
        if isinstance(event, AgentStartEvent):
            entered.set()
            assert release.wait(3)
        else:
            received.append(event)

    delivery.subscribe(observe)
    try:
        delivery.publish(AgentStartEvent(run_id="blocked"))
        assert entered.wait(2)
        delivery.publish(event)
        notes.append("producer mutation")
        release.set()
        assert delivery.tracker.wait_idle(2)
        assert not delivery.failed.is_set()
        assert received == [expected]
        assert received[0] is not event
    finally:
        release.set()
        delivery.close()


def test_empty_event_remains_pending_until_ancestor_delivery_finishes() -> None:
    dispatcher = concurrency.EventDispatcher()
    parent = concurrency.EventDelivery(dispatcher)
    child = concurrency.EventDelivery(parent=parent)
    entered = threading.Event()
    release = threading.Event()

    def observe(_event: AgentEvent) -> None:
        entered.set()
        assert release.wait(3)

    parent.subscribe(observe)
    try:
        child.publish(AgentStartEvent(run_id="child"))
        assert entered.wait(2)
        assert dispatcher.has_pending_events
        assert not child.tracker.wait_idle(0)
        assert not parent.tracker.wait_idle(0)
        release.set()
        assert parent.tracker.wait_idle(2)
        assert child.tracker.wait_idle(2)
        assert not dispatcher.has_pending_events
    finally:
        release.set()
        child.close()
        parent.close()
        dispatcher.close()


def test_large_event_is_delivered_without_serialization() -> None:
    dispatcher = concurrency.EventDispatcher()
    delivery = concurrency.EventDelivery(dispatcher)
    received: list[AgentEvent] = []
    delivery.subscribe(received.append)
    event = MessageUpdateEvent(
        run_id="run",
        message_id="message",
        step_index=0,
        generation_event=ToolCallEndEvent(
            content_index=0,
            tool_call=ToolCall(
                id="call", name="search", arguments={"query": "a" * (5 * 1024 * 1024)}
            ),
        ),
    )
    try:
        with patch.object(
            BaseModel, "model_dump", side_effect=AssertionError("Unexpected dump")
        ):
            delivery.publish(event)
        assert delivery.tracker.wait_idle(2)
        assert not delivery.failed.is_set()
        assert received == [event]
        assert not dispatcher.has_pending_events
    finally:
        delivery.close()
        dispatcher.close()
