"""Unit tests for OrcaRouter's OpenAI-compatible routing in LitellmLLM.

OrcaRouter is a named OpenAI-compatible gateway with a single fixed API surface
(OpenAI Chat Completions). These tests lock down the routing: custom_llm_provider
"openai", a `/v1`-suffixed base, and a bare model name.
"""

from unittest.mock import patch

from onyx.llm.api_surfaces import LlmApiSurface
from onyx.llm.constants import LlmProviderNames
from onyx.llm.models import LanguageModelInput, UserMessage
from onyx.llm.multi_llm import LitellmLLM
from onyx.llm.well_known_providers.constants import (
    ORCAROUTER_DEFAULT_API_BASE,
)


def _make_orcarouter_llm(api_base: str) -> LitellmLLM:
    return LitellmLLM(
        api_key="sk-orca-test",
        timeout=30,
        model_provider=LlmProviderNames.ORCAROUTER,
        model_name="orcarouter/fusion",
        max_input_tokens=128_000,
        api_base=api_base,
    )


def _completion_kwargs(llm: LitellmLLM) -> dict:
    with patch("litellm.completion") as mock_completion:
        mock_completion.return_value = []
        messages: LanguageModelInput = [UserMessage(content="Hi")]
        list(llm.stream(messages))
        return dict(mock_completion.call_args.kwargs)


def test_routes_via_openai_with_v1_base() -> None:
    llm = _make_orcarouter_llm(ORCAROUTER_DEFAULT_API_BASE)
    assert llm._custom_llm_provider == "openai"
    assert llm._api_base == ORCAROUTER_DEFAULT_API_BASE
    assert llm._api_surface is LlmApiSurface.OPENAI_CHAT_COMPLETIONS

    kwargs = _completion_kwargs(llm)
    assert kwargs["custom_llm_provider"] == "openai"
    assert kwargs["base_url"] == ORCAROUTER_DEFAULT_API_BASE
    # OpenAI-compatible proxies send a bare model name.
    assert kwargs["model"] == "orcarouter/fusion"


def test_bare_base_coerced_to_v1() -> None:
    llm = _make_orcarouter_llm("https://api.orcarouter.ai")
    assert llm._api_base == ORCAROUTER_DEFAULT_API_BASE
