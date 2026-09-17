"""Execution records stay stable through cancellation, cleanup, and reuse."""

import gc
import threading
import time
import weakref
from collections.abc import Generator

import pytest
from litellm.exceptions import (
    AuthenticationError,
    ContextWindowExceededError,
    RateLimitError,
    Timeout,
)
from pydantic import BaseModel

from onyx.agents.events import AgentEvent
from onyx.agents.models import PreparedStep, StepInput, StepResult, ToolCallContext
from onyx.agents.runtime import Agent, RunFailed
from onyx.agents.tools import AgentTool, ToolInvocation
from onyx.agents.transcript import RunFailureKind
from onyx.chat.errors import chat_error
from onyx.llm.cancellation import AgentCancelled, CancellationSignal
from onyx.llm.exceptions import ClassifiedLLMError, LLMRateLimitError, LLMTimeoutError
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
from tests.unit.onyx.agents.fakes import FakeModelClient


def answer(
    _request: GenerationRequest, _signal: CancellationSignal
) -> AssistantMessage:
    return AssistantMessage(content=[TextContent(text="answer")])


def wait_entered(event: threading.Event) -> None:
    assert event.wait(2)


@pytest.mark.parametrize("during_completion", [False, True])
def test_cancelled_writer_prevents_reuse_until_it_exits(
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
        wait_entered(entered)
        run.cancel()
        with pytest.raises(AgentCancelled):
            run.result(1)
        with pytest.raises(RuntimeError, match="already running"):
            agent.start(max_steps=1)
        assert not run.wait_for_idle(0.02)
    finally:
        release.set()
    assert run.wait_for_idle(2)
    agent.prepare_step = None
    agent.after_step = None
    following = agent.start(max_steps=1, messages=[UserMessage(content="Continue")])
    assert (following.result()).output.text == "answer"
    assert following.wait_for_idle(2)
    assert writes == ["finished"]
    assert [message.text for message in run.snapshot().messages] == (
        ["answer"] if during_completion else []
    )


def test_tool_execution_survives_enrichment_failure() -> None:
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
        run.result()
    assert run.wait_for_idle(2)
    snapshot = run.snapshot()
    assert snapshot.status == "error"
    assert snapshot.messages[-1].text == "saved"
    assert (
        next(op for op in snapshot.operations if op.tool_call_id).status == "complete"
    )


def test_failed_handle_releases_agent_and_preserves_error_classification(
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
            run.result()
        assert raised.value.failure.llm_error is not None
        assert raised.value.failure.llm_error.is_retryable
    assert run.wait_for_idle(2)
    del agent
    time.sleep(0)
    gc.collect()
    assert reference() is None
    assert run.snapshot().failure is not None


def test_wait_timeout_and_waiter_cancellation_leave_run_active() -> None:
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
        wait_entered(entered)
        with pytest.raises(TimeoutError):
            run.result(0.01)
        assert run.snapshot().status == "running"
    finally:
        release.set()
    assert (run.result(2)).output.text == "done"
    assert run.wait_for_idle(2)


def test_unsubscribe_before_dispatch_and_after_idle_is_safe() -> None:
    run = Agent(FakeModelClient(answer)).start(max_steps=1)
    observed: list[AgentEvent] = []
    unsubscribe = run.subscribe(observed.append)
    unsubscribe()
    run.result()
    assert run.wait_for_idle(2)
    unsubscribe()
    assert observed == []


def test_observer_backlog_preserves_output_and_cleanup_ownership(
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
    run = agent.start(max_steps=1, on_event=observe)
    try:
        wait_entered(entered)
        result = run.result(2)
        frozen = run.snapshot()
        assert result.output.text == "large " * 100
        assert not run.wait_for_idle(0.05)
        with pytest.raises(RuntimeError, match="already running"):
            agent.start(max_steps=1)
    finally:
        release.set()
    assert run.wait_for_idle(2)
    assert run.delivery_failed
    assert run.snapshot() == frozen


class BinaryDetails(BaseModel):
    content: bytes


def test_binary_tool_details_can_be_delivered() -> None:
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
    events: list[AgentEvent] = []
    run = agent.start(max_steps=1, on_event=events.append)
    run.result()
    assert run.wait_for_idle(2)
    assert not run.delivery_failed
    assert any(event.type == "tool_end" for event in events)


def test_late_tool_completion_cannot_change_a_closed_run(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("onyx.agents.runtime.CLEANUP_SECONDS", 0.02)
    entered = threading.Event()
    release = threading.Event()

    def execute(_invocation: ToolInvocation) -> ToolResult:
        entered.set()
        assert release.wait(3)
        return ToolResult(content="late")

    agent = Agent(
        FakeModelClient(
            lambda *_: AssistantMessage(
                content=[ToolCall(id="call", name="slow", arguments={})]
            )
        ),
        tools=[AgentTool(name="slow", description="", parameters={}, execute=execute)],
    )
    run = agent.start(max_steps=1)
    try:
        assert entered.wait(2)
        run.cancel()
        with pytest.raises(AgentCancelled):
            run.result(1)
        frozen = run.snapshot()
        assert not run.wait_for_idle(0.01)
    finally:
        release.set()
    assert run.wait_for_idle(2)
    assert run.snapshot() == frozen
    assert all(
        not isinstance(message, ToolResultMessage) for message in agent.context.messages
    )


def test_selected_tool_definition_and_callback_stay_paired() -> None:
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
    run.result()
    assert run.wait_for_idle(2)
    assert run.snapshot().messages[-1].text == "original"


def test_provider_receives_acceptance_before_reading_next_chunk() -> None:
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
    assert (run.result()).output.text == "x" * 30
    assert run.wait_for_idle(2)


def test_prestart_subscription_receives_initial_event() -> None:
    observed: list[AgentEvent] = []
    run = Agent(FakeModelClient(answer)).start(max_steps=1, on_event=observed.append)
    run.result()
    assert run.wait_for_idle(2)
    assert observed[0].type == "agent_start"
    assert observed[-1].type == "agent_end"


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
def test_raw_provider_failure_keeps_safe_ui_classification(
    error: Exception, code: str
) -> None:
    def fail(
        _request: GenerationRequest, _signal: CancellationSignal
    ) -> AssistantMessage:
        raise error

    run = Agent(FakeModelClient(fail)).start(max_steps=1)
    with pytest.raises(RunFailed) as raised:
        run.result()
    assert run.wait_for_idle(2)
    failure = raised.value.failure
    assert failure.kind == RunFailureKind.EXECUTION
    assert failure.llm_error is not None and failure.llm_error.error_code == code
    assert "private credential" not in failure.message


def test_unsubscribe_skips_listener_not_yet_dispatched() -> None:
    ready = threading.Event()

    def generate(
        request: GenerationRequest, signal: CancellationSignal
    ) -> AssistantMessage:
        assert ready.wait(2)
        return answer(request, signal)

    run = Agent(FakeModelClient(generate)).start(max_steps=1)
    observed: list[AgentEvent] = []

    def unsubscribe_next(_event: AgentEvent) -> None:
        unsubscribe()

    run.subscribe(unsubscribe_next)
    unsubscribe = run.subscribe(observed.append)
    ready.set()
    run.result()
    assert run.wait_for_idle(2)
    assert observed == []


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


def test_observer_cannot_wait_for_its_own_run_to_become_idle() -> None:
    ready = threading.Event()

    def generate(
        request: GenerationRequest, signal: CancellationSignal
    ) -> AssistantMessage:
        assert ready.wait(2)
        return answer(request, signal)

    agent = Agent(FakeModelClient(generate))
    run = agent.start(max_steps=1)
    failures: list[str] = []

    def observe(_event: AgentEvent) -> None:
        try:
            run.wait_for_idle(0.02)
        except RuntimeError as error:
            failures.append(str(error))
        else:
            failures.append("Observer idle wait was accepted")

    run.subscribe(observe)
    ready.set()
    assert (run.result(2)).output.text == "answer"
    assert run.wait_for_idle(2)
    assert failures
    assert set(failures) == {"An observer cannot wait for its own run to become idle"}


@pytest.mark.parametrize(
    "cause,wrapper,code,retryable",
    [
        (
            RateLimitError("rate limit", model="test", llm_provider="openai"),
            LLMRateLimitError,
            "RATE_LIMIT",
            True,
        ),
        (
            RateLimitError("insufficient_quota", model="test", llm_provider="openai"),
            LLMRateLimitError,
            "BUDGET_EXCEEDED",
            False,
        ),
        (
            Timeout("read timeout", model="test", llm_provider="openai"),
            LLMTimeoutError,
            "CONNECTION_ERROR",
            True,
        ),
        (None, LLMTimeoutError, "CONNECTION_ERROR", True),
    ],
)
def test_provider_failure_preserves_chat_retry_policy(
    cause: Exception | None,
    wrapper: type[LLMRateLimitError] | type[LLMTimeoutError],
    code: str,
    retryable: bool,
) -> None:
    def fail(
        _request: GenerationRequest, _signal: CancellationSignal
    ) -> AssistantMessage:
        raise wrapper("generation failed") from cause

    llm = FakeModelClient(fail)
    run = Agent(llm).start(max_steps=1)
    with pytest.raises(RunFailed) as raised:
        run.result(2)
    assert run.wait_for_idle(2)
    packet = chat_error(raised.value, llm)
    assert packet.error_code == code
    assert packet.is_retryable is retryable
