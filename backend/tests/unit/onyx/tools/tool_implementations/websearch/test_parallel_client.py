from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, cast

import pytest
import requests

import onyx.tools.tool_implementations.web_search.clients.parallel_client as parallel_module
from onyx.error_handling.exceptions import OnyxError
from onyx.tools.tool_implementations.web_search.clients.parallel_client import (
    PARALLEL_SEARCH_URL,
    ParallelSearchClient,
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
    monkeypatch.setattr("time.sleep", lambda _seconds: None)


def _empty_ok(*args: Any, **kwargs: Any) -> DummyResponse:  # noqa: ARG001
    return DummyResponse(
        status_code=200,
        payload={"search_id": "search_1", "results": [], "session_id": "s"},
    )


def test_search_maps_parallel_response(monkeypatch: pytest.MonkeyPatch) -> None:
    client = ParallelSearchClient(api_key="test-key", num_results=5)

    def _mock_post(*args: Any, **kwargs: Any) -> DummyResponse:  # noqa: ARG001
        return DummyResponse(
            status_code=200,
            payload={
                "search_id": "search_1",
                "session_id": "session_1",
                "results": [
                    {
                        "url": "https://example.com/one",
                        "title": " Result 1 ",
                        "publish_date": "2024-01-15",
                        "excerpts": [" Excerpt A ", "", "Excerpt B"],
                    },
                    {
                        "url": "https://example.com/two",
                        "title": None,
                        "publish_date": None,
                        "excerpts": None,
                    },
                    {"title": "No URL", "excerpts": ["skipped"]},
                    "not-a-dict",
                ],
            },
        )

    monkeypatch.setattr(parallel_module.requests, "post", _mock_post)

    results = client.search("onyx")

    assert len(results) == 2
    assert results[0].title == "Result 1"
    assert results[0].link == "https://example.com/one"
    assert results[0].snippet == "Excerpt A\n\nExcerpt B"
    assert results[0].author is None
    assert results[0].published_date == datetime(2024, 1, 15, tzinfo=timezone.utc)
    assert results[1].title == ""
    assert results[1].snippet == ""
    assert results[1].published_date is None


def test_search_sends_expected_request(monkeypatch: pytest.MonkeyPatch) -> None:
    client = ParallelSearchClient(
        api_key="test-key",
        num_results=500,
        timeout_seconds=12,
        mode="ADVANCED",
        location="GB",
    )
    captured: dict[str, Any] = {}

    def _mock_post(url: str, **kwargs: Any) -> DummyResponse:
        captured["url"] = url
        captured.update(kwargs)
        return _empty_ok()

    monkeypatch.setattr(parallel_module.requests, "post", _mock_post)

    client.search("onyx enterprise search")

    assert captured["url"] == PARALLEL_SEARCH_URL
    assert captured["headers"]["x-api-key"] == "test-key"
    assert captured["timeout"] == 12
    assert captured["allow_redirects"] is False
    assert captured["json"] == {
        "search_queries": ["onyx enterprise search"],
        "mode": "advanced",
        "advanced_settings": {"max_results": 20, "location": "gb"},
    }


def test_search_defaults_to_fast_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    client = ParallelSearchClient(api_key="test-key", num_results=5)
    captured: dict[str, Any] = {}

    def _mock_post(*args: Any, **kwargs: Any) -> DummyResponse:  # noqa: ARG001
        captured.update(kwargs["json"])
        return _empty_ok()

    monkeypatch.setattr(parallel_module.requests, "post", _mock_post)

    client.search("onyx")

    assert captured == {
        "search_queries": ["onyx"],
        "mode": "fast",
        "advanced_settings": {"max_results": 5},
    }


def test_search_maps_site_operator_to_include_domains(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = ParallelSearchClient(api_key="test-key", num_results=5)
    captured: dict[str, Any] = {}

    def _mock_post(*args: Any, **kwargs: Any) -> DummyResponse:  # noqa: ARG001
        captured.update(kwargs["json"])
        return _empty_ok()

    monkeypatch.setattr(parallel_module.requests, "post", _mock_post)

    client.search("release notes site:www.onyx.app")

    assert captured["search_queries"] == ["release notes"]
    assert captured["advanced_settings"]["source_policy"] == {
        "include_domains": ["onyx.app"]
    }


def test_supports_site_filter() -> None:
    assert ParallelSearchClient(api_key="test-key").supports_site_filter is False


def test_search_raises_descriptive_error_on_http_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = ParallelSearchClient(api_key="test-key")
    calls = 0

    def _mock_post(*args: Any, **kwargs: Any) -> DummyResponse:  # noqa: ARG001
        nonlocal calls
        calls += 1
        return DummyResponse(
            status_code=422,
            payload={
                "type": "error",
                "error": {"ref_id": "r", "message": "Request validation error"},
            },
        )

    monkeypatch.setattr(parallel_module.requests, "post", _mock_post)

    with pytest.raises(ValueError, match="status 422.*Request validation error"):
        client.search("onyx")
    assert calls == 1


def test_search_retries_rate_limit_then_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _no_sleep(monkeypatch)
    client = ParallelSearchClient(api_key="test-key")
    calls = 0

    def _mock_post(*args: Any, **kwargs: Any) -> DummyResponse:  # noqa: ARG001
        nonlocal calls
        calls += 1
        return DummyResponse(status_code=429, text="Too Many Requests")

    monkeypatch.setattr(parallel_module.requests, "post", _mock_post)

    with pytest.raises(ValueError, match="status 429.*Too Many Requests"):
        client.search("onyx")
    assert calls == 3


def test_search_retries_transient_request_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _no_sleep(monkeypatch)
    client = ParallelSearchClient(api_key="test-key")
    calls = 0

    def _mock_post(*args: Any, **kwargs: Any) -> DummyResponse:  # noqa: ARG001
        nonlocal calls
        calls += 1
        if calls < 3:
            raise requests.Timeout("read timed out")
        return DummyResponse(
            status_code=200,
            payload={"results": [{"url": "https://example.com", "title": "ok"}]},
        )

    monkeypatch.setattr(parallel_module.requests, "post", _mock_post)

    results = client.search("onyx")

    assert calls == 3
    assert len(results) == 1


def test_search_rejects_redirect(monkeypatch: pytest.MonkeyPatch) -> None:
    client = ParallelSearchClient(api_key="test-key")

    def _mock_post(*args: Any, **kwargs: Any) -> DummyResponse:  # noqa: ARG001
        return DummyResponse(status_code=302)

    monkeypatch.setattr(parallel_module.requests, "post", _mock_post)

    with pytest.raises(ValueError, match="redirect"):
        client.search("onyx")


def test_search_rejects_malformed_results(monkeypatch: pytest.MonkeyPatch) -> None:
    client = ParallelSearchClient(api_key="test-key")

    def _mock_post(*args: Any, **kwargs: Any) -> DummyResponse:  # noqa: ARG001
        return DummyResponse(status_code=200, payload={"results": {"url": "x"}})

    monkeypatch.setattr(parallel_module.requests, "post", _mock_post)

    with pytest.raises(ValueError, match="unexpected response shape"):
        client.search("onyx")


@pytest.mark.parametrize(
    ("kwargs", "expected_error"),
    [
        ({"mode": "ultra"}, "mode"),
        ({"location": "usa"}, "location"),
        ({"timeout_seconds": 0}, "timeout_seconds"),
    ],
)
def test_constructor_rejects_invalid_config_values(
    kwargs: dict[str, Any],
    expected_error: str,
) -> None:
    with pytest.raises(ValueError, match=expected_error):
        ParallelSearchClient(api_key="test-key", **kwargs)


@pytest.mark.parametrize(
    ("error", "expected"),
    [
        ("Parallel search failed (status 401): Unauthorized", "Invalid Parallel"),
        ("Parallel search failed (status 402): Payment", "insufficient credits"),
        ("Parallel search failed (status 429): Slow down", "rate limit exceeded"),
        ("Parallel search failed (status 500): Boom", "validation failed"),
    ],
)
def test_test_connection_maps_errors(
    monkeypatch: pytest.MonkeyPatch, error: str, expected: str
) -> None:
    client = ParallelSearchClient(api_key="test-key")

    def _mock_search(query: str) -> list[Any]:  # noqa: ARG001
        raise ValueError(error)

    monkeypatch.setattr(client, "search", _mock_search)

    with pytest.raises(OnyxError, match=expected):
        client.test_connection()


def test_test_connection_fails_on_empty_results(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = ParallelSearchClient(api_key="test-key")
    monkeypatch.setattr(client, "search", lambda _query: [])

    with pytest.raises(OnyxError, match="returned no results"):
        client.test_connection()
