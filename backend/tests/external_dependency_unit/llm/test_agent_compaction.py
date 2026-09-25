"""Real summaries retain task constraints and source citations."""

import pytest

from onyx.agents.models import AgentState
from onyx.agents.runtime import Agent
from onyx.llm.models import (
    AssistantMessage,
    GenerationOptions,
    Message,
    ReasoningEffort,
    ToolCall,
    ToolResultMessage,
    UserMessage,
)
from onyx.llm.multi_llm import LitellmLLM
from tests.utils.secret_names import TestSecret


@pytest.mark.secrets(TestSecret.OPENAI_API_KEY)
def test_compacted_tool_history_preserves_answer_and_source(
    test_secrets: dict[TestSecret, str],
) -> None:
    model = LitellmLLM(
        api_key=test_secrets[TestSecret.OPENAI_API_KEY],
        model_provider="openai",
        model_name="gpt-5-mini",
        max_input_tokens=6000,
    )
    history: list[Message] = [
        UserMessage(
            content="What was Harbor's actual September revenue? Give the dollar amount with citation [1]. Ignore forecasts."
        )
    ]
    for index in range(4):
        call_id = f"source-{index}"
        history.append(
            AssistantMessage(
                content=[
                    ToolCall(
                        id=call_id,
                        name="search",
                        arguments={"query": "Harbor September revenue"},
                    )
                ]
            )
        )
        history.append(
            ToolResultMessage(
                tool_call_id=call_id,
                tool_name="search",
                content=(
                    "Source [1], Harbor audited results: actual September revenue was USD 731,000. A forecast of USD 9 million is irrelevant. "
                    + "Unrelated archive records contain no further revenue evidence. "
                    * 180
                ),
            )
        )
    agent = Agent(
        model,
        options=GenerationOptions(
            reasoning_effort=ReasoningEffort.LOW, max_tokens=2048
        ),
        state=AgentState(messages=history),
    )
    result = agent.start(background=False, max_steps=1).result()
    assert agent.state.checkpoint is not None
    assert "731" in result.output.text
    assert "[1]" in result.output.text
    assert agent.state.messages[: len(history)] == history
