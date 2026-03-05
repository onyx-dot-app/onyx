from __future__ import annotations

import time
from unittest.mock import MagicMock
from unittest.mock import patch

import pytest
from pydantic import BaseModel

import onyx.tools.tool_implementations.open_url.onyx_web_crawler as crawler_module
from onyx.tools.tool_implementations.open_url.onyx_web_crawler import (
    DEFAULT_CONNECT_TIMEOUT_SECONDS,
)
from onyx.tools.tool_implementations.open_url.onyx_web_crawler import (
    DEFAULT_READ_TIMEOUT_SECONDS,
)
from onyx.tools.tool_implementations.open_url.onyx_web_crawler import OnyxWebCrawler


class FakeResponse(BaseModel):
    status_code: int
    headers: dict[str, str]
    content: bytes
    text: str = ""
    apparent_encoding: str | None = None
    encoding: str | None = None


def test_fetch_url_pdf_with_content_type(monkeypatch: pytest.MonkeyPatch) -> None:
    crawler = OnyxWebCrawler()
    response = FakeResponse(
        status_code=200,
        headers={"Content-Type": "application/pdf"},
        content=b"%PDF-1.4 mock",
    )

    monkeypatch.setattr(
        crawler_module,
        "ssrf_safe_get",
        lambda *args, **kwargs: response,  # noqa: ARG005
    )
    monkeypatch.setattr(
        crawler_module,
        "extract_pdf_text",
        lambda *args, **kwargs: ("pdf text", {"Title": "Doc Title"}),  # noqa: ARG005
    )

    result = crawler._fetch_url("https://example.com/report.pdf")

    assert result.full_content == "pdf text"
    assert result.title == "Doc Title"
    assert result.scrape_successful is True


def test_fetch_url_pdf_with_signature(monkeypatch: pytest.MonkeyPatch) -> None:
    crawler = OnyxWebCrawler()
    response = FakeResponse(
        status_code=200,
        headers={"Content-Type": "application/octet-stream"},
        content=b"%PDF-1.7 mock",
    )

    monkeypatch.setattr(
        crawler_module,
        "ssrf_safe_get",
        lambda *args, **kwargs: response,  # noqa: ARG005
    )
    monkeypatch.setattr(
        crawler_module,
        "extract_pdf_text",
        lambda *args, **kwargs: ("pdf text", {}),  # noqa: ARG005
    )

    result = crawler._fetch_url("https://example.com/files/file.pdf")

    assert result.full_content == "pdf text"
    assert result.title == "file.pdf"
    assert result.scrape_successful is True


def test_fetch_url_decodes_html_bytes(monkeypatch: pytest.MonkeyPatch) -> None:
    crawler = OnyxWebCrawler()
    html_bytes = b"<html><body>caf\xe9</body></html>"
    response = FakeResponse(
        status_code=200,
        headers={"Content-Type": "text/html; charset=iso-8859-1"},
        content=html_bytes,
        text="caf\u00ef\u00bf\u00bd",
    )

    monkeypatch.setattr(
        crawler_module,
        "ssrf_safe_get",
        lambda *args, **kwargs: response,  # noqa: ARG005
    )

    result = crawler._fetch_url("https://example.com/page.html")

    assert "caf\u00e9" in result.full_content
    assert result.scrape_successful is True


def test_fetch_url_pdf_exceeds_size_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    """PDF content exceeding max_pdf_size_bytes should be rejected."""
    crawler = OnyxWebCrawler(max_pdf_size_bytes=100)
    response = FakeResponse(
        status_code=200,
        headers={"Content-Type": "application/pdf"},
        content=b"%PDF-1.4 " + b"x" * 200,  # 209 bytes, exceeds 100 limit
    )

    monkeypatch.setattr(
        crawler_module,
        "ssrf_safe_get",
        lambda *args, **kwargs: response,  # noqa: ARG005
    )

    result = crawler._fetch_url("https://example.com/large.pdf")

    assert result.full_content == ""
    assert result.scrape_successful is False
    assert result.link == "https://example.com/large.pdf"


