"""Context pressure preserves the task, tool effects, and recorded history."""

import threading
from collections.abc import Generator
from unittest.mock import patch

import pytest

from onyx.agents.compaction import context_budget, history_digest, request_tokens
from onyx.agents.events import AgentEvent
from onyx.agents.execution_records import (
    CompactionCheckpoint,
    ExecutionStatus,
    RunStatus,
)
from onyx.agents.models import AgentState, PreparedStep, RunState, StepInput
from onyx.agents.runtime import Agent, Run, RunFailed, _compact_context
from onyx.agents.tools import AgentTool, ToolInvocation
from onyx.llm.cancellation import AgentCancelled, CancellationSignal
from onyx.llm.exceptions import LLMContextLimitError
from onyx.llm.interfaces import LLM, GenerationContext, LLMConfig, LLMUserIdentity
from onyx.llm.models import (
    AssistantMessage,
    GenerationErrorEvent,
    GenerationEvent,
    GenerationOptions,
    GenerationRequest,
    Message,
    SystemMessage,
    TextContent,
    ThinkingDeltaEvent,
    ToolCall,
    ToolDefinition,
    ToolResult,
    ToolResultMessage,
    UserMessage,
)
from onyx.llm.token_budget import TokenBudget, resolve_token_budget
from onyx.tracing.flows import LLMFlow
from onyx.tracing.framework.traces import TraceContentMode
from tests.unit.onyx.agents.fakes import message_events

TASK = "Compare the evidence and preserve citations."


class ContextModel(LLM):
    def __init__(self, *, tool_rounds: int = 0, reject_first: bool = False) -> None:
        self.tool_rounds = tool_rounds
        self.reject_first = reject_first
        self.generations: list[GenerationRequest] = []
        self.summaries: list[GenerationRequest] = []
        self.contexts: list[GenerationContext] = []
        self.threads: list[threading.Thread] = []

    @property
    def config(self) -> LLMConfig:
        return LLMConfig(
            model_provider="openai",
            model_name="test",
            max_input_tokens=1200,
            temperature=0,
        )

    def redact_error(self, text: str) -> str:
        return text

    def invoke(
        self, request: GenerationRequest, context: GenerationContext | None = None
    ) -> AssistantMessage:
        self.threads.append(threading.current_thread())
        if context:
            self.contexts.append(context.model_copy())
        if context and context.cancellation:
            context.cancellation.check()
        if context and context.flow == LLMFlow.CHAT_HISTORY_SUMMARIZATION:
            self.summaries.append(request.model_copy(deep=True))
            assert request_tokens(request) <= context_budget(self).input_limit
            return AssistantMessage(
                content=[
                    TextContent(
                        text="Evidence from completed searches supports [1]. Continue comparing sources."
                    )
                ]
            )
        self.generations.append(request.model_copy(deep=True))
        if self.reject_first and len(self.generations) == 1:
            raise LLMContextLimitError("Too much context")
        index = len(self.generations)
        if index <= self.tool_rounds:
            return AssistantMessage(
                content=[ToolCall(id=f"call-{index}", name="lookup", arguments={})]
            )
        return AssistantMessage(
            content=[TextContent(text="Evidence supports the conclusion [1].")]
        )

    def stream(
        self, request: GenerationRequest, context: GenerationContext | None = None
    ) -> Generator[GenerationEvent, None, None]:
        try:
            message = self.invoke(request, context)
        except LLMContextLimitError:
            yield ThinkingDeltaEvent(content_index=0, text="Discarded attempt")
            yield GenerationErrorEvent(error_message="Too much context")
            raise
        yield from message_events(message)


def test_compaction_uses_configured_input_safety_margin() -> None:
    model = ContextModel()
    with (
        patch("onyx.agents.compaction.GEN_AI_INPUT_TOKEN_SAFETY_MARGIN", 0.25),
        patch("onyx.llm.token_budget.GEN_AI_INPUT_TOKEN_SAFETY_MARGIN", 0.25),
    ):
        budget = context_budget(model)
        output_budget = resolve_token_budget(model)
    assert budget.input_limit == 900
    assert (
        model.config.max_input_tokens - budget.input_limit
        == output_budget.safety_tokens
    )


