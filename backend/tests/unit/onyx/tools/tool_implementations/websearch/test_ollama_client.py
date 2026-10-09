from __future__ import annotations

from typing import Any
from typing import cast

import pytest
import requests

import onyx.tools.tool_implementations.web_search.clients.ollama_client as ollama_module
from onyx.tools.tool_implementations.web_search.clients.ollama_client import OllamaClient
from onyx.tools.tool_implementations.web_search.providers import (
    build_search_provider_from_config,
)
from shared_configs.enums import WebSearchProviderType


class DummyResponse:
    def __init__(
        self,
        *,
        status_code: int,
        payload: dict[str, Any] | None = None,
        text: str = "",
    ) -> None:
        self.status_code = status_code
        self._payload = payload
        self.text = text

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            http_error = requests.HTTPError(f"{self.status_code} Client Error")
            http_error.response = cast(requests.Response, self)
            raise http_error

    def json(self) -> dict[str, Any]:
        if self._payload is None:
            raise ValueError("No JSON payload")
        return self._payload


def test_search_maps_ollama_response(monkeypatch: pytest.MonkeyPatch) -> None:
    client = OllamaClient(api_key="test-key", num_results=5)

    def _mock_post(*args: Any, **kwargs: Any) -> DummyResponse:  # noqa: ARG001
        return DummyResponse(
            status_code=200,
            payload={
                "results": [
                    {
                        "title": "Result 1",
                        "url": "https://example.com/one",
                        "content": "Snippet 1",
                    },
                    {
                        "title": "Result without URL",
                        "content": "Should be skipped",
                    },
                ]
            },
        )

    monkeypatch.setattr(ollama_module.requests, "post", _mock_post)

    results = client.search("onyx")

    assert len(results) == 1
    assert results[0].title == "Result 1"
    assert results[0].link == "https://example.com/one"
    assert results[0].snippet == "Snippet 1"


def test_search_caps_count_to_ollama_max(monkeypatch: pytest.MonkeyPatch) -> None:
    client = OllamaClient(api_key="test-key", num_results=100)

    captured_max_results: int | None = None

    def _mock_post(*args: Any, **kwargs: Any) -> DummyResponse:  # noqa: ARG001
        nonlocal captured_max_results
        captured_max_results = kwargs["json"]["max_results"]
        return DummyResponse(status_code=200, payload={"results": []})

    monkeypatch.setattr(ollama_module.requests, "post", _mock_post)

    client.search("onyx")
    assert captured_max_results == 10  # OLLAMA_MAX_RESULTS


def test_search_returns_empty_on_no_results(monkeypatch: pytest.MonkeyPatch) -> None:
    client = OllamaClient(api_key="test-key", num_results=5)

    def _mock_post(*args: Any, **kwargs: Any) -> DummyResponse:  # noqa: ARG001
        return DummyResponse(status_code=200, payload={"results": []})

    monkeypatch.setattr(ollama_module.requests, "post", _mock_post)

    results = client.search("onyx")
    assert results == []


def test_build_ollama_provider_requires_api_key() -> None:
    """Test that Ollama provider requires an API key."""
    with pytest.raises(ValueError, match="API key is required"):
        build_search_provider_from_config(
            provider_type=WebSearchProviderType.OLLAMA,
            api_key=None,
            config={},
        )


def test_build_ollama_provider_with_api_key() -> None:
    """Test that Ollama provider can be built with an API key."""
    provider = build_search_provider_from_config(
        provider_type=WebSearchProviderType.OLLAMA,
        api_key="test-api-key",
        config={},
    )
    assert isinstance(provider, OllamaClient)


def test_build_ollama_provider_with_timeout() -> None:
    """Test that Ollama provider can be configured with a custom timeout."""
    provider = build_search_provider_from_config(
        provider_type=WebSearchProviderType.OLLAMA,
        api_key="test-api-key",
        config={"timeout_seconds": "20"},
    )
    assert isinstance(provider, OllamaClient)
    assert provider._timeout_seconds == 20  # noqa: SLF001


def test_build_ollama_provider_rejects_invalid_timeout() -> None:
    """Test that Ollama provider rejects invalid timeout values."""
    with pytest.raises(ValueError, match="timeout_seconds"):
        build_search_provider_from_config(
            provider_type=WebSearchProviderType.OLLAMA,
            api_key="test-api-key",
            config={"timeout_seconds": "not-an-int"},
        )


def test_build_ollama_provider_rejects_zero_timeout() -> None:
    """Test that Ollama provider rejects zero timeout."""
    with pytest.raises(ValueError, match="timeout_seconds"):
        build_search_provider_from_config(
            provider_type=WebSearchProviderType.OLLAMA,
            api_key="test-api-key",
            config={"timeout_seconds": "0"},
        )