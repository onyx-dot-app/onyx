"""Run the SDK through real LiteLLM requests to the deterministic HTTP provider."""

from collections.abc import Generator
from unittest.mock import patch
from uuid import uuid4

import pytest

from onyx.agents.agent_coordination import AgentCoordinator
from onyx.agents.models import AgentState, RunState
from onyx.agents.runtime import Agent, RunFailed
from onyx.agents.tools import AgentTool, ToolInvocation
from onyx.llm.cancellation import CancellationSignal
from onyx.llm.constants import LlmProviderNames
from onyx.llm.interfaces import GenerationContext
from onyx.llm.models import (
    AssistantMessage,
    GenerationOptions,
    GenerationRequest,
    Message,
    ReasoningEffort,
    TextContent,
    ToolDefinition,
    ToolResult,
    UserMessage,
)
from onyx.llm.models import ToolCall as ModelToolCall
from onyx.llm.multi_llm import LitellmLLM
from onyx.tracing.flows import LLMFlow
from tests.integration.common_utils.managers.mock_llm import MockLLMScript
from tests.integration.mock_services.mock_llm_server.models import (
    Reply,
    RequestConditions,
    Script,
    ToolCall,
)
from tests.integration.mock_services.mock_llm_server.server import run_in_thread
from tests.unit.onyx.agents.fakes import FakeModelClient


@pytest.fixture
def script() -> Generator[MockLLMScript, None, None]:
    with (
        run_in_thread() as url,
        patch("onyx.llm.multi_llm._env_injection_enabled", return_value=False),
    ):
        handle = MockLLMScript(url, uuid4().hex, Script(default_reply=None))
        try:
            yield handle
        finally:
            handle.close()


def model(script: MockLLMScript, input_limit: int = 20000) -> LitellmLLM:
    return LitellmLLM(
        api_key="sk-mock-llm-server",
        model_provider=LlmProviderNames.OPENAI_COMPATIBLE,
        model_name="mock-model",
        max_input_tokens=input_limit,
        api_base=script.api_base,
    )


def test_tool_result_reaches_next_provider_request(script: MockLLMScript) -> None:
    script.conversation(
        "lookup",
        Reply(tool_calls=[ToolCall(id="lookup-1", name="lookup", arguments={})]),
        Reply(
            text="The answer is 42.",
            conditions=RequestConditions(has_results_for=["lookup-1"]),
        ),
    )
    agent = Agent(
        model(script),
        tools=[
            AgentTool(
                definition=ToolDefinition(
                    name="lookup",
                    description="Read the answer",
                    parameters={"type": "object", "properties": {}},
                ),
                execute=lambda _invocation: ToolResult(content="42"),
            )
        ],
        generation_context=GenerationContext(flow=LLMFlow.CHAT_RESPONSE),
    )
    run = agent.start(
        max_steps=3,
        messages=[UserMessage(content="Look up the answer")],
        background=False,
    )
    assert run.result().output.text == "The answer is 42."
    assert script.requests[-1].tool_result("lookup-1") == "42"
    script.verify()


def test_compaction_summary_is_used_without_replacing_recorded_history(
    script: MockLLMScript,
) -> None:
    script.conversation(
        "summaries",
        *[
            Reply(
                text="Earlier messages establish that the answer is 42.", required=False
            )
            for _ in range(8)
        ],
        conditions=RequestConditions(
            has_tools=False, prompt_contains=["Summarize conversation history"]
        ),
    )
    script.conversation(
        "answer",
        Reply(text="42"),
        conditions=RequestConditions(
            has_tools=False, prompt_contains=["What is the answer now?"]
        ),
    )
    history: list[Message] = []
    for index in range(5):
        history.extend(
            [
                UserMessage(id=f"question-{index}", content="Archived context " * 120),
                AssistantMessage(
                    id=f"answer-{index}",
                    content=[TextContent(text="The answer is 42. " * 100)],
                ),
            ]
        )
    agent = Agent(
        model(script, input_limit=3000),
        state=AgentState(messages=history),
        generation_context=GenerationContext(flow=LLMFlow.CHAT_RESPONSE),
    )
    run = agent.start(
        max_steps=1,
        messages=[UserMessage(content="What is the answer now?")],
        background=False,
    )
    assert run.result().output.text == "42"
    assert agent.state.checkpoint is not None
    assert agent.state.messages[: len(history)] == history
    assert script.requests_in("summaries")
    assert "Earlier messages establish" in script.requests_in("answer")[0].prompt_text
    script.verify()


def test_provider_failure_retains_completed_tool_output(script: MockLLMScript) -> None:
    script.conversation(
        "lookup",
        Reply(tool_calls=[ToolCall(id="lookup-1", name="lookup", arguments={})]),
    )
    agent = Agent(
        model(script),
        tools=[
            AgentTool(
                definition=ToolDefinition(
                    name="lookup",
                    description="Read the answer",
                    parameters={"type": "object", "properties": {}},
                ),
                execute=lambda _invocation: ToolResult(content="accepted output"),
            )
        ],
        generation_context=GenerationContext(flow=LLMFlow.CHAT_RESPONSE),
    )
    run = agent.start(
        max_steps=3,
        messages=[UserMessage(content="Look up the answer")],
        background=False,
    )
    with pytest.raises(RunFailed):
        run.result()
    snapshot = run.snapshot()
    result = snapshot.steps[0].tools["lookup-1"].result
    assert result is not None
    assert result.text == "accepted output"
    assert snapshot.failure is not None


def test_reused_child_keeps_http_history_with_a_fresh_budget(
    script: MockLLMScript,
) -> None:
    script.conversation(
        "reuse",
        Reply(text="cedar"),
        Reply(
            text="cedar",
            conditions=RequestConditions(
                prompt_contains=[
                    "Remember that the project code is cedar",
                    "What project code did I give you?",
                ]
            ),
        ),
        conditions=RequestConditions(has_tools=False),
    )
    child = Agent(
        model(script),
        options=GenerationOptions(
            reasoning_effort=ReasoningEffort.LOW, max_tokens=1024
        ),
        generation_context=GenerationContext(flow=LLMFlow.DEEP_RESEARCH),
    )

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
        first_result = invocation.agents.wait_run(first.run_id, timeout=90)
        assert first_result is not None
        following = invocation.agents.start_run(
            first.agent_id,
            messages=[
                UserMessage(
                    content="What project code did I give you? Reply only with that code."
                )
            ],
            max_steps=1,
        )
        next_result = invocation.agents.wait_run(following, timeout=90)
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
            else [ModelToolCall(id="delegate", name="delegate", arguments={})]
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
    coordinator = AgentCoordinator()

    def run_parent() -> RunState:
        run = parent.start(max_steps=2, coordinator=coordinator)
        run.result()
        assert run.wait_for_idle(timeout=90)
        return run.snapshot()

    snapshot = run_parent()
    script.verify()
    first, following = snapshot.child_runs
    assert first.agent_id == following.agent_id == child.id
    assert coordinator.discover_children(parent.id)[0].path == "/root/research"
    assert first.run_id != following.run_id
    assert first.status == following.status == "complete"

    assert len(script.requests) == 2
    script.verify()
