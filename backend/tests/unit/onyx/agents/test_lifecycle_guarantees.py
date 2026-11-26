"""Execution records stay stable through cancellation, cleanup, and reuse."""

import gc
import threading
import time
import weakref
from collections.abc import Callable, Generator
from functools import partial
from uuid import uuid4

import pytest
from litellm.exceptions import (
    AuthenticationError,
    ContextWindowExceededError,
    RateLimitError,
    Timeout,
)
from pydantic import BaseModel

from onyx.agents.events import AgentEndEvent, AgentEvent, ToolEndEvent
from onyx.agents.models import (
    AgentState,
    PreparedStep,
    RunFailureKind,
    RunHooks,
    RunStatus,
    StepInput,
    StepResult,
    ToolCallContext,
)
from onyx.agents.runtime import Agent, RunFailed
from onyx.agents.tools import AgentTool, InputMode, PendingToolInput, ToolInvocation
from onyx.chat.agent import ChatFeature
from onyx.chat.emitter import Emitter
from onyx.chat.errors import chat_error
from onyx.chat.presentation import ResponsePresenter
from onyx.deep_research.agent import DeepResearchFeature
from onyx.deep_research.research_agent import ResearchFeature
from onyx.deep_research.tool_definitions import GENERATE_REPORT_TOOL_NAME
from onyx.file_store.models import ExtractedContextFiles
from onyx.llm.cancellation import AgentCancelled, CancellationSignal
from onyx.llm.exceptions import ClassifiedLLMError, LLMRateLimitError, LLMTimeoutError
from onyx.llm.interfaces import GenerationContext
from onyx.llm.model_capabilities import ToolFamily
from onyx.llm.model_response import (
    ChatCompletionDeltaToolCall,
    Delta,
    ResponseFunctionCall,
)
from onyx.llm.models import (
    AssistantMessage,
    GenerationDoneEvent,
    GenerationEvent,
    GenerationRequest,
    ReasoningEffort,
    TextContent,
    TextDeltaEvent,
    ToolCall,
    ToolChoiceOptions,
    ToolDefinition,
    ToolResult,
    ToolResultMessage,
    UserMessage,
)
from onyx.tools.interface import Tool
from onyx.tools.models import ToolContext
from onyx.tools.tool_implementations.sandbox.sandbox_tools import ExecCommandTool
from onyx.tools.tool_implementations.sandbox.shapes import SHELL_SHAPES
from onyx.tools.tool_implementations.sandbox.turn import SandboxTurn
from onyx.tracing.flows import LLMFlow
from tests.unit.onyx.agents.fakes import EchoTool, FakeModelClient, ScriptedLLM


def answer(
    _request: GenerationRequest, _signal: CancellationSignal
) -> AssistantMessage:
    return AssistantMessage(content=[TextContent(text="answer")])


def wait_entered(event: threading.Event) -> None:
    assert event.wait(2)


@pytest.mark.parametrize("during_completion", [False, True])
def test_cancelled_callback_reserves_agent_until_it_returns(
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
        generation_context=GenerationContext(flow=LLMFlow.CHAT_RESPONSE),
        feature=RunHooks(
            prepare_step=None if during_completion else prepare,
            after_step=complete if during_completion else None,
        ),
    )
    run = agent.start(max_steps=1)
    try:
        wait_entered(entered)
        run.cancel()
        with pytest.raises(TimeoutError):
            run.result(0.05)
        assert not run._reusable.done()
        assert not run.wait_for_idle(0)
        with pytest.raises(RuntimeError, match="already running or draining"):
            agent.start(max_steps=1)
    finally:
        release.set()
    with pytest.raises(AgentCancelled):
        run.result(2)
    assert run.wait_for_idle(2)
    agent.feature = None
    following = agent.start(max_steps=1, messages=[UserMessage(content="Continue")])
    assert following.result(timeout=2).output.text == "answer"
    assert following.wait_for_idle(2)
    assert writes == ["finished"]
    assert [message.text for message in run.snapshot().messages] == (
        ["answer"] if during_completion else []
    )


