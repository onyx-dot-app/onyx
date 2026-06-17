"""Unit test: the web connector must not derive doc_updated_at from Last-Modified.

A server's HTTP Last-Modified header is an unreliable change signal — CDN/SSR
origins (e.g. Vercel ISR) regenerate it on every fetch, so it advances on each
crawl even when content is identical. Letting it populate doc_updated_at makes the
indexing pipeline's timestamp gate bypass the content-hash dedup, forcing endless
re-indexing of unchanged pages. Web documents must leave doc_updated_at unset and
rely on the content hash instead.
"""

from __future__ import annotations

from unittest.mock import MagicMock
from unittest.mock import patch

import pytest

from onyx.connectors.models import Document
from onyx.connectors.web.connector import WEB_CONNECTOR_VALID_SETTINGS
from onyx.connectors.web.connector import WebConnector
from onyx.file_processing.html_utils import ParsedHTML


@pytest.fixture(autouse=True)
def _skip_web_connector_ssrf_check(monkeypatch: pytest.MonkeyPatch) -> None:
    """This test crawls example.com and doesn't exercise SSRF. The default SSRF
    level is VALIDATE_ALL, at which the web connector does a real DNS lookup per
    fetch; neutralize the gate so the test stays hermetic (no network)."""
    monkeypatch.setattr(
        "onyx.connectors.web.connector.protected_url_check", lambda _url: None
    )


BASE_URL = "http://example.com"
# A perfectly parseable Last-Modified value. If the connector ever reads it again,
# doc_updated_at would become non-None and this test would fail.
LAST_MODIFIED = "Wed, 21 Oct 2026 07:28:00 GMT"


def _make_page_mock() -> MagicMock:
    page = MagicMock()
    page.url = BASE_URL + "/"
    response = MagicMock()
    response.status = 200
    # The server DOES send Last-Modified — the connector must still ignore it.
    response.header_value.side_effect = (
        lambda h: LAST_MODIFIED if h == "Last-Modified" else None
    )
    page.goto.return_value = response
    page.content.return_value = "<html><body><p>static</p></body></html>"
    return page


def _make_playwright_mock() -> MagicMock:
    playwright = MagicMock()
    playwright.stop = MagicMock()
    return playwright


@patch("onyx.connectors.web.connector.web_html_cleanup")
@patch("onyx.connectors.web.connector.check_internet_connection")
@patch("onyx.connectors.web.connector.requests.head")
@patch("onyx.connectors.web.connector.start_playwright")
def test_doc_updated_at_is_none_even_with_last_modified_header(
    mock_start_playwright: MagicMock,
    mock_head: MagicMock,
    _mock_check: MagicMock,
    mock_cleanup: MagicMock,
) -> None:
    page = _make_page_mock()
    context = MagicMock()
    context.new_page.return_value = page
    mock_start_playwright.return_value = (_make_playwright_mock(), context)
    mock_head.return_value.headers = {"content-type": "text/html"}
    mock_cleanup.return_value = ParsedHTML(title="Static Page", cleaned_text="static")

    connector = WebConnector(
        base_url=BASE_URL + "/",
        web_connector_type=WEB_CONNECTOR_VALID_SETTINGS.SINGLE.value,
    )

    docs = [
        doc
        for batch in connector.load_from_state()
        for doc in batch
        if isinstance(doc, Document)
    ]

    assert len(docs) == 1
    assert docs[0].doc_updated_at is None