def test_compaction_within_task_preserves_tool_effects_and_prepared_steps() -> None:
    model = ContextModel(tool_rounds=5)
    calls: list[str] = []
    prepared: list[int] = []
    execution_threads: list[threading.Thread] = []

    def execute(invocation: ToolInvocation) -> ToolResult:
        calls.append(invocation.call_id)
        return ToolResult(content="Evidence [1] 東京 " * 180)

    def prepare(decision: StepInput) -> PreparedStep:
        execution_threads.append(threading.current_thread())
        step = decision.step
        prepared.append(step.index)
        return PreparedStep(tools=tools, assemble_messages=render)

    def render(messages: list[Message]) -> list[Message]:
        assert threading.current_thread() is execution_threads[0]
        return [*messages, SystemMessage(content="Use the required report format.")]

    tools = [
        AgentTool(
            definition=ToolDefinition(
                name="lookup", description="Search", parameters={}
            ),
            execute=execute,
        )
    ]
    agent = Agent(
        model,
        state=AgentState(messages=[UserMessage(content=TASK)]),
        prepare_step=prepare,
    )
    run = agent.start(max_steps=6)
    run.result()
    assert run.wait_for_idle(2)
    assert len(model.summaries) >= 2
    assert all(thread is execution_threads[0] for thread in model.threads)
    assert all(thread is execution_threads[0] for thread in execution_threads)
    for summary_request in model.summaries:
        assert "tool_result lookup (call-" in summary_request.messages[0].text
        assert "\ufffd" not in summary_request.messages[0].text
    assert calls == [f"call-{i}" for i in range(1, 6)]
    assert prepared == list(range(6))
    assert (
        len([m for m in agent.state.messages if isinstance(m, ToolResultMessage)]) == 5
    )
    for request in model.generations:
        assert any(message.text == TASK for message in request.messages)
        assert request.messages[-1].text == "Use the required report format."
        assert request_tokens(request) <= context_budget(model).input_limit
        pending: set[str] = set()
        for message in request.messages:
            if isinstance(message, AssistantMessage):
                pending.update(call.id for call in message.tool_calls)
            elif isinstance(message, ToolResultMessage):
                assert message.tool_call_id in pending
                pending.remove(message.tool_call_id)
        assert not pending
    snapshot = run.snapshot()
    assert snapshot is not None and snapshot.checkpoint is not None
    reloaded = Agent(
        model,
        state=AgentState(messages=agent.state.messages, checkpoint=snapshot.checkpoint),
    )
    reloaded_run = reloaded.start(
        max_steps=1, messages=[UserMessage(content="Summarize the conclusion.")]
    )
    reloaded_run.result()
    assert reloaded_run.wait_for_idle(2)
    assert any(
        "Conversation summary:" in message.text
        for message in model.generations[-1].messages
    )


@pytest.mark.parametrize("step_timeout", [None, 37])
def test_provider_context_rejection_preserves_execution_settings(
    step_timeout: int | None,
) -> None:
    model = ContextModel(reject_first=True)
    history: list[Message] = [
        UserMessage(content="Old question"),
        AssistantMessage(content=[TextContent(text="Old evidence " * 100)]),
        UserMessage(content=TASK),
    ]
    prepared: list[int] = []

    def prepare(state: StepInput) -> PreparedStep:
        prepared.append(state.step.index)
        return PreparedStep(stall_timeout_s=step_timeout)

    signal = CancellationSignal()
    default_signal = CancellationSignal()
    identity = LLMUserIdentity(user_id="user", session_id="session")
    agent = Agent(
        model,
        state=AgentState(messages=history),
        generation_context=GenerationContext(
            cancellation=default_signal,
            stall_timeout_s=23,
            total_timeout_s=71,
            user_identity=identity,
            flow=LLMFlow.RESEARCH_AGENT,
            content_mode=TraceContentMode.METADATA_ONLY,
        ),
        prepare_step=prepare,
    )
    events: list[AgentEvent] = []
    run = agent.start(
        background=False, max_steps=1, cancellation=signal, on_event=events.append
    )
    result = run.result()
    assert run.wait_for_idle(2)
    starts = [event for event in events if event.type == "message_start"]
    ends = [event for event in events if event.type == "message_end"]
    assert len(starts) == len(ends) == 1
    assert starts[0].message_id == ends[0].message_id == result.output.id
    assert ends[0].status == ExecutionStatus.COMPLETE
    assert ends[0].message.error_message is None
    assert ends[0].message.thinking == ""
    assert prepared == [0]
    assert [context.flow for context in model.contexts] == [
        LLMFlow.RESEARCH_AGENT,
        LLMFlow.CHAT_HISTORY_SUMMARIZATION,
        LLMFlow.RESEARCH_AGENT,
    ]
    for context in model.contexts:
        assert context.cancellation is signal
        assert context.stall_timeout_s == (step_timeout or 23)
        assert context.total_timeout_s == 71
        assert context.user_identity == identity
        assert context.content_mode == TraceContentMode.METADATA_ONLY
    assert len(model.generations) == 2
    assert len(model.summaries) == 1
    assert result.steps == 1
    assert len(agent.state.messages) == len(history) + 1
    assert result.output.text.endswith("[1].")

    assert agent.generation_context.cancellation is default_signal
    assert agent.generation_context.stall_timeout_s == 23
    assert agent.generation_context.flow == LLMFlow.RESEARCH_AGENT


