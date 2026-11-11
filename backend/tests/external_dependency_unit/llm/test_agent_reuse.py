"""A real provider receives new run input with shared agent conversation history."""

import pytest

from onyx.agents.runtime import Agent
from onyx.llm.interfaces import GenerationContext
from onyx.llm.models import GenerationOptions, ReasoningEffort, UserMessage
from onyx.llm.multi_llm import LitellmLLM
from onyx.tracing.flows import LLMFlow
from tests.utils.secret_names import TestSecret


@pytest.mark.secrets(TestSecret.OPENAI_API_KEY)
def test_agent_reuse_preserves_context_with_a_fresh_budget(
    test_secrets: dict[TestSecret, str],
) -> None:
    agent = Agent(
        LitellmLLM(
            api_key=test_secrets[TestSecret.OPENAI_API_KEY],
            model_provider="openai",
            model_name="gpt-6-luna",
            max_input_tokens=6000,
        ),
        options=GenerationOptions(
            reasoning_effort=ReasoningEffort.LOW, max_tokens=1024
        ),
        generation_context=GenerationContext(flow=LLMFlow.DEEP_RESEARCH),
    )
    first = agent.start(
        max_steps=1,
        messages=[
            UserMessage(
                content="Remember that the project code is cedar. Reply only with the project code."
            )
        ],
    )
    first_result = first.result(timeout=90)
    assert first.wait_for_idle(timeout=90)
    following = agent.start(
        max_steps=1,
        messages=[
            UserMessage(
                content="What project code did I give you? Reply only with that code."
            )
        ],
    )
    following_result = following.result(timeout=90)
    assert following.wait_for_idle(timeout=90)

    assert first_result.steps == following_result.steps == 1
    assert "cedar" in first_result.output.text.lower()
    assert "cedar" in following_result.output.text.lower()
    assert following.previous_run_id == first.id
