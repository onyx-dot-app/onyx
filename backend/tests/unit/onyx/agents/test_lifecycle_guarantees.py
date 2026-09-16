"""Execution records stay stable through cancellation, cleanup, and reuse."""

import asyncio
import gc
import threading
import weakref
from collections.abc import Callable, Generator
from queue import Queue

import pytest
from litellm.exceptions import AuthenticationError, ContextWindowExceededError
from pydantic import BaseModel

from onyx.agents.concurrency import ExecutionServices, ExecutionWork
from onyx.agents.events import AgentEvent
from onyx.agents.models import PreparedStep, StepInput, StepResult, ToolCallContext
from onyx.agents.runtime import Agent, RunFailed
from onyx.agents.tools import AgentTool, ToolInvocation
from onyx.agents.transcript import RunFailureKind
from onyx.llm.cancellation import AgentCancelled, CancellationSignal
from onyx.llm.exceptions import ClassifiedLLMError
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
    ToolResultMessage,
    UserMessage,
)
from onyx.utils.threadpool_concurrency import ContextThreadPoolExecutor
from tests.unit.onyx.agents.fakes import FakeModelClient


def answer(
    _request: GenerationRequest, _signal: CancellationSignal
) -> AssistantMessage:
    return AssistantMessage(content=[TextContent(text="answer")])


async def wait_entered(event: threading.Event) -> None:
    async with asyncio.timeout(2):
        while not event.is_set():
            await asyncio.sleep(0.005)


@pytest.mark.asyncio
@pytest.mark.parametrize("during_completion", [False, True])
async def test_cancelled_writer_prevents_reuse_until_it_exits(
    during_completion: bool,
) -> None:
    entered = threading.Event()
    release = threading.Event()
    writes: list[str] = []

    def prepare(_input: StepInput) -> PreparedStep:
        entered.set()
        assert release.wait(3)
        writes.append("finished")
        return PreparedStep()

    def complete(_result: StepResult) -> bool:
        entered.set()
        assert release.wait(3)
        writes.append("finished")
        return False

    agent = Agent(
        FakeModelClient(answer),
        prepare_step=None if during_completion else prepare,
        after_step=complete if during_completion else None,
    )
    run = agent.start(max_steps=1)
    try:
        await wait_entered(entered)
        run.cancel()
        with pytest.raises(AgentCancelled):
            await run.wait(1)
        with pytest.raises(RuntimeError, match="already running"):
            agent.start(max_steps=1)
        assert not await run.wait_for_idle(0.02)
    finally:
        release.set()
    assert await run.wait_for_idle(2)
    agent.prepare_step = None
    agent.after_step = None
    following = agent.start(max_steps=1, messages=[UserMessage(content="Continue")])
    assert (await following.wait()).output.text == "answer"
    assert await following.wait_for_idle(2)
    assert writes == ["finished"]
    assert [message.text for message in run.snapshot().messages] == (
        ["answer"] if during_completion else []
    )


@pytest.mark.asyncio
async def test_tool_execution_survives_enrichment_failure() -> None:
    def enrich(_context: ToolCallContext, _result: ToolResult) -> ToolResult:
        raise ValueError("invalid enrichment")

    agent = Agent(
        FakeModelClient(
            lambda *_: AssistantMessage(
                content=[ToolCall(id="call", name="write", arguments={})]
            )
        ),
        tools=[
            AgentTool(
                name="write",
                description="",
                parameters={},
                execute=lambda _: ToolResult(content="saved"),
            )
        ],
        after_tool_call=enrich,
    )
    run = agent.start(max_steps=1)
    with pytest.raises(RunFailed):
        await run.wait()
    assert await run.wait_for_idle(2)
    snapshot = run.snapshot()
    assert snapshot.status == "error"
    assert snapshot.messages[-1].text == "saved"
    assert (
        next(op for op in snapshot.operations if op.tool_call_id).status == "complete"
    )


@pytest.mark.asyncio
async def test_failed_handle_releases_agent_and_preserves_error_classification(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "onyx.agents.runtime.logger.exception", lambda *_args, **_kwargs: None
    )

    def fail(
        _request: GenerationRequest, _signal: CancellationSignal
    ) -> AssistantMessage:
        raise ClassifiedLLMError(
            client_error_msg="Unavailable",
            error_code="provider_error",
            is_retryable=True,
        )

    agent = Agent(FakeModelClient(fail))
    reference = weakref.ref(agent)
    run = agent.start(max_steps=1)
    for _ in range(2):
        with pytest.raises(RunFailed) as raised:
            await run.wait()
        assert raised.value.failure.llm_error is not None
        assert raised.value.failure.llm_error.is_retryable
    assert await run.wait_for_idle(2)
    del agent
    await asyncio.sleep(0)
    gc.collect()
    assert reference() is None
    assert run.snapshot().failure is not None


