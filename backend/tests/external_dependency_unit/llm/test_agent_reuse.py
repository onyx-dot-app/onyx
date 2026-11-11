"""A real provider receives new run input with shared agent conversation history."""

import pytest

from onyx.agents.agent_coordination import AgentCoordinator
from onyx.agents.models import RunState
from onyx.agents.runtime import Agent
from onyx.agents.tools import AgentTool, ToolInvocation
from onyx.llm.cancellation import CancellationSignal
from onyx.llm.interfaces import GenerationContext
from onyx.llm.models import (
    AssistantMessage,
    GenerationOptions,
    GenerationRequest,
    ReasoningEffort,
    TextContent,
    ToolCall,
    ToolDefinition,
    ToolResult,
    UserMessage,
)
from onyx.llm.multi_llm import LitellmLLM
from onyx.tracing.flows import LLMFlow
from tests.unit.onyx.agents.fakes import FakeModelClient
from tests.utils.secret_names import TestSecret


@pytest.mark.secrets(TestSecret.OPENAI_API_KEY)
def test_child_reuse_preserves_context_with_a_fresh_budget(
    test_secrets: dict[TestSecret, str],
) -> None:
    llm = LitellmLLM(
        api_key=test_secrets[TestSecret.OPENAI_API_KEY],
        model_provider="openai",
        model_name="gpt-6-luna",
        max_input_tokens=6000,
    )
    child = Agent(
        llm,
        options=GenerationOptions(
            reasoning_effort=ReasoningEffort.LOW, max_tokens=1024
        ),
        generation_context=GenerationContext(flow=LLMFlow.DEEP_RESEARCH),
    )

    coordinator = AgentCoordinator()
    child_runs: list[RunState] = []

    def coordinate(invocation: ToolInvocation) -> ToolResult:
        first = invocation.agents.spawn_agent(
            child,
            name="research",
            description="Remember and recall a project code",
            max_steps=1,
            messages=[
                UserMessage(
                    content="Remember that the project code is cedar. Reply only with the project code."
                )
            ],
        )
        first_state = coordinator.completion(first.run_id).result(timeout=90)
        assert coordinator.run(first.run_id).wait_for_idle(timeout=90)
        receipt = invocation.agents.send_message(
            first.agent_id,
            message="What project code did I give you? Reply only with that code.",
            max_steps=1,
        )
        assert receipt.run_id is not None and receipt.run_id != first.run_id
        following = coordinator.completion(receipt.run_id).result(timeout=90)
        assert coordinator.run(receipt.run_id).wait_for_idle(timeout=90)
        child_runs.extend((first_state, following))
        assert len(first_state.steps) == len(following.steps) == 1
        assert "cedar" in first_state.steps[0].message.text.lower()
        assert "cedar" in following.steps[0].message.text.lower()
        return ToolResult(content=following.steps[0].message.text)

    def parent_reply(
        request: GenerationRequest, _signal: CancellationSignal
    ) -> AssistantMessage:
        return AssistantMessage(
            content=[TextContent(text="Done")]
            if request.messages
            else [ToolCall(id="delegate", name="delegate", arguments={})]
        )

    parent = Agent(
        FakeModelClient(parent_reply),
        generation_context=GenerationContext(flow=LLMFlow.CHAT_RESPONSE),
        tools=[
            AgentTool(
                definition=ToolDefinition(
                    name="delegate", description="", parameters={}
                ),
                execute=coordinate,
            )
        ],
    )
    run = parent.start(max_steps=2, coordinator=coordinator)
    run.result()
    assert run.wait_for_idle(timeout=90)
    first, following = child_runs
    assert first.agent_id == following.agent_id == child.id
    assert coordinator.discover_children(parent.id)[0].path == "/root/research"
    assert first.run_id != following.run_id
    assert first.status == following.status == "complete"
