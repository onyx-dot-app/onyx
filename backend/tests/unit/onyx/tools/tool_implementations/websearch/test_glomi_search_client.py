from __future__ import annotations

from typing import Any
from typing import cast

import pytest
import requests

import onyx.tools.tool_implementations.web_search.clients.glomi_search_client as glomi_module
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.tools.tool_implementations.web_search.clients.glomi_search_client import (
    GlomiSearchClient,
)
from onyx.tools.tool_implementations.web_search.models import WebSearchMode


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
            http_error = requests.HTTPError(f"{self.status_code} Error")
            http_error.response = cast(requests.Response, self)
            raise http_error

    def json(self) -> dict[str, Any]:
        if self._payload is None:
            raise ValueError("No JSON payload")
        return self._payload


def test_search_batch_sends_gateway_payload(monkeypatch: pytest.MonkeyPatch) -> None:
    client = GlomiSearchClient(
        api_key="gateway-key",
        base_url="https://search.example.test/",
        channel="tavily",
        num_results=20,
        timeout_seconds=12,
    )
    captured: dict[str, Any] = {}

    def _mock_post(*args: Any, **kwargs: Any) -> DummyResponse:
        captured["args"] = args
        captured["kwargs"] = kwargs
        return DummyResponse(
            status_code=200,
            payload={
                "results": [
                    {
                        "title": "Result 1",
                        "url": "https://example.com/one",
                        "snippet": "Snippet 1",
                        "published_date": "2026-06-15T00:00:00Z",
                        "author": "Author",
                    },
                    {
                        "title": "Result 2",
                        "link": "https://example.com/two",
                        "snippet": "Snippet 2",
                    },
                ]
            },
        )

    monkeypatch.setattr(glomi_module.requests, "post", _mock_post)

    results = client.search_batch(
        ["q1", "q2"], mode=WebSearchMode.DEEP, max_results=12
    )

    assert captured["args"] == ("https://search.example.test/search",)
    assert captured["kwargs"]["headers"]["Authorization"] == "Bearer gateway-key"
    assert captured["kwargs"]["json"] == {
        "queries": ["q1", "q2"],
        "mode": "deep",
        "channel": "tavily",
        "max_results": 12,
        "locale": "zh-CN",
    }
    assert captured["kwargs"]["timeout"] == 12
    assert [result.link for result in results] == [
        "https://example.com/one",
        "https://example.com/two",
    ]
    assert results[0].author == "Author"


def test_search_batch_omits_channel_when_unset(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = GlomiSearchClient(
        api_key="gateway-key",
        base_url="https://search.example.test",
        channel=None,
        num_results=20,
    )
    captured_payload: dict[str, Any] | None = None

    def _mock_post(*args: Any, **kwargs: Any) -> DummyResponse:  # noqa: ARG001
        nonlocal captured_payload
        captured_payload = kwargs["json"]
        return DummyResponse(status_code=200, payload={"results": []})

    monkeypatch.setattr(glomi_module.requests, "post", _mock_post)

    client.search_batch(["q1"], mode=WebSearchMode.LITE)

    assert captured_payload is not None
    assert "channel" not in captured_payload
    assert captured_payload["max_results"] == 20


def test_search_batch_maps_auth_error(monkeypatch: pytest.MonkeyPatch) -> None:
    client = GlomiSearchClient(
        api_key="bad-key",
        base_url="https://search.example.test",
    )

    def _mock_post(*args: Any, **kwargs: Any) -> DummyResponse:  # noqa: ARG001
        return DummyResponse(status_code=401, payload={"detail": "unauthorized"})

    monkeypatch.setattr(glomi_module.requests, "post", _mock_post)

    with pytest.raises(ValueError, match="Invalid Glomi Search API key"):
        client.search_batch(["q1"], mode=WebSearchMode.LITE)


def test_search_batch_maps_rate_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    client = GlomiSearchClient(
        api_key="gateway-key",
        base_url="https://search.example.test",
    )

    def _mock_post(*args: Any, **kwargs: Any) -> DummyResponse:  # noqa: ARG001
        return DummyResponse(status_code=429, payload={"detail": "too many"})

    monkeypatch.setattr(glomi_module.requests, "post", _mock_post)

    with pytest.raises(ValueError, match="Glomi Search rate limit exceeded"):
        client.search_batch(["q1"], mode=WebSearchMode.LITE)


def test_search_batch_rejects_non_json_response(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = GlomiSearchClient(
        api_key="gateway-key",
        base_url="https://search.example.test",
    )

    def _mock_post(*args: Any, **kwargs: Any) -> DummyResponse:  # noqa: ARG001
        return DummyResponse(status_code=200, payload=None, text="<html>bad</html>")

    monkeypatch.setattr(glomi_module.requests, "post", _mock_post)

    with pytest.raises(ValueError, match="non-JSON response"):
        client.search_batch(["q1"], mode=WebSearchMode.LITE)


def test_test_connection_maps_invalid_key_errors() -> None:
    client = GlomiSearchClient(
        api_key="gateway-key",
        base_url="https://search.example.test",
    )

    def _mock_search(query: str) -> list[Any]:  # noqa: ARG001
        raise ValueError("Invalid Glomi Search API key")

    client.search = _mock_search  # ty: ignore[invalid-assignment]

    with pytest.raises(OnyxError) as exc_info:
        client.test_connection()

    assert exc_info.value.error_code == OnyxErrorCode.INVALID_INPUT
    assert exc_info.value.detail == "Invalid Glomi Search API key"