def test_tool_execution_survives_enrichment_failure() -> None:
    events: list[AgentEvent] = []

    def enrich(_context: ToolCallContext, _result: ToolResult) -> ToolResult:
        raise ValueError("invalid enrichment")

    agent = Agent(
        FakeModelClient(
            lambda *_: AssistantMessage(
                content=[ToolCall(id="call", name="write", arguments={})]
            )
        ),
        generation_context=GenerationContext(flow=LLMFlow.CHAT_RESPONSE),
        tools=[
            AgentTool(
                definition=ToolDefinition(name="write", description="", parameters={}),
                execute=lambda _: ToolResult(content="saved"),
            )
        ],
        feature=RunHooks(after_tool_call=enrich),
    )
    run = agent.start(max_steps=1, on_event=events.append)
    with pytest.raises(RunFailed):
        run.result()
    assert run.wait_for_idle(2)
    snapshot = run.snapshot()
    assert snapshot.status == "error"
    assert snapshot.messages[-1].text == "saved"
    assert next(iter(snapshot.steps[0].tools.values())).status == "complete"
    assert snapshot.progress is not None
    assert snapshot.progress.finalized_tool_call_ids == set()
    completed = [event for event in events if isinstance(event, ToolEndEvent)]
    assert len(completed) == 1
    assert completed[0].result.content == "saved"


def test_cancellation_during_tool_finalization_rejects_the_enriched_result() -> None:
    entered = threading.Event()
    release = threading.Event()
    events: list[AgentEvent] = []

    def enrich(_context: ToolCallContext, _result: ToolResult) -> ToolResult:
        entered.set()
        assert release.wait(5)
        return ToolResult(content="enriched")

    agent = Agent(
        FakeModelClient(
            lambda *_: AssistantMessage(
                content=[ToolCall(id="call", name="write", arguments={})]
            )
        ),
        generation_context=GenerationContext(flow=LLMFlow.CHAT_RESPONSE),
        tools=[
            AgentTool(
                definition=ToolDefinition(name="write", description="", parameters={}),
                execute=lambda _: ToolResult(content="saved"),
            )
        ],
        feature=RunHooks(after_tool_call=enrich),
    )
    run = agent.start(max_steps=1, on_event=events.append)
    try:
        assert entered.wait(3)
        run.cancel()
    finally:
        release.set()
        assert run.wait_for_idle(3)
    with pytest.raises(AgentCancelled):
        run.result(3)
    snapshot = run.snapshot()
    assert snapshot.messages[-1].text == "saved"
    assert snapshot.progress is not None
    assert snapshot.progress.finalized_tool_call_ids == set()
    assert not any(isinstance(event, ToolEndEvent) for event in events)


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
            tool_choice=ToolChoiceOptions.REQUIRED,
            finish_reason="length",
        )

    agent = Agent(
        FakeModelClient(fail),
        generation_context=GenerationContext(flow=LLMFlow.CHAT_RESPONSE),
    )
    reference = weakref.ref(agent)
    run = agent.start(max_steps=1)
    for _ in range(2):
        with pytest.raises(RunFailed) as raised:
            run.result()
        assert raised.value.failure.llm_error is not None
        assert raised.value.failure.llm_error.is_retryable
        assert raised.value.failure.llm_error.tool_choice == ToolChoiceOptions.REQUIRED
        assert raised.value.failure.llm_error.finish_reason == "length"
    assert run.wait_for_idle(2)
    del agent
    time.sleep(0)
    gc.collect()
    assert reference() is None
    assert run.snapshot().failure is not None


ECHO_CALL = Delta(
    tool_calls=[
        ChatCompletionDeltaToolCall(
            index=0,
            id="call",
            function=ResponseFunctionCall(name="echo", arguments='{"value":"x"}'),
        )
    ]
)
_EMPTY_FILES = ExtractedContextFiles(
    file_texts=[],
    image_files=[],
    use_as_search_filter=False,
    total_token_count=0,
    file_metadata=[],
    uncapped_token_count=None,
)