def test_fetch_url_pdf_within_size_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    """PDF content within max_pdf_size_bytes should be processed normally."""
    crawler = OnyxWebCrawler(max_pdf_size_bytes=500)
    response = FakeResponse(
        status_code=200,
        headers={"Content-Type": "application/pdf"},
        content=b"%PDF-1.4 mock",  # Small content
    )

    monkeypatch.setattr(
        crawler_module,
        "ssrf_safe_get",
        lambda *args, **kwargs: response,  # noqa: ARG005
    )
    monkeypatch.setattr(
        crawler_module,
        "extract_pdf_text",
        lambda *args, **kwargs: ("pdf text", {"Title": "Doc Title"}),  # noqa: ARG005
    )

    result = crawler._fetch_url("https://example.com/small.pdf")

    assert result.full_content == "pdf text"
    assert result.scrape_successful is True


def test_fetch_url_html_exceeds_size_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    """HTML content exceeding max_html_size_bytes should be rejected."""
    crawler = OnyxWebCrawler(max_html_size_bytes=50)
    html_bytes = b"<html><body>" + b"x" * 100 + b"</body></html>"  # Exceeds 50 limit
    response = FakeResponse(
        status_code=200,
        headers={"Content-Type": "text/html"},
        content=html_bytes,
    )

    monkeypatch.setattr(
        crawler_module,
        "ssrf_safe_get",
        lambda *args, **kwargs: response,  # noqa: ARG005
    )

    result = crawler._fetch_url("https://example.com/large.html")

    assert result.full_content == ""
    assert result.scrape_successful is False
    assert result.link == "https://example.com/large.html"


def test_fetch_url_html_within_size_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    """HTML content within max_html_size_bytes should be processed normally."""
    crawler = OnyxWebCrawler(max_html_size_bytes=500)
    html_bytes = b"<html><body>hello world</body></html>"
    response = FakeResponse(
        status_code=200,
        headers={"Content-Type": "text/html"},
        content=html_bytes,
    )

    monkeypatch.setattr(
        crawler_module,
        "ssrf_safe_get",
        lambda *args, **kwargs: response,  # noqa: ARG005
    )

    result = crawler._fetch_url("https://example.com/small.html")

    assert "hello world" in result.full_content
    assert result.scrape_successful is True


# ---------------------------------------------------------------------------
# Helpers for parallel / failure-isolation / timeout tests
# ---------------------------------------------------------------------------


def _make_mock_response(
    *,
    status_code: int = 200,
    content: bytes = b"<html><body>Hello</body></html>",
    content_type: str = "text/html",
    delay: float = 0.0,
) -> MagicMock:
    """Create a mock response that behaves like a requests.Response."""
    resp = MagicMock()
    resp.status_code = status_code
    resp.headers = {"Content-Type": content_type}

    if delay:
        original_content = content

        @property  # type: ignore[misc]
        def _delayed_content(_self: object) -> bytes:
            time.sleep(delay)
            return original_content

        type(resp).content = _delayed_content
    else:
        resp.content = content

    resp.apparent_encoding = None
    resp.encoding = None

    return resp


class TestParallelExecution:
    """Verify that contents() fetches URLs in parallel."""

    @patch("onyx.tools.tool_implementations.open_url.onyx_web_crawler.ssrf_safe_get")
    def test_multiple_urls_fetched_concurrently(self, mock_get: MagicMock) -> None:
        """With a per-URL delay, parallel execution should be much faster than sequential."""
        per_url_delay = 0.3
        num_urls = 5
        urls = [f"http://example.com/page{i}" for i in range(num_urls)]

        mock_get.return_value = _make_mock_response(delay=per_url_delay)

        crawler = OnyxWebCrawler()
        start = time.monotonic()
        results = crawler.contents(urls)
        elapsed = time.monotonic() - start

        # Sequential would take ~1.5s; parallel should be well under that
        assert elapsed < per_url_delay * num_urls * 0.7
        assert len(results) == num_urls
        assert all(r.scrape_successful for r in results)

    @patch("onyx.tools.tool_implementations.open_url.onyx_web_crawler.ssrf_safe_get")
    def test_empty_urls_returns_empty(self, mock_get: MagicMock) -> None:
        crawler = OnyxWebCrawler()
        results = crawler.contents([])
        assert results == []
        mock_get.assert_not_called()

    @patch("onyx.tools.tool_implementations.open_url.onyx_web_crawler.ssrf_safe_get")
    def test_single_url(self, mock_get: MagicMock) -> None:
        mock_get.return_value = _make_mock_response()
        crawler = OnyxWebCrawler()
        results = crawler.contents(["http://example.com"])
        assert len(results) == 1
        assert results[0].scrape_successful