@pytest.mark.asyncio
async def test_wait_timeout_and_waiter_cancellation_leave_run_active() -> None:
    release = threading.Event()
    entered = threading.Event()

    def generate(
        _request: GenerationRequest, _signal: CancellationSignal
    ) -> AssistantMessage:
        entered.set()
        assert release.wait(3)
        return AssistantMessage(content=[TextContent(text="done")])

    run = Agent(FakeModelClient(generate)).start(max_steps=1)
    try:
        await wait_entered(entered)
        with pytest.raises(TimeoutError):
            await run.wait(0.01)
        waiter = asyncio.create_task(run.wait())
        await asyncio.sleep(0)
        waiter.cancel()
        with pytest.raises(asyncio.CancelledError):
            await waiter
        assert run.snapshot().status == "running"
    finally:
        release.set()
    assert (await run.wait(2)).output.text == "done"
    assert await run.wait_for_idle(2)


@pytest.mark.asyncio
async def test_unsubscribe_before_dispatch_and_after_idle_is_safe() -> None:
    run = Agent(FakeModelClient(answer)).start(max_steps=1)
    observed: list[AgentEvent] = []
    unsubscribe = run.subscribe(observed.append)
    unsubscribe()
    await run.wait()
    assert await run.wait_for_idle(2)
    unsubscribe()
    assert observed == []


