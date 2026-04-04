from __future__ import annotations

from typing import Any
from typing import cast

import pytest
import requests
from fastapi import HTTPException

import onyx.tools.tool_implementations.web_search.clients.baidu_client as baidu_module
from onyx.tools.tool_implementations.web_search.clients.baidu_client import (
    BaiduClient,
)


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


def test_search_maps_baidu_response(monkeypatch: pytest.MonkeyPatch) -> None:
    client = BaiduClient(api_key="test-key", num_results=5)

    def _mock_post(*args: Any, **kwargs: Any) -> DummyResponse:  # noqa: ARG001
        return DummyResponse(
            status_code=200,
            payload={
                "references": [
                    {
                        "title": "Result 1",
                        "url": "https://example.com/one",
                        "snippet": "Snippet 1",
                        "website": "Example Site",
                        "date": "2025-05-23 00:00:00",
                        "type": "web",
                    },
                    {
                        "title": "Image result",
                        "url": "https://example.com/image",
                        "snippet": "Should be skipped",
                        "type": "image",
                    },
                    {
                        "title": "Result without URL",
                        "snippet": "Should be skipped",
                        "type": "web",
                    },
                ]
            },
        )

    monkeypatch.setattr(baidu_module.requests, "post", _mock_post)

    results = client.search("onyx")

    assert len(results) == 1
    assert results[0].title == "Result 1"
    assert results[0].link == "https://example.com/one"
    assert results[0].snippet == "Snippet 1"
    assert results[0].author == "Example Site"
    assert results[0].published_date is not None


def test_search_caps_count_to_baidu_max(monkeypatch: pytest.MonkeyPatch) -> None:
    client = BaiduClient(api_key="test-key", num_results=100)
    captured_top_k: int | None = None

    def _mock_post(*args: Any, **kwargs: Any) -> DummyResponse:  # noqa: ARG001
        nonlocal captured_top_k
        captured_top_k = kwargs["json"]["resource_type_filter"][0]["top_k"]
        return DummyResponse(status_code=200, payload={"references": []})

    monkeypatch.setattr(baidu_module.requests, "post", _mock_post)

    client.search("onyx")

    assert captured_top_k == 50


def test_search_uses_expected_headers(monkeypatch: pytest.MonkeyPatch) -> None:
    client = BaiduClient(api_key="test-key", num_results=5)
    captured_headers: dict[str, str] | None = None

    def _mock_post(*args: Any, **kwargs: Any) -> DummyResponse:  # noqa: ARG001
        nonlocal captured_headers
        captured_headers = kwargs["headers"]
        return DummyResponse(status_code=200, payload={"references": []})

    monkeypatch.setattr(baidu_module.requests, "post", _mock_post)

    client.search("onyx")

    assert captured_headers is not None
    assert captured_headers["Authorization"] == "Bearer test-key"
    assert captured_headers["X-Appbuilder-Authorization"] == "Bearer test-key"


def test_search_raises_descriptive_error_on_http_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = BaiduClient(api_key="test-key", num_results=5)

    def _mock_post(*args: Any, **kwargs: Any) -> DummyResponse:  # noqa: ARG001
        return DummyResponse(
            status_code=401,
            payload={"code": "110", "message": "Unauthorized"},
        )

    monkeypatch.setattr(baidu_module.requests, "post", _mock_post)

    with pytest.raises(ValueError, match="status 401"):
        client.search("onyx")


def test_search_does_not_retry_non_retryable_http_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = BaiduClient(api_key="test-key", num_results=5)
    calls = 0

    def _mock_post(*args: Any, **kwargs: Any) -> DummyResponse:  # noqa: ARG001
        nonlocal calls
        calls += 1
        return DummyResponse(
            status_code=401,
            payload={"code": "110", "message": "Unauthorized"},
        )

    monkeypatch.setattr(baidu_module.requests, "post", _mock_post)

    with pytest.raises(ValueError, match="status 401"):
        client.search("onyx")
    assert calls == 1


def test_constructor_rejects_invalid_timeout() -> None:
    with pytest.raises(ValueError, match="timeout_seconds"):
        BaiduClient(api_key="test-key", timeout_seconds=0)


def test_test_connection_maps_invalid_key_errors() -> None:
    client = BaiduClient(api_key="test-key")

    def _mock_search(query: str) -> list[Any]:  # noqa: ARG001
        raise ValueError("Baidu search failed (status 401): Unauthorized")

    client.search = _mock_search  # type: ignore[method-assign]

    with pytest.raises(HTTPException, match="Invalid Baidu API key"):
        client.test_connection()


def test_test_connection_maps_rate_limit_errors() -> None:
    client = BaiduClient(api_key="test-key")

    def _mock_search(query: str) -> list[Any]:  # noqa: ARG001
        raise ValueError("Baidu search failed (status 429): Too many requests")

    client.search = _mock_search  # type: ignore[method-assign]

    with pytest.raises(HTTPException, match="rate limit exceeded"):
        client.test_connection()


def test_test_connection_propagates_unexpected_errors() -> None:
    client = BaiduClient(api_key="test-key")

    def _mock_search(query: str) -> list[Any]:  # noqa: ARG001
        raise RuntimeError("unexpected parsing bug")

    client.search = _mock_search  # type: ignore[method-assign]

    with pytest.raises(RuntimeError, match="unexpected parsing bug"):
        client.test_connection()