def _plain() -> tuple[Agent, object | None]:
    return (
        Agent(
            ScriptedLLM([ECHO_CALL, Delta(content="done")]),
            generation_context=GenerationContext(flow=LLMFlow.CHAT_RESPONSE),
            tools=[EchoTool().bind(ToolContext)],
        ),
        None,
    )


def _chat(*, code_mode: bool = False, sandbox: bool = False) -> tuple[Agent, object]:
    tools: list[Tool] = [EchoTool()]
    if sandbox:
        tools.append(
            ExecCommandTool(
                SandboxTurn(
                    tenant_id="t",
                    user_id=uuid4(),
                    chat_session_id=uuid4(),
                    vm_chat_files=[],
                    copy_vm_chat_files=False,
                    shell=SHELL_SHAPES[ToolFamily.OPENAI],
                )
            )
        )

    def build() -> ChatFeature:
        return ChatFeature(
            messages=[],
            tools=tools,
            code_mode=code_mode,
            custom_agent_prompt=None,
            base_system_prompt="",
            context_files=_EMPTY_FILES,
            persona=None,
            user_memory_context=None,
            llm=ScriptedLLM([ECHO_CALL, Delta(content="done")]),
            create_subagent=lambda: build().agent(AgentState()),
        )

    feature = build()
    return feature.agent(AgentState()), feature


def _research() -> tuple[Agent, object]:
    feature = ResearchFeature(
        [EchoTool()],
        # A step without calls continues; the step after it writes the report.
        ScriptedLLM([ECHO_CALL, Delta(content="notes"), Delta(content="done")]),
        len,
        None,
        "",
        ReasoningEffort.LOW,
    )
    return feature.agent(), feature


def _deep_research() -> tuple[Agent, object]:
    feature = DeepResearchFeature(
        [],
        ScriptedLLM(
            [
                Delta(content="Plan"),
                Delta(
                    tool_calls=[
                        ChatCompletionDeltaToolCall(
                            index=0,
                            id="report",
                            function=ResponseFunctionCall(
                                name=GENERATE_REPORT_TOOL_NAME, arguments="{}"
                            ),
                        )
                    ]
                ),
                Delta(content="done"),
            ],
            128000,
        ),
        len,
        None,
        "",
        ReasoningEffort.LOW,
        None,
        skip_clarification=True,
    )
    return feature.agent(AgentState()), feature


@pytest.mark.parametrize(
    "build",
    [
        _plain,
        _chat,
        partial(_chat, code_mode=True),
        partial(_chat, sandbox=True),
        _research,
        _deep_research,
    ],
    ids=[
        "agent",
        "chat",
        "chat-code-mode",
        "chat-sandbox",
        "research",
        "deep-research",
    ],
)
def test_finished_agent_and_run_are_freed_without_a_garbage_collection_pass(
    build: Callable[[], tuple[Agent, object | None]],
) -> None:
    agent, feature = build()
    presenter = ResponsePresenter(Emitter(lambda _packet: None))
    gc.collect()
    gc.disable()
    try:
        run = agent.start(
            max_steps=4,
            background=False,
            messages=[UserMessage(content="question")],
            on_event=presenter.consume,
        )
        assert run.result(timeout=5).output.text == "done"
        assert run.wait_for_idle(5)
        freed = [threading.Event() for _ in range(3)]
        weakref.finalize(run, freed[0].set)
        weakref.finalize(agent, freed[1].set)
        if feature is not None:
            weakref.finalize(feature, freed[2].set)
        else:
            freed[2].set()
        del run, agent, feature
        # Worker threads can still be leaving frames that hold the run.
        assert all(event.wait(5) for event in freed)
    finally:
        gc.enable()


