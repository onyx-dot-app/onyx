from typing import Any
from unittest.mock import patch

import litellm
import pytest
from litellm.exceptions import BadRequestError
from litellm.types.utils import Delta

from onyx.configs.constants import MessageType
from onyx.llm.constants import LlmProviderNames
from onyx.llm.model_capabilities import openai_model_supports_reasoning_none
from onyx.llm.models import ReasoningEffort, UserMessage
from onyx.llm.multi_llm import LitellmLLM
from onyx.llm.well_known_providers.constants import (
    BIFROST_API_MODE_CHAT_COMPLETIONS,
    BIFROST_API_MODE_CONFIG_KEY,
    BIFROST_API_MODE_RESPONSES,
)
from onyx.secondary_llm_flows.document_filter import classify_section_relevance
from onyx.secondary_llm_flows.query_expansion import (
    keyword_query_expansion,
    semantic_query_rephrase,
)
from onyx.tools.models import ChatMinimalTextMessage

_COMPLETION = "onyx.llm.litellm_singleton.litellm.completion"

_TOOLS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "get_weather",
            "parameters": {"type": "object", "properties": {}},
        },
    }
]


def _llm(
    model_name: str,
    model_provider: str = LlmProviderNames.OPENAI,
    **kwargs: Any,
) -> LitellmLLM:
    return LitellmLLM(
        api_key="test-key",
        model_provider=model_provider,
        model_name=model_name,
        max_input_tokens=100000,
        **kwargs,
    )


