"""Children share execution semantics and retain identity across parent runs."""

import asyncio
import threading
from collections.abc import Awaitable, Callable, Generator
from unittest.mock import patch

import pytest

from onyx.agents.concurrency import ExecutionWork
from onyx.agents.coordination import AgentCoordinator, AgentInfo, RunCoordination
from onyx.agents.events import AgentEvent, MessageEndEvent
from onyx.agents.items import messages_from_items
from onyx.agents.models import PreparedStep, RunSnapshot, StepInput
from onyx.agents.runtime import Agent, Run, RunFailed
from onyx.agents.tools import AgentControl, AgentTool, SpawnResult, ToolInvocation
from onyx.agents.transcript import RunFailureKind, RunStatus
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
from tests.unit.onyx.agents.fakes import FakeModelClient, run_agent


def parent_agent(execute: Callable[[ToolInvocation], Awaitable[ToolResult]]) -> Agent:
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
        tools=[
            AgentTool(
                name="coordinate",
                description="Coordinate child work",
                parameters={},
                execute_async=execute,
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

    async def retrieve(invocation: ToolInvocation) -> ToolResult:
        with pytest.raises(RunFailed) as saved:
            await invocation.agents.wait_run(transcript.run_id, timeout=2)
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
        read_run=lambda *_: transcript,
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

    async def coordinate(invocation: ToolInvocation) -> ToolResult:
        nonlocal spawned, prior_control
        if spawned is None:
            prior_control = invocation.agents
            spawned = await invocation.agents.spawn_agent(
                child,
                name="research",
                description="Facts",
                messages=[initial],
                max_steps=2,
            )
            initial.content = "changed caller copy"
            result = await invocation.agents.wait_run(spawned.run_id, timeout=3)
            assert result is not None and result.output.text == "answer 1"
            result.output.content.clear()
        else:
            assert prior_control is not None
            with pytest.raises(RuntimeError):
                await prior_control.start_run(child.id, messages=[], max_steps=1)
            previous = await invocation.agents.wait_run(spawned.run_id, timeout=0)
            assert previous is not None and previous.output.text == "answer 1"
            next_id = await invocation.agents.start_run(
                child.id, messages=[UserMessage(content="second task")], max_steps=1
            )
            result = await invocation.agents.wait_run(next_id, timeout=3)
            assert result is not None and result.output.text == "answer 2"
        return ToolResult(content="child finished")

    async def exercise() -> None:
        parent = parent_agent(coordinate)
        coordinator = AgentCoordinator()
        first = parent.start(max_steps=2, coordinator=coordinator)
        await first.wait()
        assert await first.wait_for_idle(timeout=3)
        before = first.snapshot()
        second = parent.start(max_steps=2, coordinator=coordinator)
        await second.wait()
        assert await second.wait_for_idle(timeout=3)
        assert first.snapshot() == before
        after = second.snapshot()
        assert before.child_runs[0].input_messages[0].text == "first task"
        assert after.child_runs[0].input_messages[0].text == "second task"
        assert after.child_runs[0].previous_run_id == before.child_runs[0].run_id
        assert before.child_runs[0].parent_tool_call_id == "first"
        assert after.child_runs[0].parent_message_id == f"{second.id}:0"
        assert coordinator.discovery(parent.id)[0].id == child.id
        assert await coordinator.close(timeout=3)

    asyncio.run(exercise())
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

    async def coordinate(invocation: ToolInvocation) -> ToolResult:
        spawned = await invocation.agents.spawn_agent(
            child,
            name="research",
            description="Facts",
            messages=[UserMessage(content="accepted")],
            max_steps=1,
        )
        async with asyncio.timeout(2):
            while not entered.is_set():
                await asyncio.sleep(0.01)
        assert await invocation.agents.wait_run(spawned.run_id, timeout=0) is None
        with pytest.raises(RuntimeError):
            await invocation.agents.start_run(
                child.id, messages=[UserMessage(content="rejected")], max_steps=1
            )
        with pytest.raises(ValueError):
            await invocation.agents.start_run("unknown", messages=[], max_steps=1)
        release.set()
        assert await invocation.agents.wait_run(spawned.run_id, timeout=3) is not None
        return ToolResult(content="done")

    parent = parent_agent(coordinate)
    parent.max_parallel_operations = 1
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

    async def coordinate(invocation: ToolInvocation) -> ToolResult:
        nonlocal spawned
        if spawned is None:
            spawned = await invocation.agents.spawn_agent(
                child,
                name="same name",
                description="Facts",
                messages=[UserMessage(content="first")],
                max_steps=1,
            )
            await invocation.agents.wait_run(spawned.run_id, timeout=3)
        else:
            next_id = await invocation.agents.start_run(
                child.id, messages=[UserMessage(content="second")], max_steps=1
            )
            result = await invocation.agents.wait_run(next_id, timeout=3)
            assert result is not None and result.output.text == "replacement"
        return ToolResult(content="done")

    async def exercise() -> None:
        parent = parent_agent(coordinate)
        coordinator = AgentCoordinator()
        first = parent.start(max_steps=2, coordinator=coordinator)
        async with asyncio.timeout(3):
            while not entered.is_set():
                await asyncio.sleep(0.01)
        first.cancel()
        with pytest.raises(AgentCancelled):
            await first.wait()
        assert await first.wait_for_idle(timeout=3)
        record = first.snapshot()
        assert record.child_runs[0].status == RunStatus.CANCELLED
        second = parent.start(max_steps=2, coordinator=coordinator)
        await second.wait()
        assert await second.wait_for_idle(timeout=3)
        assert first.snapshot() == record
        assert await coordinator.close(timeout=3)

    asyncio.run(exercise())


def test_immediate_restart_waits_for_terminal_child_delivery_to_drain() -> None:
    entered, release = threading.Event(), threading.Event()
    child = Agent(
        FakeModelClient(lambda *_: AssistantMessage(content=[TextContent(text="done")]))
    )

    class ObservedCoordinator(AgentCoordinator):
        def bind(
            self,
            run: Run,
            work: ExecutionWork,
            publish: Callable[[AgentEvent], None],
            cancellation: CancellationSignal,
        ) -> RunCoordination:
            binding = super().bind(run, work, publish, cancellation)
            if run.agent_id == child.id:

                def observe(_event: AgentEvent) -> None:
                    entered.set()
                    assert release.wait(3)

                run.subscribe(observe)
            return binding

    async def delegate(invocation: ToolInvocation) -> ToolResult:
        submitted = await invocation.agents.spawn_agent(
            child, name="research", description="Task", messages=[], max_steps=1
        )
        assert await invocation.agents.wait_run(submitted.run_id, timeout=2) is not None
        async with asyncio.timeout(2):
            while not entered.is_set():
                await asyncio.sleep(0.01)
        restarting = asyncio.create_task(
            invocation.agents.start_run(
                child.id, messages=[UserMessage(content="again")], max_steps=1
            )
        )
        await asyncio.sleep(0.03)
        assert not restarting.done()
        release.set()
        run_id = await restarting
        assert run_id != submitted.run_id
        assert await invocation.agents.wait_run(run_id, timeout=2) is not None
        return ToolResult(content="done")

    try:
        run_agent(
            parent_agent(delegate), max_steps=2, coordinator=ObservedCoordinator()
        )
    finally:
        release.set()


def test_parent_join_allows_child_to_start_nested_work() -> None:
    parent_answered = threading.Event()

    async def nested(invocation: ToolInvocation) -> ToolResult:
        async with asyncio.timeout(3):
            while not parent_answered.is_set():
                await asyncio.sleep(0.01)
        leaf = Agent(
            FakeModelClient(
                lambda *_: AssistantMessage(content=[TextContent(text="leaf")])
            )
        )
        submitted = await invocation.agents.spawn_agent(
            leaf, name="leaf", description="Nested work", messages=[], max_steps=1
        )
        result = await invocation.agents.wait_run(submitted.run_id, timeout=2)
        assert result is not None
        return ToolResult(content=result.output.text)

    async def delegate(invocation: ToolInvocation) -> ToolResult:
        child = parent_agent(nested)
        await invocation.agents.spawn_agent(
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
    parent.max_parallel_operations = 1
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
    async def exercise() -> None:
        entered = asyncio.Event()
        cleanup_started = asyncio.Event()
        release_cleanup = asyncio.Event()

        async def pending(_invocation: ToolInvocation) -> ToolResult:
            entered.set()
            try:
                await asyncio.Event().wait()
            finally:
                cleanup_started.set()
                while not release_cleanup.is_set():
                    try:
                        await release_cleanup.wait()
                    except asyncio.CancelledError:
                        # Cleanup can outlast repeated cancellation requests.
                        continue
            return ToolResult(content="done")

        child = Agent(
            FakeModelClient(
                lambda *_: AssistantMessage(
                    content=[ToolCall(id="work", name="work", arguments={})]
                )
            ),
            tools=[
                AgentTool(
                    name="work", description="", parameters={}, execute_async=pending
                )
            ],
        )

        async def delegate(invocation: ToolInvocation) -> ToolResult:
            spawned = await invocation.agents.spawn_agent(
                child, name="child", description="Work", messages=[], max_steps=1
            )
            await invocation.agents.wait_run(spawned.run_id, timeout=3)
            return ToolResult(content="done")

        coordinator = AgentCoordinator()
        with (
            patch("onyx.agents.coordination.CLEANUP_SECONDS", 0.01),
            patch("onyx.agents.coordination.CHILD_TERMINAL_TIMEOUT_SECONDS", 0.5),
        ):
            run = parent_agent(delegate).start(max_steps=2, coordinator=coordinator)
            try:
                await asyncio.wait_for(entered.wait(), timeout=2)
                run.cancel()
                await asyncio.wait_for(cleanup_started.wait(), timeout=2)
                await asyncio.sleep(0.03)
                assert run.status == RunStatus.RUNNING
            finally:
                release_cleanup.set()
            with pytest.raises(AgentCancelled):
                await run.wait(timeout=2)
            assert run.snapshot().child_runs[0].status == RunStatus.CANCELLED
            assert await run.wait_for_idle(timeout=2)
            assert await coordinator.close(timeout=2)

    asyncio.run(exercise())


def test_child_terminal_timeout_fails_parent_and_retains_cleanup_ownership() -> None:
    async def exercise() -> None:
        entered = asyncio.Event()
        release_cleanup = asyncio.Event()

        async def pending(_invocation: ToolInvocation) -> ToolResult:
            entered.set()
            try:
                await asyncio.Event().wait()
            finally:
                while not release_cleanup.is_set():
                    try:
                        await release_cleanup.wait()
                    except asyncio.CancelledError:
                        continue
            return ToolResult(content="done")

        child = Agent(
            FakeModelClient(
                lambda *_: AssistantMessage(
                    content=[ToolCall(id="work", name="work", arguments={})]
                )
            ),
            tools=[
                AgentTool(
                    name="work", description="", parameters={}, execute_async=pending
                )
            ],
        )

        async def delegate(invocation: ToolInvocation) -> ToolResult:
            spawned = await invocation.agents.spawn_agent(
                child, name="child", description="Work", messages=[], max_steps=1
            )
            await invocation.agents.wait_run(spawned.run_id, timeout=3)
            return ToolResult(content="done")

        parent = parent_agent(delegate)
        coordinator = AgentCoordinator()
        with patch("onyx.agents.coordination.CHILD_TERMINAL_TIMEOUT_SECONDS", 0.01):
            run = parent.start(max_steps=2, coordinator=coordinator)
            try:
                await asyncio.wait_for(entered.wait(), timeout=2)
                run.cancel()
                with pytest.raises(RunFailed):
                    await run.wait(timeout=2)
                record = run.snapshot()
                assert record.status == RunStatus.ERROR
                assert record.child_runs[0].status == RunStatus.ERROR
                assert record.child_runs[0].failure is not None
                assert record.child_runs[0].failure.kind == RunFailureKind.EXECUTION
                assert not await run.wait_for_idle(timeout=0.01)
                with pytest.raises(RuntimeError, match="running or draining"):
                    parent.start(max_steps=1, coordinator=coordinator)
            finally:
                release_cleanup.set()
            assert await run.wait_for_idle(timeout=2)
            assert run.snapshot() == record
            following = parent.start(max_steps=1, coordinator=coordinator)
            await following.wait(timeout=2)
            assert await following.wait_for_idle(timeout=2)
            assert await coordinator.close(timeout=2)

    asyncio.run(exercise())


@pytest.mark.asyncio
async def test_failed_child_settlement_retains_accepted_partial_output(
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
            yield TextDeltaEvent(message=message, content_index=0, text=message.text)
            partial_accepted.set()
            assert release.wait(3)
            yield GenerationDoneEvent(message=message)

    child = Agent(PartialModel(lambda _request, _signal: AssistantMessage()))

    async def coordinate(invocation: ToolInvocation) -> ToolResult:
        await invocation.agents.spawn_agent(
            child,
            name="research",
            description="Facts",
            messages=[UserMessage(content="Find facts")],
            max_steps=1,
        )
        async with asyncio.timeout(2):
            while not partial_accepted.is_set():
                await asyncio.sleep(0.005)
        return ToolResult(content="Child started")

    parent = parent_agent(coordinate)
    original_finish = RunCoordination.finish
    failed_coordinators: list[RunCoordination] = []

    async def fail_parent_finish(
        coordination: RunCoordination, cancel: bool
    ) -> list[RunSnapshot]:
        if coordination.run.agent_id == parent.id:
            failed_coordinators.append(coordination)
            raise TimeoutError("Forced settlement timeout")
        return await original_finish(coordination, cancel)

    monkeypatch.setattr(RunCoordination, "finish", fail_parent_finish)
    coordinator = AgentCoordinator()
    run = parent.start(max_steps=2, coordinator=coordinator)
    try:
        with pytest.raises(RunFailed):
            await run.wait(2)
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
            operation.status != RunStatus.RUNNING
            for operation in captured_child.operations
        )
        projected = project_response(
            snapshot,
            response_id=42,
            tool_ids={"coordinate": 1},
            registrations=coordinator.registrations(),
        )
        assert projected.response is not None
        assert (
            messages_from_items(projected.response.items)[-1].text == "first finished"
        )
        assert (
            messages_from_items(projected.response.child_runs[0].items)[0].text
            == "Child partial output"
        )
    finally:
        release.set()
        monkeypatch.setattr(RunCoordination, "finish", original_finish)
        for coordination in failed_coordinators[:1]:
            await original_finish(coordination, cancel=True)
        assert await run.wait_for_idle(3)
