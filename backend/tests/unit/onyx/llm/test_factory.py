from onyx.llm.constants import LlmProviderNames
from onyx.llm.factory import _build_provider_extra_headers
from onyx.llm.well_known_providers.constants import OLLAMA_API_KEY_CONFIG_KEY


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
