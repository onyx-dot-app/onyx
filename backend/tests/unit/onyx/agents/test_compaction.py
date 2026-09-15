"""Context pressure preserves the task, tool effects, and recorded history."""

from collections.abc import Generator

import pytest

from onyx.agents.compaction import ContextLimitError, context_budget, request_tokens
from onyx.agents.runtime import Agent, AgentContext, AgentHooks, AgentStep
from onyx.agents.tools import AgentTool, ToolInvocation
from onyx.llm.exceptions import LLMContextLimitError
from onyx.llm.interfaces import LLM, GenerationContext, LLMInfo
from onyx.llm.models import (
    AssistantMessage,
    GenerationDoneEvent,
    GenerationEvent,
    GenerationRequest,
    Message,
    SystemMessage,
    TextContent,
    ToolCall,
    ToolResult,
    ToolResultMessage,
    UserMessage,
)
from onyx.tracing.flows import LLMFlow

TASK = "Compare the evidence and preserve citations."


class ContextModel(LLM):
    def __init__(self, *, tool_rounds: int = 0, reject_first: bool = False) -> None:
        self.tool_rounds = tool_rounds
        self.reject_first = reject_first
        self.generations: list[GenerationRequest] = []
        self.summaries: list[GenerationRequest] = []

    @property
    def info(self) -> LLMInfo:
        return LLMInfo(
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

    def prepare(context: AgentContext, step: AgentStep) -> AgentContext:
        prepared.append(step.index)
        return context

    def render(context: AgentContext) -> GenerationRequest:
        context.messages.append(
            SystemMessage(content="Use the required report format.")
        )
        return context.generation_request()

    agent = Agent(
        model,
        context=AgentContext(
            messages=[UserMessage(content=TASK)],
            tools=[
                AgentTool(
                    name="lookup", description="Search", parameters={}, execute=execute
                )
            ],
        ),
        hooks=AgentHooks(prepare_step=prepare, build_request=render),
    )
    agent.run(max_steps=6)
    assert len(model.summaries) >= 2
    for summary_request in model.summaries:
        assert "tool_result lookup (call-" in summary_request.messages[0].text
        assert "\ufffd" not in summary_request.messages[0].text
    assert calls == [f"call-{i}" for i in range(1, 6)]
    assert prepared == list(range(6))
    assert (
        len([m for m in agent.context.messages if isinstance(m, ToolResultMessage)])
        == 5
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
    snapshot = agent.snapshot()
    assert snapshot is not None and snapshot.checkpoint is not None
    reloaded = Agent(
        model,
        context=AgentContext(
            messages=agent.context.messages, checkpoint=snapshot.checkpoint
        ),
    )
    reloaded.run(
        max_steps=1, messages=[UserMessage(content="Summarize the conclusion.")]
    )
    assert any(
        "Conversation summary:" in message.text
        for message in model.generations[-1].messages
    )


def test_provider_context_rejection_retries_only_generation() -> None:
    model = ContextModel(reject_first=True)
    history: list[Message] = [
        UserMessage(content="Old question"),
        AssistantMessage(content=[TextContent(text="Old evidence " * 100)]),
        UserMessage(content=TASK),
    ]
    agent = Agent(model, context=AgentContext(messages=history))
    result = agent.run(max_steps=1)
    assert len(model.generations) == 2
    assert len(model.summaries) == 1
    assert result.steps == 1
    assert len(agent.context.messages) == len(history) + 1
    assert result.output.text.endswith("[1].")


def test_oversized_required_instruction_fails_without_losing_snapshot() -> None:
    model = ContextModel()
    agent = Agent(
        model, context=AgentContext(messages=[UserMessage(content="mandatory " * 2000)])
    )
    with pytest.raises(ContextLimitError):
        agent.run(max_steps=1)
    assert not model.generations
    assert agent.context.messages[0].text == "mandatory " * 2000
    snapshot = agent.snapshot()
    assert snapshot is not None and snapshot.status == "error"
