from __future__ import annotations

from dataclasses import dataclass

import onyx.tools.tool_implementations.open_url.onyx_web_crawler as crawler_module
from onyx.tools.tool_implementations.open_url.onyx_web_crawler import OnyxWebCrawler


@dataclass
class FakeResponse:
    status_code: int
    headers: dict[str, str]
    content: bytes
    text: str = ""


def test_fetch_url_pdf_with_content_type(monkeypatch: object) -> None:
    crawler = OnyxWebCrawler()
    response = FakeResponse(
        status_code=200,
        headers={"Content-Type": "application/pdf"},
        content=b"%PDF-1.4 mock",
    )

    monkeypatch.setattr(
        crawler_module,
        "ssrf_safe_get",
        lambda *args, **kwargs: response,
    )
    monkeypatch.setattr(
        crawler_module,
        "read_pdf_file",
        lambda *args, **kwargs: ("pdf text", {"Title": "Doc Title"}, []),
    )

    result = crawler._fetch_url("https://example.com/report.pdf")

    assert result.full_content == "pdf text"
    assert result.title == "Doc Title"
    assert result.scrape_successful is True


def test_fetch_url_pdf_with_signature(monkeypatch: object) -> None:
    crawler = OnyxWebCrawler()
    response = FakeResponse(
        status_code=200,
        headers={"Content-Type": "application/octet-stream"},
        content=b"%PDF-1.7 mock",
    )

    monkeypatch.setattr(
        crawler_module,
        "ssrf_safe_get",
        lambda *args, **kwargs: response,
    )
    monkeypatch.setattr(
        crawler_module,
        "read_pdf_file",
        lambda *args, **kwargs: ("pdf text", {}, []),
    )

    result = crawler._fetch_url("https://example.com/files/file.pdf")

    assert result.full_content == "pdf text"
    assert result.title == "file.pdf"
    assert result.scrape_successful is True
