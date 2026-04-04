from __future__ import annotations

from typing import Any
from typing import cast

import pytest
import requests

import onyx.tools.tool_implementations.web_search.clients.baidu_client as baidu_module
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
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

    with pytest.raises(OnyxError) as exc_info:
        client.test_connection()
    assert exc_info.value.error_code == OnyxErrorCode.CREDENTIAL_INVALID
    assert "Invalid Baidu API key" in exc_info.value.detail


def test_test_connection_maps_rate_limit_errors() -> None:
    client = BaiduClient(api_key="test-key")

    def _mock_search(query: str) -> list[Any]:  # noqa: ARG001
        raise ValueError("Baidu search failed (status 429): Too many requests")

    client.search = _mock_search  # type: ignore[method-assign]

    with pytest.raises(OnyxError) as exc_info:
        client.test_connection()
    assert exc_info.value.error_code == OnyxErrorCode.RATE_LIMITED
    assert "rate limit exceeded" in exc_info.value.detail


def test_test_connection_rejects_empty_search_results() -> None:
    client = BaiduClient(api_key="test-key")

    def _mock_search(query: str) -> list[Any]:  # noqa: ARG001
        return []

    client.search = _mock_search  # type: ignore[method-assign]

    with pytest.raises(OnyxError) as exc_info:
        client.test_connection()
    assert exc_info.value.error_code == OnyxErrorCode.CONNECTOR_VALIDATION_FAILED
    assert "search returned no results" in exc_info.value.detail


def test_test_connection_propagates_unexpected_errors() -> None:
    client = BaiduClient(api_key="test-key")

    def _mock_search(query: str) -> list[Any]:  # noqa: ARG001
        raise RuntimeError("unexpected parsing bug")

    client.search = _mock_search  # type: ignore[method-assign]

    with pytest.raises(RuntimeError, match="unexpected parsing bug"):
        client.test_connection()


def test_extract_error_detail_logs_invalid_json(
    caplog: pytest.LogCaptureFixture,
) -> None:
    response = cast(
        requests.Response,
        DummyResponse(status_code=500, payload=None, text="plain error detail"),
    )

    with caplog.at_level("DEBUG", logger=baidu_module.logger.name):
        assert baidu_module._extract_error_detail(response) == "plain error detail"

    assert "Failed to parse Baidu error response as JSON" in caplog.text


def test_parse_published_date_logs_expected_parse_failures(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    def _mock_time_str_to_utc(value: str) -> Any:  # noqa: ARG001
        raise ValueError("invalid date")

    monkeypatch.setattr(baidu_module, "time_str_to_utc", _mock_time_str_to_utc)

    with caplog.at_level("DEBUG", logger=baidu_module.logger.name):
        assert baidu_module._parse_published_date("not-a-date") is None

    assert "Could not parse Baidu published_date" in caplog.text


def test_parse_published_date_propagates_unexpected_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _mock_time_str_to_utc(value: str) -> Any:  # noqa: ARG001
        raise TypeError("unexpected parser bug")

    monkeypatch.setattr(baidu_module, "time_str_to_utc", _mock_time_str_to_utc)

    with pytest.raises(TypeError, match="unexpected parser bug"):
        baidu_module._parse_published_date("2025-05-23 00:00:00")
