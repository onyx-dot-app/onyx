import pytest

from onyx.tools.tool_implementations.web_search.providers import (
    build_search_provider_from_config,
)
from onyx.tools.tool_implementations.web_search.providers import (
    provider_requires_api_key,
)
from shared_configs.enums import WebSearchProviderType


def test_provider_requires_api_key() -> None:
    """Test that provider_requires_api_key correctly identifies which providers need API keys."""
    assert provider_requires_api_key(WebSearchProviderType.EXA) is True
    assert provider_requires_api_key(WebSearchProviderType.BRAVE) is True
    assert provider_requires_api_key(WebSearchProviderType.SERPER) is True
    assert provider_requires_api_key(WebSearchProviderType.GOOGLE_PSE) is True
    assert provider_requires_api_key(WebSearchProviderType.SEARXNG) is False


def test_build_searxng_provider_without_api_key() -> None:
    """Test that SearXNG provider can be built without an API key."""
    provider = build_search_provider_from_config(
        provider_type=WebSearchProviderType.SEARXNG,
        api_key=None,
        config={"searxng_base_url": "http://localhost:8080"},
    )
    assert provider is not None


def test_build_searxng_provider_requires_base_url() -> None:
    """Test that SearXNG provider requires a base URL."""
    with pytest.raises(ValueError, match="Please provide a URL"):
        build_search_provider_from_config(
            provider_type=WebSearchProviderType.SEARXNG,
            api_key=None,
            config={},
        )


def test_build_exa_provider_requires_api_key() -> None:
    """Test that Exa provider requires an API key."""
    with pytest.raises(ValueError, match="API key is required"):
        build_search_provider_from_config(
            provider_type=WebSearchProviderType.EXA,
            api_key=None,
            config={},
        )


def test_build_brave_provider_requires_api_key() -> None:
    """Test that Brave provider requires an API key."""
    with pytest.raises(ValueError, match="API key is required"):
        build_search_provider_from_config(
            provider_type=WebSearchProviderType.BRAVE,
            api_key=None,
            config={},
        )


def test_build_serper_provider_requires_api_key() -> None:
    """Test that Serper provider requires an API key."""
    with pytest.raises(ValueError, match="API key is required"):
        build_search_provider_from_config(
            provider_type=WebSearchProviderType.SERPER,
            api_key=None,
            config={},
        )


def test_build_google_pse_provider_requires_api_key() -> None:
    """Test that Google PSE provider requires an API key."""
    with pytest.raises(ValueError, match="API key is required"):
        build_search_provider_from_config(
            provider_type=WebSearchProviderType.GOOGLE_PSE,
            api_key=None,
            config={"search_engine_id": "test-cx"},
        )


def test_build_google_pse_provider_requires_search_engine_id() -> None:
    """Test that Google PSE provider requires a search engine ID."""
    with pytest.raises(ValueError, match="search engine id"):
        build_search_provider_from_config(
            provider_type=WebSearchProviderType.GOOGLE_PSE,
            api_key="test-api-key",
            config={},
        )
