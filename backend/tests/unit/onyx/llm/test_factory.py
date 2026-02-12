from unittest.mock import patch

from onyx.llm.constants import LlmProviderNames
from onyx.llm.factory import _build_provider_extra_headers
from onyx.llm.factory import get_llm
from onyx.llm.factory import llm_from_provider
from onyx.llm.well_known_providers.constants import OLLAMA_API_KEY_CONFIG_KEY
from onyx.server.manage.llm.models import LLMProviderView
from onyx.server.manage.llm.models import ModelConfigurationView


def test_build_provider_extra_headers_adds_bearer_for_ollama_api_key() -> None:
    headers = _build_provider_extra_headers(
        LlmProviderNames.OLLAMA_CHAT,
        {OLLAMA_API_KEY_CONFIG_KEY: "  test-key  "},
    )

    assert headers == {"Authorization": "Bearer test-key"}


def test_build_provider_extra_headers_keeps_existing_bearer_prefix() -> None:
    headers = _build_provider_extra_headers(
        LlmProviderNames.OLLAMA_CHAT,
        {OLLAMA_API_KEY_CONFIG_KEY: "bearer test-key"},
    )

    assert headers == {"Authorization": "bearer test-key"}


def test_build_provider_extra_headers_ignores_empty_ollama_api_key() -> None:
    headers = _build_provider_extra_headers(
        LlmProviderNames.OLLAMA_CHAT,
        {OLLAMA_API_KEY_CONFIG_KEY: "   "},
    )

    assert headers == {}


def _build_provider_view(
    provider: str,
    max_input_tokens: int | None,
) -> LLMProviderView:
    return LLMProviderView(
        id=1,
        name="test-provider",
        provider=provider,
        default_model_name="test-model",
        model_configurations=[
            ModelConfigurationView(
                name="test-model",
                is_visible=True,
                max_input_tokens=max_input_tokens,
                supports_image_input=False,
            )
        ],
        api_key=None,
        api_base="http://localhost:11434",
        api_version=None,
        custom_config=None,
        is_public=True,
        is_auto_mode=False,
        groups=[],
        personas=[],
        deployment_name=None,
        default_vision_model=None,
    )


def test_get_llm_sets_ollama_num_ctx_model_kwarg() -> None:
    with patch("onyx.llm.factory.LitellmLLM") as mock_litellm_llm:
        get_llm(
            provider=LlmProviderNames.OLLAMA_CHAT,
            model="test-model",
            deployment_name=None,
            max_input_tokens=4096,
            model_kwargs={"num_ctx": 8192},
        )

        kwargs = mock_litellm_llm.call_args.kwargs
        assert kwargs["model_kwargs"] == {"num_ctx": 8192}


def test_get_llm_does_not_set_ollama_num_ctx_for_non_ollama_provider() -> None:
    with patch("onyx.llm.factory.LitellmLLM") as mock_litellm_llm:
        get_llm(
            provider=LlmProviderNames.OPENAI,
            model="gpt-4o-mini",
            deployment_name=None,
            max_input_tokens=4096,
        )

        kwargs = mock_litellm_llm.call_args.kwargs
        assert kwargs["model_kwargs"] == {}


def test_llm_from_provider_passes_configured_ollama_num_ctx() -> None:
    provider = _build_provider_view(
        provider=LlmProviderNames.OLLAMA_CHAT,
        max_input_tokens=16384,
    )

    with patch("onyx.llm.factory.get_llm") as mock_get_llm:
        llm_from_provider(
            model_name="test-model",
            llm_provider=provider,
        )

        kwargs = mock_get_llm.call_args.kwargs
        assert kwargs["max_input_tokens"] == 16384
        assert kwargs["model_kwargs"] == {"num_ctx": 16384}


def test_llm_from_provider_omits_ollama_num_ctx_when_model_context_unknown() -> None:
    provider = _build_provider_view(
        provider=LlmProviderNames.OLLAMA_CHAT,
        max_input_tokens=None,
    )

    with (
        patch(
            "onyx.llm.factory.get_max_input_tokens_from_llm_provider",
            return_value=32000,
        ),
        patch("onyx.llm.factory.get_llm") as mock_get_llm,
    ):
        llm_from_provider(
            model_name="test-model",
            llm_provider=provider,
        )

        kwargs = mock_get_llm.call_args.kwargs
        assert kwargs["max_input_tokens"] == 32000
        assert kwargs["model_kwargs"] == {}


def test_llm_from_provider_never_sets_ollama_num_ctx_for_non_ollama_provider() -> None:
    provider = _build_provider_view(
        provider=LlmProviderNames.OPENAI,
        max_input_tokens=16384,
    )

    with patch("onyx.llm.factory.get_llm") as mock_get_llm:
        llm_from_provider(
            model_name="test-model",
            llm_provider=provider,
        )

        kwargs = mock_get_llm.call_args.kwargs
        assert kwargs["max_input_tokens"] == 16384
        assert kwargs["model_kwargs"] == {}
