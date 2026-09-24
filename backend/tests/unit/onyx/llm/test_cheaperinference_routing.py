"""Unit tests for Cheaper Inference routing in LitellmLLM.

Cheaper Inference is an OpenAI-compatible gateway. LiteLLM has no provider
integration of that name, so Onyx reaches it by impersonating LiteLLM's
`openai` provider and pointing `base_url` at the gateway. These tests lock that
mapping down, because a change to it silently breaks every request.
"""

from unittest.mock import patch

from onyx.llm.api_surfaces import LlmApiSurface
from onyx.llm.constants import LlmProviderNames
from onyx.llm.models import LanguageModelInput, UserMessage
from onyx.llm.multi_llm import LitellmLLM

_API_BASE = "https://api.cheaperinference.com/v1"


def _make_llm(
    api_base: str = _API_BASE,
    model_name: str = "gpt-5-mini",
) -> LitellmLLM:
    return LitellmLLM(
        api_key="ci-test-key",
        timeout=30,
        model_provider=LlmProviderNames.CHEAPERINFERENCE,
        model_name=model_name,
        max_input_tokens=400_000,
        api_base=api_base,
    )


def _completion_kwargs(llm: LitellmLLM) -> dict:
    with patch("litellm.completion") as mock_completion:
        mock_completion.return_value = []
        messages: LanguageModelInput = [UserMessage(content="Hi")]
        list(llm.stream(messages))
        return dict(mock_completion.call_args.kwargs)


def test_routes_via_openai_with_the_gateway_base() -> None:
    llm = _make_llm()
    assert llm._api_surface is LlmApiSurface.OPENAI_CHAT_COMPLETIONS
    assert llm._custom_llm_provider == "openai"
    assert llm._api_base == _API_BASE

    kwargs = _completion_kwargs(llm)
    assert kwargs["custom_llm_provider"] == "openai"
    assert kwargs["base_url"] == _API_BASE
    # OpenAI-compatible proxies send a bare model name.
    assert kwargs["model"] == "gpt-5-mini"


def test_coerces_bare_base_to_v1() -> None:
    llm = _make_llm(api_base="https://api.cheaperinference.com")
    assert llm._api_base == _API_BASE


def test_trailing_slash_does_not_duplicate_v1() -> None:
    llm = _make_llm(api_base="https://api.cheaperinference.com/v1/")
    assert llm._api_base == _API_BASE
