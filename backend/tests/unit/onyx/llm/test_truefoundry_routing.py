"""Unit tests for TrueFoundry routing in LitellmLLM.

TrueFoundry mounts the OpenAI routes directly on its gateway base (the SaaS host
or a self-hosted path), so the base must reach LiteLLM without the `/v1` suffix
other OpenAI-compatible providers get, and the `<account>/<model>` id must go
out as-is.
"""

from unittest.mock import patch

from onyx.llm.api_surfaces import LlmApiSurface, resolve_api_surface
from onyx.llm.constants import LlmProviderNames
from onyx.llm.model_request import ChatCompletionMessage, UserMessage
from onyx.llm.multi_llm import LitellmLLM


def _make_llm(
    api_base: str = "https://gateway.truefoundry.ai",
    model_name: str = "openai-main/gpt-4o-mini",
) -> LitellmLLM:
    return LitellmLLM(
        api_key="tfy-test-key",
        model_provider=LlmProviderNames.TRUEFOUNDRY,
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
        resolve_api_surface(LlmProviderNames.TRUEFOUNDRY, None)
        is LlmApiSurface.OPENAI_CHAT_COMPLETIONS
    )
    assert _make_llm()._custom_llm_provider == "openai"


def test_bare_base_is_not_coerced_to_v1() -> None:
    llm = _make_llm()
    assert llm._api_base == "https://gateway.truefoundry.ai"

    kwargs = _completion_kwargs(llm)
    assert kwargs["custom_llm_provider"] == "openai"
    assert kwargs["base_url"] == "https://gateway.truefoundry.ai"
    assert kwargs["model"] == "openai-main/gpt-4o-mini"


def test_self_hosted_base_keeps_its_path_and_drops_the_trailing_slash() -> None:
    llm = _make_llm(api_base="https://acme.truefoundry.cloud/api/llm/")
    assert llm._api_base == "https://acme.truefoundry.cloud/api/llm"


def test_explicit_v1_base_is_passed_through() -> None:
    llm = _make_llm(api_base="https://gateway.truefoundry.ai/v1")
    assert llm._api_base == "https://gateway.truefoundry.ai/v1"