class TestFailureIsolation:
    """Verify that one URL failure doesn't affect others in the batch."""

    @patch("onyx.tools.tool_implementations.open_url.onyx_web_crawler.ssrf_safe_get")
    def test_one_failure_doesnt_kill_batch(self, mock_get: MagicMock) -> None:
        good_resp = _make_mock_response()
        bad_resp = _make_mock_response(status_code=500)

        # First and third URLs succeed, second fails
        mock_get.side_effect = [good_resp, bad_resp, good_resp]

        crawler = OnyxWebCrawler()
        results = crawler.contents(["http://a.com", "http://b.com", "http://c.com"])

        assert len(results) == 3
        assert results[0].scrape_successful
        assert not results[1].scrape_successful
        assert results[2].scrape_successful

    @patch("onyx.tools.tool_implementations.open_url.onyx_web_crawler.ssrf_safe_get")
    def test_exception_doesnt_kill_batch(self, mock_get: MagicMock) -> None:
        good_resp = _make_mock_response()

        # Second URL raises an exception
        mock_get.side_effect = [
            good_resp,
            RuntimeError("connection reset"),
            _make_mock_response(),
        ]

        crawler = OnyxWebCrawler()
        results = crawler.contents(["http://a.com", "http://b.com", "http://c.com"])

        assert len(results) == 3
        assert results[0].scrape_successful
        assert not results[1].scrape_successful
        assert results[2].scrape_successful

    @patch("onyx.tools.tool_implementations.open_url.onyx_web_crawler.ssrf_safe_get")
    def test_ssrf_exception_doesnt_kill_batch(self, mock_get: MagicMock) -> None:
        from onyx.utils.url import SSRFException

        good_resp = _make_mock_response()
        mock_get.side_effect = [
            good_resp,
            SSRFException("blocked"),
            _make_mock_response(),
        ]

        crawler = OnyxWebCrawler()
        results = crawler.contents(
            ["http://a.com", "http://internal.local", "http://c.com"]
        )

        assert len(results) == 3
        assert results[0].scrape_successful
        assert not results[1].scrape_successful
        assert results[2].scrape_successful


class TestTupleTimeout:
    """Verify that separate connect and read timeouts are passed correctly."""

    @patch("onyx.tools.tool_implementations.open_url.onyx_web_crawler.ssrf_safe_get")
    def test_default_tuple_timeout(self, mock_get: MagicMock) -> None:
        mock_get.return_value = _make_mock_response()

        crawler = OnyxWebCrawler()
        crawler.contents(["http://example.com"])

        call_kwargs = mock_get.call_args
        assert call_kwargs.kwargs["timeout"] == (
            DEFAULT_CONNECT_TIMEOUT_SECONDS,
            DEFAULT_READ_TIMEOUT_SECONDS,
        )

    @patch("onyx.tools.tool_implementations.open_url.onyx_web_crawler.ssrf_safe_get")
    def test_custom_tuple_timeout(self, mock_get: MagicMock) -> None:
        mock_get.return_value = _make_mock_response()

        crawler = OnyxWebCrawler(timeout_seconds=30, connect_timeout_seconds=3)
        crawler.contents(["http://example.com"])

        call_kwargs = mock_get.call_args
        assert call_kwargs.kwargs["timeout"] == (3, 30)