def test_step_timeout_override_does_not_change_later_steps() -> None:
    model = ContextModel(tool_rounds=1)
    tool = AgentTool(
        definition=ToolDefinition(
            name="lookup", description="Lookup evidence", parameters={"type": "object"}
        ),
        execute=lambda _invocation: ToolResult(content="Evidence"),
    )

    def prepare(state: StepInput) -> PreparedStep:
        return PreparedStep(
            tools=[tool], stall_timeout_s=37 if state.step.index == 0 else None
        )

    agent = Agent(
        model,
        generation_context=GenerationContext(stall_timeout_s=23),
        prepare_step=prepare,
    )
    run = agent.start(background=False, max_steps=2)
    run.result()
    assert run.wait_for_idle(2)
    assert [context.stall_timeout_s for context in model.contexts] == [37, 23]
    assert agent.generation_context.stall_timeout_s == 23


def test_oversized_required_instruction_fails_without_losing_snapshot() -> None:
    model = ContextModel()
    agent = Agent(
        model, state=AgentState(messages=[UserMessage(content="mandatory " * 2000)])
    )
    run = agent.start(max_steps=1)
    with pytest.raises(RunFailed):
        run.result()
    assert run.wait_for_idle(2)
    assert not model.generations
    assert agent.state.messages[0].text == "mandatory " * 2000
    snapshot = run.snapshot()
    assert snapshot is not None and snapshot.status == "error"


def test_context_fitting_validates_checkpoint_once() -> None:
    source: list[Message] = [UserMessage(content="Current branch")]
    checkpoint = CompactionCheckpoint(
        summary="Summary", covered_count=1, covered_digest=history_digest(source)
    )
    run = Run.from_snapshot(
        RunState(
            run_id="run",
            agent_id="agent",
            status=RunStatus.COMPLETE,
            checkpoint=checkpoint,
            steps=[],
        )
    )
    with patch("onyx.agents.compaction.history_digest", wraps=history_digest) as digest:
        request = _compact_context(
            run,
            ContextModel(),
            source,
            PreparedStep(),
            GenerationContext(flow=LLMFlow.UNTAGGED_INVOKE),
        )
    digest.assert_called_once_with(source)
    assert any(
        message.text == "Conversation summary:\nSummary" for message in request.messages
    )
    assert run.snapshot().checkpoint == checkpoint


def test_checkpoint_from_another_branch_is_removed_from_context() -> None:
    agent = Agent(
        ContextModel(),
        state=AgentState(
            messages=[UserMessage(content="Current branch")],
            checkpoint=CompactionCheckpoint(
                summary="Other branch", covered_count=1, covered_digest="different"
            ),
        ),
    )
    run = agent.start(max_steps=1)
    run.result()
    assert run.wait_for_idle(2)
    assert run.snapshot().checkpoint is None
    assert agent.state.checkpoint is None


