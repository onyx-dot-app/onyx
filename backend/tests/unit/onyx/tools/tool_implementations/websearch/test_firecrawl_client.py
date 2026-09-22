from __future__ import annotations

from typing import Any, cast

import pytest
import requests
from fastapi import HTTPException

import onyx.tools.tool_implementations.web_search.clients.firecrawl_client as firecrawl_module
from onyx.tools.tool_implementations.web_search.clients.firecrawl_client import (
    FIRECRAWL_SEARCH_URL,
    FirecrawlSearchClient,
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


def _no_sleep(monkeypatch: pytest.MonkeyPatch) -> None:
    # retry_builder (tenacity) sleeps between attempts; keep retry tests fast.
    monkeypatch.setattr("time.sleep", lambda _seconds: None)


def test_search_maps_firecrawl_response(monkeypatch: pytest.MonkeyPatch) -> None:
    client = FirecrawlSearchClient(api_key="test-key", num_results=5)

    def _mock_post(*args: Any, **kwargs: Any) -> DummyResponse:  # noqa: ARG001
        return DummyResponse(
            status_code=200,
            payload={
                "success": True,
                "data": {
                    "web": [
                        {
                            "url": "https://example.com/one",
                            "title": " Result 1 ",
                            "description": "Snippet 1",
                            "position": 1,
                        },
                        {
                            "title": "Result without URL",
                            "description": "Should be skipped",
                        },
                        "not-a-dict",
                    ]
                },
            },
        )

    monkeypatch.setattr(firecrawl_module.requests, "post", _mock_post)

    results = client.search("onyx")

    assert len(results) == 1
    assert results[0].title == "Result 1"
    assert results[0].link == "https://example.com/one"
    assert results[0].snippet == "Snippet 1"
    assert results[0].author is None
    assert results[0].published_date is None


def test_search_sends_expected_request(monkeypatch: pytest.MonkeyPatch) -> None:
    client = FirecrawlSearchClient(
        api_key="test-key",
        num_results=500,
        tbs="QDR:D",
        location="Berlin,Germany",
        country="de",
    )
    captured_url: str | None = None
    captured_body: dict[str, Any] | None = None
    captured_headers: dict[str, str] | None = None

    def _mock_post(url: str, **kwargs: Any) -> DummyResponse:
        nonlocal captured_url, captured_body, captured_headers
        captured_url = url
        captured_body = kwargs["json"]
        captured_headers = kwargs["headers"]
        return DummyResponse(
            status_code=200, payload={"success": True, "data": {"web": []}}
        )

    monkeypatch.setattr(firecrawl_module.requests, "post", _mock_post)

    client.search("onyx")

    assert captured_url == FIRECRAWL_SEARCH_URL
    assert captured_headers is not None
    assert captured_headers["Authorization"] == "Bearer test-key"
    assert captured_body is not None
    assert captured_body["query"] == "onyx"
    assert captured_body["limit"] == 100
    assert captured_body["sources"] == ["web"]
    assert captured_body["tbs"] == "qdr:d"
    assert captured_body["location"] == "Berlin,Germany"
    assert captured_body["country"] == "DE"


def test_search_omits_unset_optional_params(monkeypatch: pytest.MonkeyPatch) -> None:
    client = FirecrawlSearchClient(api_key="test-key", num_results=5)
    captured_body: dict[str, Any] | None = None

    def _mock_post(*args: Any, **kwargs: Any) -> DummyResponse:  # noqa: ARG001
        nonlocal captured_body
        captured_body = kwargs["json"]
        return DummyResponse(
            status_code=200, payload={"success": True, "data": {"web": []}}
        )

    monkeypatch.setattr(firecrawl_module.requests, "post", _mock_post)

    client.search("onyx")

    assert captured_body == {"query": "onyx", "limit": 5, "sources": ["web"]}


def test_search_uses_custom_base_url(monkeypatch: pytest.MonkeyPatch) -> None:
    client = FirecrawlSearchClient(
        api_key="test-key", base_url="https://firecrawl.internal/v2/search"
    )
    captured_url: str | None = None

    def _mock_post(url: str, **kwargs: Any) -> DummyResponse:  # noqa: ARG001
        nonlocal captured_url
        captured_url = url
        return DummyResponse(
            status_code=200, payload={"success": True, "data": {"web": []}}
        )

    monkeypatch.setattr(firecrawl_module.requests, "post", _mock_post)

    client.search("onyx")

    assert captured_url == "https://firecrawl.internal/v2/search"


def test_supports_site_filter() -> None:
    client = FirecrawlSearchClient(api_key="test-key")
    assert client.supports_site_filter is True


def test_search_raises_descriptive_error_on_http_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = FirecrawlSearchClient(api_key="test-key", num_results=5)

    def _mock_post(*args: Any, **kwargs: Any) -> DummyResponse:  # noqa: ARG001
        return DummyResponse(
            status_code=401,
            payload={"success": False, "error": "Unauthorized: Invalid token"},
        )

    monkeypatch.setattr(firecrawl_module.requests, "post", _mock_post)

    with pytest.raises(ValueError, match="status 401.*Invalid token"):
        client.search("onyx")


def test_search_does_not_retry_non_retryable_http_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = FirecrawlSearchClient(api_key="test-key", num_results=5)
    calls = 0

    def _mock_post(*args: Any, **kwargs: Any) -> DummyResponse:  # noqa: ARG001
        nonlocal calls
        calls += 1
        return DummyResponse(
            status_code=402,
            payload={"success": False, "error": "Payment Required"},
        )

    monkeypatch.setattr(firecrawl_module.requests, "post", _mock_post)

    with pytest.raises(ValueError, match="status 402"):
        client.search("onyx")
    assert calls == 1


def test_search_retries_rate_limit_then_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _no_sleep(monkeypatch)
    client = FirecrawlSearchClient(api_key="test-key", num_results=5)
    calls = 0

    def _mock_post(*args: Any, **kwargs: Any) -> DummyResponse:  # noqa: ARG001
        nonlocal calls
        calls += 1
        return DummyResponse(
            status_code=429,
            payload={"success": False, "error": "Rate limit exceeded"},
        )

    monkeypatch.setattr(firecrawl_module.requests, "post", _mock_post)

    with pytest.raises(ValueError, match="status 429"):
        client.search("onyx")
    assert calls == 3


def test_search_retries_transient_request_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _no_sleep(monkeypatch)
    client = FirecrawlSearchClient(api_key="test-key", num_results=5)
    calls = 0

    def _mock_post(*args: Any, **kwargs: Any) -> DummyResponse:  # noqa: ARG001
        nonlocal calls
        calls += 1
        if calls < 3:
            raise requests.ConnectionError("connection reset")
        return DummyResponse(
            status_code=200,
            payload={
                "success": True,
                "data": {"web": [{"url": "https://example.com", "title": "ok"}]},
            },
        )

    monkeypatch.setattr(firecrawl_module.requests, "post", _mock_post)

    results = client.search("onyx")

    assert calls == 3
    assert len(results) == 1


def test_search_retries_non_json_body_then_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _no_sleep(monkeypatch)
    client = FirecrawlSearchClient(api_key="test-key", num_results=5)
    calls = 0

    def _mock_post(*args: Any, **kwargs: Any) -> DummyResponse:  # noqa: ARG001
        nonlocal calls
        calls += 1
        # payload=None makes DummyResponse.json() raise, like a proxy HTML page.
        return DummyResponse(status_code=200, payload=None, text="<html>502</html>")

    monkeypatch.setattr(firecrawl_module.requests, "post", _mock_post)

    with pytest.raises(ValueError, match="non-JSON"):
        client.search("onyx")
    assert calls == 3


def test_search_rejects_malformed_web_section(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = FirecrawlSearchClient(api_key="test-key", num_results=5)

    def _mock_post(*args: Any, **kwargs: Any) -> DummyResponse:  # noqa: ARG001
        return DummyResponse(
            status_code=200, payload={"success": True, "data": {"web": 42}}
        )

    monkeypatch.setattr(firecrawl_module.requests, "post", _mock_post)

    with pytest.raises(ValueError, match="data.web"):
        client.search("onyx")


def test_search_returns_empty_when_web_section_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = FirecrawlSearchClient(api_key="test-key", num_results=5)

    def _mock_post(*args: Any, **kwargs: Any) -> DummyResponse:  # noqa: ARG001
        return DummyResponse(
            status_code=200, payload={"success": True, "data": {"news": []}}
        )

    monkeypatch.setattr(firecrawl_module.requests, "post", _mock_post)

    assert client.search("onyx") == []


def test_constructor_accepts_custom_tbs_range() -> None:
    client = FirecrawlSearchClient(
        api_key="test-key", tbs="cdr:1,cd_min:1/1/2026,cd_max:2/1/2026"
    )
    assert client._tbs == "cdr:1,cd_min:1/1/2026,cd_max:2/1/2026"  # noqa: SLF001


def test_search_raises_on_success_false_body(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = FirecrawlSearchClient(api_key="test-key", num_results=5)

    def _mock_post(*args: Any, **kwargs: Any) -> DummyResponse:  # noqa: ARG001
        return DummyResponse(
            status_code=200,
            payload={"success": False, "error": "Search backend unavailable"},
        )

    monkeypatch.setattr(firecrawl_module.requests, "post", _mock_post)

    with pytest.raises(ValueError, match="Search backend unavailable"):
        client.search("onyx")


@pytest.mark.parametrize(
    ("kwargs", "expected_error"),
    [
        ({"country": "USA"}, "country"),
        ({"tbs": "last-week"}, "tbs"),
        ({"base_url": "firecrawl.internal/v2/search"}, "base_url"),
        ({"timeout_seconds": 0}, "timeout_seconds"),
    ],
)
def test_constructor_rejects_invalid_config_values(
    kwargs: dict[str, Any],
    expected_error: str,
) -> None:
    with pytest.raises(ValueError, match=expected_error):
        FirecrawlSearchClient(api_key="test-key", **kwargs)


def test_test_connection_maps_invalid_key_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = FirecrawlSearchClient(api_key="test-key")

    def _mock_search(query: str) -> list[Any]:  # noqa: ARG001
        raise ValueError("Firecrawl search failed (status 401): Unauthorized")

    monkeypatch.setattr(client, "search", _mock_search)

    with pytest.raises(HTTPException, match="Invalid Firecrawl API key"):
        client.test_connection()


def test_test_connection_maps_insufficient_credit_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = FirecrawlSearchClient(api_key="test-key")

    def _mock_search(query: str) -> list[Any]:  # noqa: ARG001
        raise ValueError("Firecrawl search failed (status 402): Payment Required")

    monkeypatch.setattr(client, "search", _mock_search)

    with pytest.raises(HTTPException, match="insufficient credits"):
        client.test_connection()


def test_test_connection_maps_rate_limit_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = FirecrawlSearchClient(api_key="test-key")

    def _mock_search(query: str) -> list[Any]:  # noqa: ARG001
        raise ValueError("Firecrawl search failed (status 429): Too many requests")

    monkeypatch.setattr(client, "search", _mock_search)

    with pytest.raises(HTTPException, match="rate limit exceeded"):
        client.test_connection()


def test_test_connection_fails_on_empty_results(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = FirecrawlSearchClient(api_key="test-key")

    def _mock_search(query: str) -> list[Any]:  # noqa: ARG001
        return []

    monkeypatch.setattr(client, "search", _mock_search)

    with pytest.raises(HTTPException, match="returned no results"):
        client.test_connection()


def test_test_connection_propagates_unexpected_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = FirecrawlSearchClient(api_key="test-key")

    def _mock_search(query: str) -> list[Any]:  # noqa: ARG001
        raise RuntimeError("unexpected parsing bug")

    monkeypatch.setattr(client, "search", _mock_search)

    with pytest.raises(RuntimeError, match="unexpected parsing bug"):
        client.test_connection()
