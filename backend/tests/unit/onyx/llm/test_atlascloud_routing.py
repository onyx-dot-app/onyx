"""Unit tests for Atlas Cloud routing in LitellmLLM.

LiteLLM has no `atlascloud` provider, so a `atlascloud/<model>` model string
fails with "LLM Provider NOT provided". The gateway is OpenAI-compatible, so it
is routed through the OpenAI-compatible surface like Nebius TokenFactory:
`custom_llm_provider="openai"`, a bare model id, and a `/v1` base.
"""

from unittest.mock import patch

from onyx.llm.api_surfaces import LlmApiSurface, resolve_api_surface
from onyx.llm.constants import LlmProviderNames
from onyx.llm.model_request import ChatCompletionMessage, UserMessage
from onyx.llm.multi_llm import LitellmLLM
from onyx.llm.well_known_providers.constants import ATLASCLOUD_DEFAULT_API_BASE


def _make_llm(
    model_name: str = "deepseek-ai/DeepSeek-V3.1-Terminus",
    api_base: str | None = None,
) -> LitellmLLM:
    return LitellmLLM(
        api_key="atlas-test-key",
        model_provider=LlmProviderNames.ATLASCLOUD,
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


def test_provider_uses_the_openai_chat_completions_surface() -> None:
    assert (
        resolve_api_surface(LlmProviderNames.ATLASCLOUD, None)
        is LlmApiSurface.OPENAI_CHAT_COMPLETIONS
    )


def test_request_is_routed_as_openai_with_a_bare_model_id() -> None:
    kwargs = _completion_kwargs(_make_llm())
    assert kwargs["custom_llm_provider"] == "openai"
    assert kwargs["model"] == "deepseek-ai/DeepSeek-V3.1-Terminus"
    assert not kwargs["model"].startswith("atlascloud/")


def test_missing_api_base_defaults_to_the_gateway_not_openai() -> None:
    llm = _make_llm()
    assert llm._api_base == ATLASCLOUD_DEFAULT_API_BASE
    assert _completion_kwargs(llm)["base_url"] == ATLASCLOUD_DEFAULT_API_BASE


def test_explicit_api_base_gets_a_v1_suffix() -> None:
    llm = _make_llm(api_base="https://api.atlascloud.ai")
    assert _completion_kwargs(llm)["base_url"] == "https://api.atlascloud.ai/v1"
