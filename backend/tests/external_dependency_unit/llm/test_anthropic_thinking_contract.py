"""External dependency unit tests for the Anthropic thinking/sampling
contract resolution.

Newer Anthropic models (Opus 4.7+, Sonnet 5, Fable 5) reject the legacy
thinking API (thinking.type=enabled + budget_tokens) and non-default sampling
params with a 400. These tests make real API calls to verify Onyx sends the
adaptive-thinking payload these models require — the exact failure the
capability resolution in onyx/llm/anthropic_capabilities.py prevents.

Real-call tests use claude-haiku-4-5 for the legacy path (cheap tier per
testing guidelines) and claude-sonnet-5 for the new-contract path (the
contract under test has no cheaper representative).
"""

import os

import pytest

from onyx.llm.models import ChatCompletionMessage
from onyx.llm.models import ReasoningEffort
from onyx.llm.models import UserMessage
from onyx.llm.multi_llm import LitellmLLM

_ANTHROPIC_KEY_MISSING = not os.environ.get("ANTHROPIC_API_KEY")


def _make_llm(model_name: str) -> LitellmLLM:
    return LitellmLLM(
        api_key=os.environ["ANTHROPIC_API_KEY"],
        model_provider="anthropic",
        model_name=model_name,
        max_input_tokens=200000,
    )


@pytest.mark.skipif(_ANTHROPIC_KEY_MISSING, reason="Anthropic API key not available")
def test_sonnet_5_reasoning_stream_does_not_400() -> None:
    """Regression: claude-sonnet-5 with reasoning enabled 400'd with
    'thinking.type.enabled is not supported for this model' before the
    capability resolution routed it to the adaptive thinking API.
    """
    llm = _make_llm("claude-sonnet-5")
    messages: list[ChatCompletionMessage] = [
        UserMessage(role="user", content="Reply with exactly one word: ok")
    ]

    chunks = list(
        llm.stream(
            messages,
            reasoning_effort=ReasoningEffort.HIGH,
            max_tokens=2048,
        )
    )

    assert chunks, "Expected at least one streamed chunk"


@pytest.mark.skipif(_ANTHROPIC_KEY_MISSING, reason="Anthropic API key not available")
def test_sonnet_5_reasoning_invoke_does_not_400() -> None:
    llm = _make_llm("claude-sonnet-5")
    messages: list[ChatCompletionMessage] = [
        UserMessage(role="user", content="Reply with exactly one word: ok")
    ]

    response = llm.invoke(
        messages,
        reasoning_effort=ReasoningEffort.HIGH,
        max_tokens=2048,
    )

    assert response.choice.message.content, "Expected a non-empty response"


@pytest.mark.skipif(_ANTHROPIC_KEY_MISSING, reason="Anthropic API key not available")
def test_legacy_model_keeps_working_with_reasoning() -> None:
    """Older models must stay on their existing (legacy) thinking path."""
    llm = _make_llm("claude-haiku-4-5")
    messages: list[ChatCompletionMessage] = [
        UserMessage(role="user", content="Reply with exactly one word: ok")
    ]

    chunks = list(
        llm.stream(
            messages,
            reasoning_effort=ReasoningEffort.HIGH,
            max_tokens=2048,
        )
    )

    assert chunks, "Expected at least one streamed chunk"
