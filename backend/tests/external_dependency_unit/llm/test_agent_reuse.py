"""A real provider receives new run input with shared agent conversation history."""

import asyncio

import pytest
from sqlalchemy.orm import Session

from onyx.agents.coordination import AgentCoordinator
from onyx.agents.models import RunSnapshot
from onyx.agents.runtime import Agent
from onyx.agents.tools import AgentTool, ToolInvocation
from onyx.db.llm import fetch_existing_llm_providers
from onyx.llm.cancellation import CancellationSignal
from onyx.llm.factory import llm_from_provider
from onyx.llm.interfaces import GenerationContext
from onyx.llm.models import (
    AssistantMessage,
    GenerationOptions,
    GenerationRequest,
    ReasoningEffort,
    TextContent,
    ToolCall,
    ToolResult,
    UserMessage,
)
from onyx.server.manage.llm.models import LLMProviderView
from onyx.tracing.flows import LLMFlow
from tests.unit.onyx.agents.fakes import FakeModelClient


@pytest.mark.usefixtures("enable_ee")
def test_child_reuse_preserves_context_with_a_fresh_budget(db_session: Session) -> None:
    providers = fetch_existing_llm_providers(db_session, flow_type_filter=[])
    provider = next(
        (provider for provider in providers if provider.provider == "openai"), None
    )
    assert provider is not None, "Configure an OpenAI provider before running this test"
    llm = llm_from_provider(
        model_name="gpt-5-mini",
        llm_provider=LLMProviderView.from_model(provider),
        timeout=60,
    )
    child = Agent(
        llm,
        options=GenerationOptions(
            reasoning_effort=ReasoningEffort.LOW, max_tokens=1024
        ),
        execution=GenerationContext(flow=LLMFlow.DEEP_RESEARCH),
    )

    async def coordinate(invocation: ToolInvocation) -> ToolResult:
        first = await invocation.agents.spawn_agent(
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
        first_result = await invocation.agents.wait_run(first.run_id, timeout=90)
        assert first_result is not None
        following = await invocation.agents.start_run(
            first.agent_id,
            messages=[
                UserMessage(
                    content="What project code did I give you? Reply only with that code."
                )
            ],
            max_steps=1,
        )
        next_result = await invocation.agents.wait_run(following, timeout=90)
        assert first_result is not None and next_result is not None
        assert first_result.steps == next_result.steps == 1
        assert first_result.run_id != next_result.run_id
        assert "cedar" in first_result.output.text.lower()
        assert "cedar" in next_result.output.text.lower()
        return ToolResult(content=next_result.output.text)

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
        tools=[
            AgentTool(
                name="delegate",
                description="",
                parameters={},
                execute_async=coordinate,
            )
        ],
    )
    coordinator = AgentCoordinator()

    async def run_parent() -> RunSnapshot:
        run = parent.start(max_steps=2, coordinator=coordinator)
        await run.wait()
        assert await run.wait_for_idle(timeout=90)
        return run.snapshot()

    snapshot = asyncio.run(run_parent())
    first, following = snapshot.child_runs
    assert first.agent_id == following.agent_id == child.id
    assert coordinator.discovery(parent.id)[0].path == "/root/research"
    assert first.run_id != following.run_id
    assert first.status == following.status == "complete"