@pytest.mark.parametrize("max_tokens", [None, 200])
def test_output_budget_is_recalculated_after_compaction(
    monkeypatch: pytest.MonkeyPatch, max_tokens: int | None
) -> None:
    budget = TokenBudget(
        max_output_tokens=4096,
        context_tokens=4300,
        safety_tokens=120,
    )
    monkeypatch.setattr("onyx.agents.runtime.resolve_token_budget", lambda _: budget)
    model = ContextModel(reject_first=True)
    agent = Agent(
        model,
        state=AgentState(
            messages=[
                UserMessage(content="Old question"),
                AssistantMessage(content=[TextContent(text="Old evidence " * 100)]),
                UserMessage(content=TASK),
            ]
        ),
        options=GenerationOptions(max_tokens=max_tokens),
    )
    agent.start(background=False, max_steps=1).result()
    assert len(model.generations) == 2
    assert model.summaries
    for request in model.generations:
        expected = budget.output_allowance(request_tokens(request))
        assert expected is not None
        assert request.options.max_tokens == (
            min(max_tokens, expected) if max_tokens else expected
        )
    if max_tokens is None:
        before = model.generations[0].options.max_tokens
        after = model.generations[1].options.max_tokens
        assert before is not None and after is not None
        assert after > before


@pytest.mark.parametrize("reject_first", [False, True])
@pytest.mark.parametrize("provider_error", [False, True])
def test_failed_summary_truncates_old_turns_without_changing_history(
    reject_first: bool, provider_error: bool
) -> None:
    class FailingSummaryModel(ContextModel):
        def invoke(
            self, request: GenerationRequest, context: GenerationContext | None = None
        ) -> AssistantMessage:
            if context and context.flow == LLMFlow.CHAT_HISTORY_SUMMARIZATION:
                self.summaries.append(request)
                if provider_error:
                    raise RuntimeError("Summary provider unavailable")
                return AssistantMessage()
            return super().invoke(request, context)

    model = FailingSummaryModel(reject_first=reject_first)
    history: list[Message] = [
        SystemMessage(content="Preserve these instructions."),
        UserMessage(content="Old question"),
        AssistantMessage(content=[ToolCall(id="old", name="lookup", arguments={})]),
        ToolResultMessage(
            tool_call_id="old",
            tool_name="lookup",
            content="Old evidence " * (100 if reject_first else 1500),
        ),
        AssistantMessage(content=[TextContent(text="Old answer")]),
        UserMessage(content=TASK),
        AssistantMessage(content=[ToolCall(id="current", name="lookup", arguments={})]),
        ToolResultMessage(
            tool_call_id="current", tool_name="lookup", content="Current evidence"
        ),
    ]
    agent = Agent(model, state=AgentState(messages=history))
    run = agent.start(background=False, max_steps=1)
    run.result()
    assert model.summaries
    request = model.generations[-1]
    assert request.messages == [history[0], *history[5:]]
    assert request_tokens(request) <= context_budget(model).input_limit
    assert agent.state.messages[:-1] == history
    checkpoint = run.snapshot().checkpoint
    assert checkpoint is not None and checkpoint.summary == ""
    assert checkpoint.covered_count == 5

    # The same cutoff survives a resumed agent without losing recorded history.
    reloaded = Agent(model, state=agent.state)
    reloaded.start(background=False, max_steps=1).result()
    assert model.generations[-1].messages[: len(request.messages)] == request.messages
    assert reloaded.state.messages[: len(history)] == history


def test_truncation_does_not_drop_oversized_current_tool_result() -> None:
    model = ContextModel()
    history: list[Message] = [
        UserMessage(content="Old question"),
        AssistantMessage(content=[TextContent(text="Old answer")]),
        UserMessage(content=TASK),
        AssistantMessage(content=[ToolCall(id="current", name="lookup", arguments={})]),
        ToolResultMessage(
            tool_call_id="current", tool_name="lookup", content="Evidence " * 2000
        ),
    ]
    agent = Agent(model, state=AgentState(messages=history))
    with patch(
        "onyx.agents.runtime.compact_history", side_effect=RuntimeError("Failed")
    ):
        run = agent.start(background=False, max_steps=1)
        with pytest.raises(RunFailed):
            run.result()
    assert not model.generations
    assert agent.state.messages == history


def test_failed_summary_does_not_swallow_cancellation() -> None:
    model = ContextModel()
    run = Run.from_snapshot(
        RunState(run_id="run", agent_id="agent", status=RunStatus.COMPLETE, steps=[])
    )
    with patch("onyx.agents.runtime.compact_history", side_effect=AgentCancelled()):
        with pytest.raises(AgentCancelled):
            _compact_context(
                run,
                model,
                [UserMessage(content="old"), UserMessage(content=TASK)],
                PreparedStep(),
                GenerationContext(),
                force=True,
            )
