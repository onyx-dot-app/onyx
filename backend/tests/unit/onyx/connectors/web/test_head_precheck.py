"""The HEAD content-type precheck must never abort a scrape."""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, patch

import pytest
import requests

from onyx.connectors.models import Document
from onyx.connectors.web.connector import WEB_CONNECTOR_VALID_SETTINGS, WebConnector

BASE_URL = "http://example.com"
PAGE_HTML = "<html><body><p>Indexable content</p></body></html>"


@pytest.fixture(autouse=True)
def _skip_web_connector_ssrf_check(monkeypatch: pytest.MonkeyPatch) -> None:
    """The default SSRF level does a real DNS lookup per fetch; neutralize the
    gate so these tests stay hermetic."""
    monkeypatch.setattr(
        "onyx.connectors.web.connector.protected_url_check", lambda _url: None
    )


def _make_playwright_context_mock() -> MagicMock:
    context = MagicMock()

    def _new_page() -> MagicMock:
        page = MagicMock()

        def _goto(url: str, **kwargs: Any) -> MagicMock:  # noqa: ARG001
            page.url = url
            response = MagicMock()
            response.status = 200
            response.header_value.return_value = None  # no cf-ray
            return response

        page.goto.side_effect = _goto
        page.content.return_value = PAGE_HTML
        return page

    context.new_page.side_effect = _new_page
    return context


@pytest.mark.parametrize(
    "head_error",
    [
        # `requests` resolves a redirect by re-decoding the latin-1 header as
        # UTF-8, so a `Location` holding non-UTF-8 bytes raises this. Chromium
        # percent-encodes the same bytes and follows the redirect fine.
        UnicodeDecodeError("utf-8", b"\xe9", 0, 1, "invalid continuation byte"),
        requests.ConnectionError("connection reset"),
    ],
    ids=["unicode_decode_error", "connection_error"],
)
@patch("onyx.connectors.web.connector.check_internet_connection")
@patch("onyx.connectors.web.connector.requests.head")
@patch("onyx.connectors.web.connector.start_playwright")
def test_failed_head_precheck_still_indexes_the_page(
    mock_start_playwright: MagicMock,
    mock_head: MagicMock,
    _mock_check: MagicMock,
    head_error: Exception,
) -> None:
    """A failing HEAD only disables content-type based PDF detection; the browser
    fetch below still runs and the page is indexed."""
    mock_start_playwright.return_value = (MagicMock(), _make_playwright_context_mock())
    mock_head.side_effect = head_error

    connector = WebConnector(
        base_url=BASE_URL + "/",
        web_connector_type=WEB_CONNECTOR_VALID_SETTINGS.SINGLE.value,
    )

    docs = [doc for batch in connector.load_from_state() for doc in batch]

    assert len(docs) == 1
    doc = docs[0]
    assert isinstance(doc, Document)
    assert doc.id == BASE_URL + "/"
    # Proves the browser fetch below the precheck actually ran.
    assert "Indexable content" in doc.get_text_content()
