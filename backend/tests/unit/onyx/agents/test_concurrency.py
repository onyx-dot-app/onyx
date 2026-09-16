"""Shared workers bound process load and retain cancelled work until actual completion."""

import asyncio
from concurrent.futures import Future
from contextvars import ContextVar
from threading import Event

import pytest

from onyx.agents import concurrency
from onyx.agents.concurrency import ExecutionServices, WorkTracker
from onyx.agents.coordination import AgentCoordinator
from onyx.agents.runtime import Agent
from onyx.agents.tools import AgentTool, ToolInvocation
from onyx.llm.cancellation import AgentCancelled, CancellationSignal
from onyx.llm.models import AssistantMessage, TextContent, ToolCall, ToolResult
from tests.unit.onyx.agents.fakes import FakeModelClient


@pytest.mark.asyncio
async def test_shared_workers_bound_distinct_trees_and_preserve_context(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pool = concurrency._SharedExecutor(1, 2, "test-agent-shared")
    monkeypatch.setattr(concurrency, "_OPERATION_WORKERS", pool)
    tenant = ContextVar("test_worker_tenant", default="unset")
    entered = Event()
    release = Event()
    first_services = ExecutionServices(1)
    second_services = ExecutionServices(1)
    rejected_services = ExecutionServices(1)

    def first_operation() -> str:
        entered.set()
        assert release.wait(3)
        return tenant.get()

    first_token = tenant.set("first")
    first = asyncio.create_task(
        first_services.blocking(first_operation, CancellationSignal())
    )
    tenant.reset(first_token)
    async with asyncio.timeout(2):
        while not entered.is_set():
            await asyncio.sleep(0)
    second_token = tenant.set("second")
    second = asyncio.create_task(
        second_services.blocking(tenant.get, CancellationSignal())
    )
    tenant.reset(second_token)
    try:
        async with asyncio.timeout(2):
            while second_services.tracker.idle:
                await asyncio.sleep(0)
        with pytest.raises(RuntimeError, match="backlog exceeded"):
            await rejected_services.blocking(tenant.get, CancellationSignal())
        assert rejected_services.tracker.idle
    finally:
        release.set()
    assert await first == "first"
    assert await second == "second"
    assert await first_services.wait_idle(1)
    assert await second_services.wait_idle(1)
    pool._executor.shutdown(wait=True)


@pytest.mark.asyncio
async def test_provider_completion_remains_tracked_after_worker_returns() -> None:
    services = ExecutionServices(1)
    signal = CancellationSignal()
    run_work = WorkTracker()
    registered = Event()
    provider_done: Future[None] = Future()
    idle = Event()

    def operation() -> None:
        signal.track_operation(provider_done)
        registered.set()

    await services.blocking(operation, signal, tracker=run_work)
    assert registered.is_set()
    signal.cancel()
    run_work.on_idle(idle.set)
    assert not await services.wait_idle(0.01)
    assert not idle.is_set()
    provider_done.set_result(None)
    assert await services.wait_idle(1)
    assert idle.is_set()


@pytest.mark.asyncio
async def test_cancelled_shared_worker_keeps_tracking_until_exit() -> None:
    services = ExecutionServices(1)
    signal = CancellationSignal()
    entered = Event()
    release = Event()
    idle = Event()

    def operation() -> None:
        entered.set()
        assert release.wait(3)

    running = asyncio.create_task(services.blocking(operation, signal))
    try:
        async with asyncio.timeout(2):
            while not entered.is_set():
                await asyncio.sleep(0)
        signal.cancel()
        with pytest.raises(AgentCancelled):
            await running
        services.tracker.on_idle(idle.set)
        assert not await services.wait_idle(0.01)
        assert not idle.is_set()
    finally:
        release.set()
    assert await services.wait_idle(1)
    assert idle.is_set()


@pytest.mark.asyncio
async def test_async_tool_admission_leaves_capacity_for_child_models() -> None:
    active = 0
    peak = 0
    completed: list[str] = []

    async def coordinate(invocation: ToolInvocation) -> ToolResult:
        nonlocal active, peak
        active += 1
        peak = max(peak, active)
        try:
            child = Agent(
                FakeModelClient(
                    lambda *_: AssistantMessage(content=[TextContent(text="child")])
                )
            )
            spawned = await invocation.agents.spawn_agent(
                child,
                name=invocation.call_id,
                description="Child model work",
                messages=[],
                max_steps=1,
            )
            result = await invocation.agents.wait_run(spawned.run_id, timeout=2)
            assert result is not None and result.output.text == "child"
            completed.append(invocation.call_id)
            return ToolResult(content="done")
        finally:
            active -= 1

    replies = iter(
        [
            AssistantMessage(
                content=[
                    ToolCall(id=name, name="coordinate", arguments={})
                    for name in ("first", "second", "third")
                ]
            ),
            AssistantMessage(content=[TextContent(text="finished")]),
        ]
    )
    agent = Agent(
        FakeModelClient(lambda *_: next(replies)),
        max_parallel_operations=1,
        tools=[
            AgentTool(
                name="coordinate",
                description="Run a child model",
                parameters={},
                execute_async=coordinate,
            )
        ],
    )
    run = agent.start(max_steps=2, coordinator=AgentCoordinator())
    result = await run.wait(timeout=3)
    assert result.output.text == "finished"
    assert peak == 1
    assert completed == ["first", "second", "third"]
    assert await run.wait_for_idle(timeout=2)
