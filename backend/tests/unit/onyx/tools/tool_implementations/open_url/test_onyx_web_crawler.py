from __future__ import annotations

import pytest
from pydantic import BaseModel

import onyx.tools.tool_implementations.open_url.onyx_web_crawler as crawler_module
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
