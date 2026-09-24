"""Unit tests for Vercel AI Gateway routing in LitellmTransport.

Unlike Portkey and Bifrost, this provider is reached through LiteLLM's own
integration rather than an OpenAI-compatible surface, so it has no
`api_surfaces` entry. LiteLLM owns the base URL and the wire protocol; Onyx
only has to hand it a correctly prefixed model string. The gateway namespaces
its models as `vendor/model`, which nests inside LiteLLM's own
`provider/model` convention, so these tests lock that spelling down.
"""

from unittest.mock import patch

from onyx.llm.api_surfaces import resolve_api_surface
from onyx.llm.constants import LlmProviderNames
from onyx.llm.litellm_models import LanguageModelInput, UserMessage
from onyx.llm.multi_llm import LitellmTransport


def _make_llm(
    model_name: str = "anthropic/claude-sonnet-4.5",
    api_base: str | None = None,
) -> LitellmTransport:
    return LitellmTransport(
        api_key="vck-test-key",
        model_provider=LlmProviderNames.VERCEL_AI_GATEWAY,
        model_name=model_name,
        max_input_tokens=200_000,
        api_base=api_base,
    )


def _completion_kwargs(llm: LitellmTransport) -> dict:
    with patch("litellm.completion") as mock_completion:
        mock_completion.return_value = []
        messages: LanguageModelInput = [UserMessage(content="Hi")]
        list(llm.stream(messages))
        return dict(mock_completion.call_args.kwargs)


def test_provider_has_no_openai_compatible_surface() -> None:
    """Routing goes through LiteLLM's native provider, not a coerced surface."""
    assert resolve_api_surface(LlmProviderNames.VERCEL_AI_GATEWAY, None) is None


def test_namespaced_model_keeps_the_provider_prefix() -> None:
    kwargs = _completion_kwargs(_make_llm())
    assert kwargs["model"] == "vercel_ai_gateway/anthropic/claude-sonnet-4.5"


def test_base_url_is_left_to_litellm_when_unset() -> None:
    """LiteLLM defaults the base to the gateway, so Onyx must not invent one."""
    llm = _make_llm()
    assert llm._api_base is None
    assert _completion_kwargs(llm)["base_url"] is None


def test_explicit_api_base_is_passed_through_unchanged() -> None:
    """No `/v1` coercion: that only applies to OpenAI-compatible surfaces."""
    llm = _make_llm(api_base="https://ai-gateway.vercel.sh")
    assert llm._api_base == "https://ai-gateway.vercel.sh"
    assert _completion_kwargs(llm)["base_url"] == "https://ai-gateway.vercel.sh"