@pytest.mark.asyncio
async def test_observer_backlog_does_not_change_output_or_release_admission(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("onyx.agents.concurrency.AGENT_EVENT_BUFFER_MAX_BYTES", 512)
    monkeypatch.setattr("onyx.agents.concurrency.CLEANUP_SECONDS", 0.02)
    entered = threading.Event()
    release = threading.Event()

    def observe(_event: AgentEvent) -> None:
        entered.set()
        assert release.wait(3)

    agent = Agent(
        FakeModelClient(
            lambda *_: AssistantMessage(content=[TextContent(text="large " * 100)])
        )
    )
    run = agent.start(max_steps=1)
    run.subscribe(observe)
    try:
        await wait_entered(entered)
        result = await run.wait(2)
        frozen = run.snapshot()
        assert result.output.text == "large " * 100
        assert not await run.wait_for_idle(0.05)
        with pytest.raises(RuntimeError, match="already running"):
            agent.start(max_steps=1)
    finally:
        release.set()
    assert await run.wait_for_idle(2)
    assert run.delivery_failed
    assert run.snapshot() == frozen


class BinaryDetails(BaseModel):
    content: bytes


@pytest.mark.asyncio
async def test_binary_tool_details_can_be_delivered() -> None:
    agent = Agent(
        FakeModelClient(
            lambda *_: AssistantMessage(
                content=[ToolCall(id="call", name="file", arguments={})]
            )
        ),
        tools=[
            AgentTool(
                name="file",
                description="",
                parameters={},
                execute=lambda _: ToolResult(
                    content="file",
                    details=BinaryDetails(content=b"\xff\x00"),
                    terminate=True,
                ),
            )
        ],
    )
    run = agent.start(max_steps=1)
    events: list[AgentEvent] = []
    run.subscribe(events.append)
    await run.wait()
    assert await run.wait_for_idle(2)
    assert not run.delivery_failed
    assert any(event.type == "tool_end" for event in events)


@pytest.mark.asyncio
async def test_late_async_tool_completion_cannot_change_a_closed_run(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("onyx.agents.runtime.CLEANUP_SECONDS", 0.02)
    entered = asyncio.Event()
    release = asyncio.Event()

    async def execute(_invocation: ToolInvocation) -> ToolResult:
        entered.set()
        while not release.is_set():
            try:
                await release.wait()
            except asyncio.CancelledError:
                continue
        return ToolResult(content="late")

    agent = Agent(
        FakeModelClient(
            lambda *_: AssistantMessage(
                content=[ToolCall(id="call", name="slow", arguments={})]
            )
        ),
        tools=[
            AgentTool(name="slow", description="", parameters={}, execute_async=execute)
        ],
    )
    run = agent.start(max_steps=1)
    try:
        await asyncio.wait_for(entered.wait(), 2)
        run.cancel()
        with pytest.raises(AgentCancelled):
            await run.wait(1)
        frozen = run.snapshot()
        assert not await run.wait_for_idle(0.01)
    finally:
        release.set()
    assert await run.wait_for_idle(2)
    assert run.snapshot() == frozen
    assert all(
        not isinstance(message, ToolResultMessage) for message in agent.context.messages
    )


@pytest.mark.asyncio
async def test_selected_tool_definition_and_callback_stay_paired() -> None:
    tool = AgentTool(
        name="original",
        description="",
        parameters={},
        execute=lambda _: ToolResult(content="original", terminate=True),
    )

    def generate(
        request: GenerationRequest, _signal: CancellationSignal
    ) -> AssistantMessage:
        assert request.tools[0].name == "original"
        tool.definition = tool.definition.model_copy(update={"name": "replacement"})
        tool.execute = lambda _: ToolResult(content="replacement")
        return AssistantMessage(
            content=[ToolCall(id="call", name="original", arguments={})]
        )

    run = Agent(FakeModelClient(generate), tools=[tool]).start(max_steps=1)
    await run.wait()
    assert await run.wait_for_idle(2)
    assert run.snapshot().messages[-1].text == "original"


@pytest.mark.asyncio
async def test_provider_receives_acceptance_before_reading_next_chunk() -> None:
    class StreamingModel(FakeModelClient):
        def stream(
            self, request: GenerationRequest, context: GenerationContext | None = None
        ) -> Generator[GenerationEvent, None, None]:
            assert request.messages == []
            assert context is not None
            text = ""
            for _ in range(30):
                text += "x"
                yield TextDeltaEvent(
                    message=AssistantMessage(content=[TextContent(text=text)]),
                    content_index=0,
                    text="x",
                )
                assert run.snapshot().messages[-1].text == text
            yield GenerationDoneEvent(
                message=AssistantMessage(content=[TextContent(text=text)])
            )

    run = Agent(StreamingModel(answer)).start(max_steps=1)
    assert (await run.wait()).output.text == "x" * 30
    assert await run.wait_for_idle(2)


@pytest.mark.asyncio
@pytest.mark.parametrize("eager", [False, True])
async def test_start_allows_subscription_before_execution(eager: bool) -> None:
    loop = asyncio.get_running_loop()
    factory = loop.get_task_factory()
    if eager:
        loop.set_task_factory(asyncio.eager_task_factory)
    try:
        events: list[AgentEvent] = []
        run = Agent(FakeModelClient(answer)).start(max_steps=1)
        run.subscribe(events.append)
        await run.wait()
        assert await run.wait_for_idle(2)
        assert events[0].type == "agent_start"
    finally:
        loop.set_task_factory(factory)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "error,code",
    [
        (
            AuthenticationError(
                message="bad private credential", llm_provider="openai", model="test"
            ),
            "AUTH_ERROR",
        ),
        (
            ContextWindowExceededError(
                message="long prompt", llm_provider="openai", model="test"
            ),
            "CONTEXT_TOO_LONG",
        ),
    ],
)
async def test_raw_provider_failure_keeps_safe_ui_classification(
    error: Exception, code: str
) -> None:
    def fail(
        _request: GenerationRequest, _signal: CancellationSignal
    ) -> AssistantMessage:
        raise error

    run = Agent(FakeModelClient(fail)).start(max_steps=1)
    with pytest.raises(RunFailed) as raised:
        await run.wait()
    assert await run.wait_for_idle(2)
    failure = raised.value.failure
    assert failure.kind == RunFailureKind.EXECUTION
    assert failure.llm_error is not None and failure.llm_error.error_code == code
    assert "private credential" not in failure.message


@pytest.mark.asyncio
async def test_unsubscribe_skips_listener_not_yet_dispatched() -> None:
    run = Agent(FakeModelClient(answer)).start(max_steps=1)
    observed: list[AgentEvent] = []

    def unsubscribe_next(_event: AgentEvent) -> None:
        unsubscribe()

    run.subscribe(unsubscribe_next)
    unsubscribe = run.subscribe(observed.append)
    await run.wait()
    assert await run.wait_for_idle(2)
    assert observed == []


def test_cancelled_capacity_wait_does_not_start_operation() -> None:
    async def exercise() -> None:
        services = ExecutionServices(1)
        signal = CancellationSignal()
        started = threading.Event()
        await services.capacity.acquire()
        waiting = asyncio.create_task(services.blocking(started.set, signal))
        try:
            await asyncio.sleep(0.001)
            signal.cancel()
            services.capacity.release()
            with pytest.raises(AgentCancelled):
                await asyncio.wait_for(waiting, timeout=1)
            assert await services.wait_idle(timeout=1)
            assert not started.is_set()
        finally:
            signal.cancel()
            services.close()

    asyncio.run(exercise())


def test_tool_argument_mutation_does_not_change_recorded_model_call() -> None:
    def execute(invocation: ToolInvocation) -> ToolResult:
        invocation.arguments["query"] = "tool-local value"
        return ToolResult(content="Result")

    agent = Agent(
        FakeModelClient(
            lambda *_: AssistantMessage(
                content=[
                    ToolCall(
                        id="lookup", name="lookup", arguments={"query": "original"}
                    )
                ]
            )
        ),
        tools=[
            AgentTool(name="lookup", description="", parameters={}, execute=execute)
        ],
    )
    result = agent.run(max_steps=1)
    message = agent.context.messages[0]
    assert isinstance(message, AssistantMessage)
    assert message.tool_calls[0].arguments == {"query": "original"}
    assert result.output.tool_calls[0].arguments == {"query": "original"}


@pytest.mark.asyncio
async def test_update_backpressure_is_shared_and_cancellation_releases_capacity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    services = ExecutionServices(1)
    first_work = ExecutionWork(services)
    second_work = ExecutionWork(services)
    queued: Queue[Callable[[], None]] = Queue()
    effects: list[str] = []
    first_signal = CancellationSignal()
    second_signal = CancellationSignal()
    following_signal = CancellationSignal()

    def schedule(callback: Callable[[], None]) -> None:
        queued.put_nowait(callback)

    monkeypatch.setattr(services.loop, "call_soon_threadsafe", schedule)
    with ContextThreadPoolExecutor(2, "test-update-producer") as producers:
        first = producers.submit(
            lambda: first_work.accept(lambda: effects.append("first"), first_signal)
        )
        try:
            async with asyncio.timeout(1):
                while queued.empty():
                    await asyncio.sleep(0.005)
            second = producers.submit(
                lambda: second_work.accept(
                    lambda: effects.append("second"), second_signal
                )
            )
            await asyncio.sleep(0.03)
            assert queued.qsize() == 1
            second_signal.cancel()
            async with asyncio.timeout(1):
                while not second.done():
                    await asyncio.sleep(0.005)
            with pytest.raises(AgentCancelled):
                second.result()
            assert queued.qsize() == 1
            first_signal.cancel()
            async with asyncio.timeout(1):
                while not first.done():
                    await asyncio.sleep(0.005)
            with pytest.raises(AgentCancelled):
                first.result()
            assert not first_work.tracker.idle
            queued.get_nowait()()
            assert first_work.tracker.idle
            assert effects == []
            following = producers.submit(
                lambda: second_work.accept(
                    lambda: effects.append("following"), following_signal
                )
            )
            async with asyncio.timeout(1):
                while queued.empty():
                    await asyncio.sleep(0.005)
            queued.get_nowait()()
            async with asyncio.timeout(1):
                while not following.done():
                    await asyncio.sleep(0.005)
            following.result()
            assert effects == ["following"]
        finally:
            first_signal.cancel()
            second_signal.cancel()
            following_signal.cancel()
            while not queued.empty():
                queued.get_nowait()()
            services.close()


@pytest.mark.asyncio
async def test_observer_cannot_wait_for_its_own_run_to_become_idle() -> None:
    agent = Agent(FakeModelClient(answer))
    run = agent.start(max_steps=1)
    failures: list[str] = []

    def observe(_event: AgentEvent) -> None:
        try:
            asyncio.run(run.wait_for_idle(0.02))
        except RuntimeError as error:
            failures.append(str(error))
        else:
            failures.append("Observer idle wait was accepted")

    run.subscribe(observe)
    assert (await run.wait(2)).output.text == "answer"
    assert await run.wait_for_idle(2)
    assert failures
    assert set(failures) == {"An observer cannot wait for its own run to become idle"}
