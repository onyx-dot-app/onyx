"""Recommended models missing from the vendored catalog fall back to generic
limits and capability flags. These pin the catalog values (LiteLLM 1.100.4
metadata) for models added to recommended-models.json in #18339."""

from typing import Any
from unittest.mock import patch

import pytest

from onyx.llm.constants import LlmProviderNames
from onyx.llm.model_capabilities import (
    ReasoningParamStyle,
    catalog_model_supports_image_input,
    get_llm_max_output_tokens,
    llm_max_input_tokens,
    model_is_reasoning_model,
    openai_model_supports_reasoning_none,
    resolve_reasoning_param_style,
    supported_reasoning_efforts,
)
from onyx.llm.model_catalog import build_model_map
from onyx.llm.model_request import UserMessage
from onyx.llm.models import ReasoningEffort
from onyx.llm.multi_llm import LitellmLLM

_TOOLS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "get_weather",
            "parameters": {"type": "object", "properties": {}},
        },
    }
]


@pytest.mark.parametrize(
    "provider,model_name,max_input,max_output",
    [
        (LlmProviderNames.OPENAI, "gpt-6.2-sol", 922000, 128000),
        (LlmProviderNames.OPENAI, "gpt-6.2-astra", 922000, 128000),
        (LlmProviderNames.ANTHROPIC, "claude-fable-5-2", 1000000, 128000),
        # LiteLLM lists output == context, which the catalog treats as untrusted.
        (LlmProviderNames.VERTEX_AI, "gemini-4-hydrogen", 1048576, 104857),
        (LlmProviderNames.VERTEX_AI, "gemini-4-carbon", 1048576, 104857),
        (LlmProviderNames.VERTEX_AI, "gemini-4-neon", 1048576, 104857),
    ],
)
def test_recommended_model_limits_and_flags(
    provider: str, model_name: str, max_input: int, max_output: int
) -> None:
    model_map = build_model_map()
    entry = model_map[f"{provider}/{model_name}"]
    assert llm_max_input_tokens(model_map, model_name, provider) == max_input
    assert get_llm_max_output_tokens(model_map, model_name, provider) == max_output
    assert model_is_reasoning_model(model_name, provider)
    assert catalog_model_supports_image_input(model_name, provider)
    assert entry["supports_function_calling"] is True
    assert entry["supports_response_schema"] is True


@pytest.mark.parametrize("model_name", ["gpt-6.2-sol", "gpt-6.2-astra"])
def test_gpt_6_2_rejects_reasoning_none(model_name: str) -> None:
    assert not openai_model_supports_reasoning_none(model_name)
    assert (
        resolve_reasoning_param_style(LlmProviderNames.OPENAI, [model_name], None)
        is ReasoningParamStyle.OPENAI
    )


@pytest.mark.parametrize(
    "provider,model_name,expected",
    [
        (
            LlmProviderNames.ANTHROPIC,
            "claude-fable-5-2",
            [
                ReasoningEffort.LOW,
                ReasoningEffort.MEDIUM,
                ReasoningEffort.HIGH,
                ReasoningEffort.XHIGH,
            ],
        ),
        (
            LlmProviderNames.VERTEX_AI,
            "gemini-4-hydrogen",
            [
                ReasoningEffort.OFF,
                ReasoningEffort.LOW,
                ReasoningEffort.MEDIUM,
                ReasoningEffort.HIGH,
            ],
        ),
    ],
)
def test_recommended_model_reasoning_levels(
    provider: str, model_name: str, expected: list[ReasoningEffort]
) -> None:
    assert supported_reasoning_efforts(provider, [model_name], None) == expected


@pytest.mark.parametrize("model_name", ["gpt-6.2-sol", "gpt-6.2-astra"])
@pytest.mark.parametrize("effort", [ReasoningEffort.OFF, ReasoningEffort.HIGH])
def test_gpt_6_2_tool_turn_never_sends_reasoning_none(
    model_name: str, effort: ReasoningEffort
) -> None:
    """OpenAI answers 400 to reasoning_effort "none" on these models."""
    llm = LitellmLLM(
        api_key="test-key",
        model_provider=LlmProviderNames.OPENAI,
        model_name=model_name,
        max_input_tokens=100000,
    )
    with patch("onyx.llm.litellm_singleton.litellm.completion") as completion:
        llm._completion(
            prompt=[UserMessage(content="hello")],
            tools=_TOOLS,
            tool_choice=None,
            stream=False,
            parallel_tool_calls=False,
            reasoning_effort=effort,
        )
    kwargs = completion.call_args.kwargs
    assert kwargs.get("reasoning_effort") != "none"
    assert (kwargs.get("reasoning") or {}).get("effort") != "none"