def test_released_suspended_run_is_freed_without_a_garbage_collection_pass() -> None:
    agent = Agent(
        FakeModelClient(
            lambda *_: AssistantMessage(
                content=[ToolCall(id="send", name="echo", arguments={"value": "x"})]
            )
        ),
        generation_context=GenerationContext(flow=LLMFlow.CHAT_RESPONSE),
        tools=[EchoTool().bind(ToolContext)],
        feature=RunHooks(
            before_tool_call=lambda _context: PendingToolInput(
                request_id="approve", prompt="Send?", mode=InputMode.EXECUTE
            )
        ),
    )
    gc.collect()
    gc.disable()
    try:
        run = agent.start(max_steps=2, messages=[UserMessage(content="Send")])
        assert run.wait_until_settled(5).status == RunStatus.SUSPENDED
        assert run.wait_for_idle(5)
        run.handoff()
        freed = [threading.Event(), threading.Event()]
        weakref.finalize(run, freed[0].set)
        weakref.finalize(agent, freed[1].set)
        del run, agent
        assert all(event.wait(5) for event in freed)
    finally:
        gc.enable()


def test_wait_timeout_and_waiter_cancellation_leave_run_active() -> None:
    release = threading.Event()
    entered = threading.Event()

    def generate(
        _request: GenerationRequest, _signal: CancellationSignal
    ) -> AssistantMessage:
        entered.set()
        assert release.wait(3)
        return AssistantMessage(content=[TextContent(text="done")])

    run = Agent(
        FakeModelClient(generate),
        generation_context=GenerationContext(flow=LLMFlow.CHAT_RESPONSE),
    ).start(max_steps=1)
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
    run = Agent(
        FakeModelClient(answer),
        generation_context=GenerationContext(flow=LLMFlow.CHAT_RESPONSE),
    ).start(max_steps=1)
    observed: list[AgentEvent] = []
    unsubscribe = run.subscribe(observed.append)
    unsubscribe()
    run.result()
    assert run.wait_for_idle(2)
    unsubscribe()
    assert observed == []


