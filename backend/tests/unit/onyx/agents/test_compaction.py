"""Context pressure preserves the task, tool effects, and recorded history."""

from collections.abc import Generator

import pytest

from onyx.agents.compaction import context_budget, request_tokens
from onyx.agents.models import AgentState, PreparedStep, StepInput
from onyx.agents.runtime import Agent, RunFailed
from onyx.agents.tools import AgentTool, ToolInvocation
from onyx.agents.transcript import CompactionCheckpoint
from onyx.llm.cancellation import CancellationSignal
from onyx.llm.exceptions import LLMContextLimitError
from onyx.llm.interfaces import LLM, GenerationContext, LLMConfig, LLMUserIdentity
from onyx.llm.models import (
    AssistantMessage,
    GenerationDoneEvent,
    GenerationEvent,
    GenerationOptions,
    GenerationRequest,
    Message,
    SystemMessage,
    TextContent,
    ToolCall,
    ToolResult,
    ToolResultMessage,
    UserMessage,
)
from onyx.llm.token_budget import TokenBudget
from onyx.tracing.flows import LLMFlow
from onyx.tracing.framework.traces import TraceContentMode

TASK = "Compare the evidence and preserve citations."


class ContextModel(LLM):
    def __init__(self, *, tool_rounds: int = 0, reject_first: bool = False) -> None:
        self.tool_rounds = tool_rounds
        self.reject_first = reject_first
        self.generations: list[GenerationRequest] = []
        self.summaries: list[GenerationRequest] = []
        self.contexts: list[GenerationContext] = []

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
        yield GenerationDoneEvent(message=self.invoke(request, context))


def test_compaction_within_task_preserves_tool_effects_and_prepared_steps() -> None:
    model = ContextModel(tool_rounds=5)
    calls: list[str] = []
    prepared: list[int] = []

    def execute(invocation: ToolInvocation) -> ToolResult:
        calls.append(invocation.call_id)
        return ToolResult(content="Evidence [1] 東京 " * 180)

    def prepare(decision: StepInput) -> PreparedStep:
        step = decision.step
        prepared.append(step.index)
        return PreparedStep(tools=tools, assemble_messages=render)

    def render(messages: list[Message]) -> list[Message]:
        return [*messages, SystemMessage(content="Use the required report format.")]

    tools = [
        AgentTool(name="lookup", description="Search", parameters={}, execute=execute)
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
        return PreparedStep(timeout=step_timeout)

    signal = CancellationSignal()
    identity = LLMUserIdentity(user_id="user", session_id="session")
    agent = Agent(
        model,
        state=AgentState(messages=history),
        generation_context=GenerationContext(
            cancellation=signal,
            timeout=23,
            total_timeout=71,
            user_identity=identity,
            flow=LLMFlow.RESEARCH_AGENT,
            content_mode=TraceContentMode.METADATA_ONLY,
        ),
        prepare_step=prepare,
    )
    result = agent.start(background=False, max_steps=1).result()
    assert prepared == [0]
    assert [context.flow for context in model.contexts] == [
        LLMFlow.RESEARCH_AGENT,
        LLMFlow.CHAT_HISTORY_SUMMARIZATION,
        LLMFlow.RESEARCH_AGENT,
    ]
    for context in model.contexts:
        assert context.cancellation is signal
        assert context.timeout == (step_timeout or 23)
        assert context.total_timeout == 71
        assert context.user_identity == identity
        assert context.content_mode == TraceContentMode.METADATA_ONLY
    assert len(model.generations) == 2
    assert len(model.summaries) == 1
    assert result.steps == 1
    assert len(agent.state.messages) == len(history) + 1
    assert result.output.text.endswith("[1].")


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
        input_tokens=1080,
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
