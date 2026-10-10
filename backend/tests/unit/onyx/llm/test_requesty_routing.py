"""Unit tests for Requesty routing in LitellmLLM.

Requesty is an OpenAI-compatible router, so like Nebius TokenFactory it goes
through the static chat completions surface: LiteLLM's `openai` provider, a
base URL ending in /v1, and the model id as the router expects it.
"""

from unittest.mock import patch

import litellm

from onyx.llm.api_surfaces import LlmApiSurface, resolve_api_surface
from onyx.llm.constants import LlmProviderNames
from onyx.llm.model_request import ChatCompletionMessage, UserMessage
from onyx.llm.multi_llm import LitellmLLM


def _make_llm(model_name: str, api_base: str) -> LitellmLLM:
    return LitellmLLM(
        api_key="test-key",
        model_provider=LlmProviderNames.REQUESTY,
        model_name=model_name,
        max_input_tokens=128_000,
        api_base=api_base,
    )


def _completion_kwargs(llm: LitellmLLM) -> dict:
    with patch("litellm.completion") as mock_completion:
        mock_completion.return_value = []
        messages: list[ChatCompletionMessage] = [UserMessage(content="Hi")]
        list(llm.stream_raw(messages))
        return dict(mock_completion.call_args.kwargs)


def test_provider_uses_the_chat_completions_surface() -> None:
    assert (
        resolve_api_surface(LlmProviderNames.REQUESTY, None)
        == LlmApiSurface.OPENAI_CHAT_COMPLETIONS
    )


def test_vendor_model_id_is_sent_unchanged() -> None:
    llm = _make_llm("anthropic/claude-haiku-4-5", "https://router.requesty.ai/v1")
    kwargs = _completion_kwargs(llm)
    assert kwargs["custom_llm_provider"] == "openai"
    assert kwargs["base_url"] == "https://router.requesty.ai/v1"
    assert kwargs["model"] == "anthropic/claude-haiku-4-5"


def test_openai_vendor_prefix_survives_litellm() -> None:
    """LiteLLM strips a leading "openai/" for the openai provider, so the id is
    prefixed once more and Requesty still receives "openai/gpt-4o-mini"."""
    kwargs = _completion_kwargs(
        _make_llm("openai/gpt-4o-mini", "https://router.requesty.ai/v1")
    )
    assert kwargs["model"] == "openai/openai/gpt-4o-mini"
    sent_model = litellm.get_llm_provider(
        model=kwargs["model"], custom_llm_provider="openai"
    )[0]
    assert sent_model == "openai/gpt-4o-mini"


def test_managed_model_id_is_sent_unchanged() -> None:
    kwargs = _completion_kwargs(
        _make_llm("claude-haiku-4-5", "https://router.requesty.ai/v1")
    )
    assert kwargs["model"] == "claude-haiku-4-5"


def test_bare_regional_base_is_coerced_to_v1() -> None:
    llm = _make_llm("openai/gpt-4o-mini", "https://router.eu.requesty.ai")
    assert llm._api_base == "https://router.eu.requesty.ai/v1"
