from __future__ import annotations

from typing import Any
from typing import cast

import pytest
import requests
from fastapi import HTTPException

import onyx.tools.tool_implementations.web_search.clients.brave_client as brave_module
from onyx.tools.tool_implementations.web_search.clients.brave_client import (
    BraveClient,
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


def test_search_maps_brave_response(monkeypatch: pytest.MonkeyPatch) -> None:
    client = BraveClient(api_key="test-key", num_results=5)

    def _mock_get(*args: Any, **kwargs: Any) -> DummyResponse:  # noqa: ARG001
        return DummyResponse(
            status_code=200,
            payload={
                "web": {
                    "results": [
                        {
                            "title": "Result 1",
                            "url": "https://example.com/one",
                            "description": "Snippet 1",
                        },
                        {
                            "title": "Result without URL",
                            "description": "Should be skipped",
                        },
                    ]
                }
            },
        )

    monkeypatch.setattr(brave_module.requests, "get", _mock_get)

    results = client.search("onyx")

    assert len(results) == 1
    assert results[0].title == "Result 1"
    assert results[0].link == "https://example.com/one"
    assert results[0].snippet == "Snippet 1"


def test_search_caps_count_to_brave_max(monkeypatch: pytest.MonkeyPatch) -> None:
    client = BraveClient(api_key="test-key", num_results=100)
    captured_count: str | None = None

    def _mock_get(*args: Any, **kwargs: Any) -> DummyResponse:  # noqa: ARG001
        nonlocal captured_count
        captured_count = kwargs["params"]["count"]
        return DummyResponse(status_code=200, payload={"web": {"results": []}})

    monkeypatch.setattr(brave_module.requests, "get", _mock_get)

    client.search("onyx")

    assert captured_count == "20"


def test_search_includes_optional_params(monkeypatch: pytest.MonkeyPatch) -> None:
    client = BraveClient(
        api_key="test-key",
        num_results=5,
        country="us",
        search_lang="en",
        ui_lang="en-US",
        safesearch="moderate",
        freshness="pw",
    )
    captured_params: dict[str, str] | None = None

    def _mock_get(*args: Any, **kwargs: Any) -> DummyResponse:  # noqa: ARG001
        nonlocal captured_params
        captured_params = kwargs["params"]
        return DummyResponse(status_code=200, payload={"web": {"results": []}})

    monkeypatch.setattr(brave_module.requests, "get", _mock_get)

    client.search("onyx")

    assert captured_params is not None
    assert captured_params["country"] == "US"
    assert captured_params["search_lang"] == "en"
    assert captured_params["ui_lang"] == "en-US"
    assert captured_params["safesearch"] == "moderate"
    assert captured_params["freshness"] == "pw"


def test_search_raises_descriptive_error_on_http_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = BraveClient(api_key="test-key", num_results=5)

    def _mock_get(*args: Any, **kwargs: Any) -> DummyResponse:  # noqa: ARG001
        return DummyResponse(
            status_code=401,
            payload={"error": {"message": "Unauthorized"}},
        )

    monkeypatch.setattr(brave_module.requests, "get", _mock_get)

    with pytest.raises(ValueError, match="status 401"):
        client.search("onyx")


def test_search_does_not_retry_non_retryable_http_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = BraveClient(api_key="test-key", num_results=5)
    calls = 0

    def _mock_get(*args: Any, **kwargs: Any) -> DummyResponse:  # noqa: ARG001
        nonlocal calls
        calls += 1
        return DummyResponse(
            status_code=401,
            payload={"error": {"message": "Unauthorized"}},
        )

    monkeypatch.setattr(brave_module.requests, "get", _mock_get)

    with pytest.raises(ValueError, match="status 401"):
        client.search("onyx")
    assert calls == 1


@pytest.mark.parametrize(
    ("kwargs", "expected_error"),
    [
        ({"country": "USA"}, "country"),
        ({"safesearch": "invalid"}, "safesearch"),
        ({"freshness": "invalid"}, "freshness"),
        ({"timeout_seconds": 0}, "timeout_seconds"),
    ],
)
def test_constructor_rejects_invalid_config_values(
    kwargs: dict[str, Any],
    expected_error: str,
) -> None:
    with pytest.raises(ValueError, match=expected_error):
        BraveClient(api_key="test-key", **kwargs)


def test_test_connection_maps_invalid_key_errors() -> None:
    client = BraveClient(api_key="test-key")

    def _mock_search(query: str) -> list[Any]:  # noqa: ARG001
        raise ValueError("Brave search failed (status 401): Unauthorized")

    client.search = _mock_search  # type: ignore[method-assign]

    with pytest.raises(HTTPException, match="Invalid Brave API key"):
        client.test_connection()


def test_test_connection_maps_rate_limit_errors() -> None:
    client = BraveClient(api_key="test-key")

    def _mock_search(query: str) -> list[Any]:  # noqa: ARG001
        raise ValueError("Brave search failed (status 429): Too many requests")

    client.search = _mock_search  # type: ignore[method-assign]

    with pytest.raises(HTTPException, match="rate limit exceeded"):
        client.test_connection()


def test_test_connection_propagates_unexpected_errors() -> None:
    client = BraveClient(api_key="test-key")

    def _mock_search(query: str) -> list[Any]:  # noqa: ARG001
        raise RuntimeError("unexpected parsing bug")

    client.search = _mock_search  # type: ignore[method-assign]

    with pytest.raises(RuntimeError, match="unexpected parsing bug"):
        client.test_connection()