def _sent_kwargs(
    llm: LitellmLLM,
    effort: ReasoningEffort,
    tools: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    with patch(_COMPLETION) as completion:
        llm._completion(
            prompt=[UserMessage(content="hello")],
            tools=tools,
            tool_choice=None,
            stream=False,
            parallel_tool_calls=False,
            reasoning_effort=effort,
        )
    return dict(completion.call_args.kwargs)


def _text_stream_chunks(text: str) -> list[litellm.ModelResponse]:
    return [
        litellm.ModelResponse(
            id="chatcmpl-1",
            choices=[
                litellm.Choices(
                    delta=Delta(role="assistant", content=text),
                    finish_reason="stop",
                    index=0,
                )
            ],
            created=0,
            model="gpt-5.6-sol",
            object="chat.completion.chunk",
        )
    ]


@pytest.mark.parametrize(
    "model_name",
    ["gpt-5.6-sol", "gpt-5.6", "gpt-5.6-terra", "gpt-5.6-luna", "gpt-5.5"],
)
def test_off_sends_explicit_none_to_native_openai_sol(model_name: str) -> None:
    kwargs = _sent_kwargs(_llm(model_name), ReasoningEffort.OFF)
    assert kwargs["model"] == f"openai/responses/{model_name}"
    assert kwargs["reasoning"] == {"effort": "none"}
    assert "reasoning_effort" not in kwargs


def test_low_still_sends_low_to_native_openai_sol() -> None:
    kwargs = _sent_kwargs(_llm("gpt-5.6-sol"), ReasoningEffort.LOW)
    assert kwargs["reasoning"] == {"effort": "low", "summary": "auto"}


def test_default_still_sends_medium_to_native_openai_sol() -> None:
    kwargs = _sent_kwargs(_llm("gpt-5.6-sol"), ReasoningEffort.AUTO)
    assert kwargs["reasoning"] == {"effort": "medium", "summary": "auto"}


def test_off_beats_a_high_admin_default() -> None:
    llm = _llm("gpt-5.6-sol", reasoning_effort_default=ReasoningEffort.HIGH)
    assert _sent_kwargs(llm, ReasoningEffort.OFF)["reasoning"] == {"effort": "none"}
    assert _sent_kwargs(llm, ReasoningEffort.AUTO)["reasoning"]["effort"] == "high"


def test_off_keeps_temperature_unchanged() -> None:
    llm = _llm("gpt-5.6-sol")
    off = _sent_kwargs(llm, ReasoningEffort.OFF)
    low = _sent_kwargs(llm, ReasoningEffort.LOW)
    assert off["temperature"] == low["temperature"]


@pytest.mark.parametrize("model_name", ["gpt-5", "gpt-5-mini", "o3", "gpt-5.5-pro"])
def test_off_still_omits_reasoning_for_other_native_openai_models(
    model_name: str,
) -> None:
    kwargs = _sent_kwargs(_llm(model_name), ReasoningEffort.OFF)
    assert "reasoning" not in kwargs
    assert "reasoning_effort" not in kwargs


def test_off_sends_explicit_none_on_azure() -> None:
    azure = _llm(
        "gpt-5.6-sol",
        model_provider=LlmProviderNames.AZURE,
        api_base="https://example.openai.azure.com",
        api_version="2025-04-01-preview",
    )
    kwargs = _sent_kwargs(azure, ReasoningEffort.OFF)
    assert kwargs["model"] == "azure/responses/gpt-5.6-sol"
    assert kwargs["reasoning"] == {"effort": "none"}
    assert "reasoning_effort" not in kwargs


def test_off_sends_explicit_none_on_litellm_proxy() -> None:
    proxy = _llm(
        "gpt-5.6-sol",
        model_provider=LlmProviderNames.LITELLM_PROXY,
        api_base="https://proxy.example",
    )
    kwargs = _sent_kwargs(proxy, ReasoningEffort.OFF)
    assert kwargs["model"] == "litellm_proxy/responses/gpt-5.6-sol"
    assert kwargs["reasoning"] == {"effort": "none"}


def test_off_sends_explicit_none_on_bifrost_chat_completions() -> None:
    bifrost = _llm(
        "openai/gpt-5.6-sol",
        model_provider=LlmProviderNames.BIFROST,
        api_base="https://bifrost.example/v1",
        custom_config={BIFROST_API_MODE_CONFIG_KEY: BIFROST_API_MODE_CHAT_COMPLETIONS},
    )
    kwargs = _sent_kwargs(bifrost, ReasoningEffort.OFF)
    assert kwargs["reasoning"] == {"effort": "none"}
    assert "reasoning_effort" not in kwargs


def test_off_sends_explicit_none_on_bifrost_responses() -> None:
    bifrost = _llm(
        "openai/gpt-5.6-sol",
        model_provider=LlmProviderNames.BIFROST,
        api_base="https://bifrost.example/v1",
        custom_config={BIFROST_API_MODE_CONFIG_KEY: BIFROST_API_MODE_RESPONSES},
    )
    kwargs = _sent_kwargs(bifrost, ReasoningEffort.OFF)
    assert kwargs["reasoning"] == {"effort": "none"}


def test_off_sends_explicit_none_on_openrouter() -> None:
    openrouter = _llm(
        "openai/gpt-5.6-sol",
        model_provider=LlmProviderNames.OPENROUTER,
    )
    kwargs = _sent_kwargs(openrouter, ReasoningEffort.OFF)
    assert kwargs["reasoning_effort"] == "none"
    assert "reasoning" not in kwargs


def test_off_sends_explicit_none_on_openai_compatible() -> None:
    compatible = _llm(
        "gpt-5.6-sol",
        model_provider=LlmProviderNames.OPENAI_COMPATIBLE,
        api_base="https://llm.example/v1",
    )
    kwargs = _sent_kwargs(compatible, ReasoningEffort.OFF)
    assert kwargs["reasoning"] == {"effort": "none"}


def test_bifrost_chat_tools_off_sends_only_reasoning_effort_none() -> None:
    bifrost = _llm(
        "openai/gpt-5.6-sol",
        model_provider=LlmProviderNames.BIFROST,
        api_base="https://bifrost.example/v1",
        custom_config={BIFROST_API_MODE_CONFIG_KEY: BIFROST_API_MODE_CHAT_COMPLETIONS},
    )
    kwargs = _sent_kwargs(bifrost, ReasoningEffort.OFF, tools=_TOOLS)
    assert kwargs["reasoning_effort"] == "none"
    assert "reasoning" not in kwargs


def test_gateway_none_is_strippable_on_rejection() -> None:
    calls: list[dict[str, Any]] = []

    def completion(**kwargs: Any) -> Any:
        calls.append(kwargs)
        if "reasoning" in kwargs:
            raise BadRequestError(
                message="Unsupported value for reasoning.effort",
                model="m",
                llm_provider="azure",
            )
        return None

    azure = _llm(
        "gpt-5.6-sol",
        model_provider=LlmProviderNames.AZURE,
        api_base="https://example.openai.azure.com",
        api_version="2025-04-01-preview",
    )
    with patch(_COMPLETION, side_effect=completion):
        azure._completion(
            prompt=[UserMessage(content="hello")],
            tools=None,
            tool_choice=None,
            stream=False,
            parallel_tool_calls=False,
            reasoning_effort=ReasoningEffort.OFF,
        )

    assert len(calls) == 2
    assert calls[0]["reasoning"] == {"effort": "none"}
    assert "reasoning" not in calls[1]


def test_azure_alias_unknown_to_registry_still_omits() -> None:
    azure = _llm(
        "gpt-5.6-sol-01-ptu",
        model_provider=LlmProviderNames.AZURE,
        api_base="https://example.openai.azure.com",
        api_version="2025-04-01-preview",
    )
    kwargs = _sent_kwargs(azure, ReasoningEffort.OFF)
    assert "reasoning" not in kwargs
    assert "reasoning_effort" not in kwargs


def test_capability_is_registry_gated() -> None:
    assert openai_model_supports_reasoning_none("gpt-5.6")
    assert openai_model_supports_reasoning_none("openai/gpt-5.6-sol")
    assert openai_model_supports_reasoning_none("openai.gpt-5.6-sol")
    assert openai_model_supports_reasoning_none("gpt-5.5")
    assert openai_model_supports_reasoning_none("gpt-5.4")
    assert openai_model_supports_reasoning_none("gpt-5.1")
    assert not openai_model_supports_reasoning_none("gpt-5")
    assert not openai_model_supports_reasoning_none("gpt-5-mini")
    assert not openai_model_supports_reasoning_none("gpt-5.5-pro")
    assert not openai_model_supports_reasoning_none("gpt-5-chat-latest")
    assert not openai_model_supports_reasoning_none("gpt-6-astra")
    assert not openai_model_supports_reasoning_none("gpt-5.6-sol-01-ptu")
    assert not openai_model_supports_reasoning_none("o3")


def test_explicit_none_survives_the_retry_ladder() -> None:
    calls: list[dict[str, Any]] = []

    def completion(**kwargs: Any) -> Any:
        calls.append(kwargs)
        if "temperature" in kwargs:
            raise BadRequestError(
                message="temperature is not supported", model="m", llm_provider="openai"
            )
        return None

    with patch(_COMPLETION, side_effect=completion):
        _llm("gpt-5.6-sol")._completion(
            prompt=[UserMessage(content="hello")],
            tools=None,
            tool_choice=None,
            stream=False,
            parallel_tool_calls=False,
            reasoning_effort=ReasoningEffort.OFF,
        )

    assert len(calls) == 2
    assert "temperature" in calls[0] and "temperature" not in calls[1]
    assert calls[0]["reasoning"] == {"effort": "none"}
    assert calls[1]["reasoning"] == {"effort": "none"}


_HISTORY: list[ChatMinimalTextMessage] = [
    ChatMinimalTextMessage(message="what is onyx", message_type=MessageType.USER)
]


def _search_llm() -> LitellmLLM:
    return _llm("gpt-5.6-sol", reasoning_effort_user_default=ReasoningEffort.HIGH)


def test_semantic_query_rephrase_sends_none() -> None:
    with patch(_COMPLETION, return_value=_text_stream_chunks("onyx")) as completion:
        semantic_query_rephrase(_HISTORY, _search_llm())
    assert completion.call_args.kwargs["reasoning"] == {"effort": "none"}


def test_keyword_query_expansion_sends_none() -> None:
    with patch(_COMPLETION, return_value=_text_stream_chunks("onyx")) as completion:
        keyword_query_expansion(_HISTORY, _search_llm())
    assert completion.call_args.kwargs["reasoning"] == {"effort": "none"}


def test_classify_section_relevance_sends_none() -> None:
    with patch(_COMPLETION, return_value=_text_stream_chunks("1")) as completion:
        classify_section_relevance(
            document_title="doc",
            section_text="body",
            user_query="what is onyx",
            llm=_search_llm(),
            section_above_text=None,
            section_below_text=None,
        )
    assert completion.call_args.kwargs["reasoning"] == {"effort": "none"}