def test_observer_backlog_preserves_output_and_cleanup_ownership() -> None:
    entered = threading.Event()
    release = threading.Event()
    received: list[AgentEvent] = []

    def observe(event: AgentEvent) -> None:
        entered.set()
        assert release.wait(3)
        received.append(event)

    agent = Agent(
        FakeModelClient(
            lambda *_: AssistantMessage(content=[TextContent(text="large " * 100)])
        ),
        generation_context=GenerationContext(flow=LLMFlow.CHAT_RESPONSE),
    )
    run = agent.start(max_steps=1, on_event=observe)
    try:
        wait_entered(entered)
        result = run.result(2)
        frozen = run.snapshot()
        assert result.output.text == "large " * 100
        assert not run.wait_for_idle(0.05)
        assert not run._reusable.done()
        with pytest.raises(RuntimeError, match="already running or draining"):
            agent.start(max_steps=1)
    finally:
        release.set()
    assert run.wait_for_idle(2)
    following = agent.start(max_steps=1)
    assert following.result(timeout=2).output.text == "large " * 100
    assert following.wait_for_idle(2)
    assert not run.delivery_failed
    assert isinstance(received[-1], AgentEndEvent)
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
        generation_context=GenerationContext(flow=LLMFlow.CHAT_RESPONSE),
        tools=[
            AgentTool(
                definition=ToolDefinition(name="file", description="", parameters={}),
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


def test_late_tool_completion_cannot_change_a_closed_run() -> None:
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
        generation_context=GenerationContext(flow=LLMFlow.CHAT_RESPONSE),
        tools=[
            AgentTool(
                definition=ToolDefinition(name="slow", description="", parameters={}),
                execute=execute,
            )
        ],
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
        not isinstance(message, ToolResultMessage) for message in agent.state.messages
    )


def test_selected_tool_definition_and_callback_stay_paired() -> None:
    tool = AgentTool(
        definition=ToolDefinition(name="original", description="", parameters={}),
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

    run = Agent(
        FakeModelClient(generate),
        generation_context=GenerationContext(flow=LLMFlow.CHAT_RESPONSE),
        tools=[tool],
    ).start(max_steps=1)
    run.result()
    assert run.wait_for_idle(2)
    assert run.snapshot().messages[-1].text == "original"


def test_provider_receives_acceptance_before_reading_next_chunk() -> None:
    started = threading.Event()

    class StreamingModel(FakeModelClient):
        def stream(
            self, request: GenerationRequest, context: GenerationContext | None = None
        ) -> Generator[GenerationEvent, None, None]:
            assert started.wait(3)
            assert request.messages == []
            assert context is not None
            text = ""
            for _ in range(30):
                text += "x"
                yield TextDeltaEvent(
                    content_index=0,
                    text="x",
                )
                assert run.snapshot().messages[-1].text == text
            yield GenerationDoneEvent()

    run = Agent(
        StreamingModel(answer),
        generation_context=GenerationContext(flow=LLMFlow.CHAT_RESPONSE),
    ).start(max_steps=1)
    started.set()
    assert (run.result()).output.text == "x" * 30
    assert run.wait_for_idle(2)


def test_prestart_subscription_receives_initial_event() -> None:
    observed: list[AgentEvent] = []
    run = Agent(
        FakeModelClient(answer),
        generation_context=GenerationContext(flow=LLMFlow.CHAT_RESPONSE),
    ).start(max_steps=1, on_event=observed.append)
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

    run = Agent(
        FakeModelClient(fail),
        generation_context=GenerationContext(flow=LLMFlow.CHAT_RESPONSE),
    ).start(max_steps=1)
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

    run = Agent(
        FakeModelClient(generate),
        generation_context=GenerationContext(flow=LLMFlow.CHAT_RESPONSE),
    ).start(max_steps=1)
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
        generation_context=GenerationContext(flow=LLMFlow.CHAT_RESPONSE),
        tools=[
            AgentTool(
                definition=ToolDefinition(name="lookup", description="", parameters={}),
                execute=execute,
            )
        ],
    )
    result = agent.start(background=False, max_steps=1).result()
    message = agent.state.messages[0]
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

    agent = Agent(
        FakeModelClient(generate),
        generation_context=GenerationContext(flow=LLMFlow.CHAT_RESPONSE),
    )
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
    run = Agent(
        llm, generation_context=GenerationContext(flow=LLMFlow.CHAT_RESPONSE)
    ).start(max_steps=1)
    with pytest.raises(RunFailed) as raised:
        run.result(2)
    assert run.wait_for_idle(2)
    packet = chat_error(raised.value, llm)
    assert packet.error_code == code
    assert packet.is_retryable is retryable


def test_cancelled_before_tool_callback_cannot_start_the_tool() -> None:
    entered, release = threading.Event(), threading.Event()
    executed: list[str] = []

    def before(_context: ToolCallContext) -> None:
        entered.set()
        assert release.wait(3)

    def execute(_invocation: ToolInvocation) -> ToolResult:
        executed.append("write")
        return ToolResult(content="written")

    agent = Agent(
        FakeModelClient(
            lambda *_: AssistantMessage(
                content=[TextContent(text="New answer")]
                if entered.is_set()
                else [ToolCall(id="write", name="write", arguments={})]
            )
        ),
        generation_context=GenerationContext(flow=LLMFlow.CHAT_RESPONSE),
        tools=[
            AgentTool(
                definition=ToolDefinition(name="write", description="", parameters={}),
                execute=execute,
            )
        ],
        feature=RunHooks(before_tool_call=before),
    )
    old = agent.start(max_steps=1)
    try:
        assert entered.wait(2)
        old.cancel()
        with pytest.raises(AgentCancelled):
            old.result(timeout=2)
        assert not old._reusable.done()
        with pytest.raises(RuntimeError, match="already running or draining"):
            agent.start(max_steps=1)
        assert not old.wait_for_idle(0)
    finally:
        release.set()
    assert old.wait_for_idle(2)
    new = agent.start(max_steps=1)
    assert new.result(timeout=2).output.text == "New answer"
    assert new.wait_for_idle(2)
    assert executed == []
