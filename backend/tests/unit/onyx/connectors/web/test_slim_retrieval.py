"""Unit tests for WebConnector.retrieve_all_slim_docs (slim pruning path)."""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock
from unittest.mock import patch

from onyx.connectors.models import SlimDocument
from onyx.connectors.web.connector import WEB_CONNECTOR_VALID_SETTINGS
from onyx.connectors.web.connector import WebConnector

BASE_URL = "http://example.com"

SINGLE_PAGE_HTML = (
    "<html><body><p>Content that should not appear in slim output</p></body></html>"
)

RECURSIVE_ROOT_HTML = """
<html><body>
  <a href="/page2">Page 2</a>
  <a href="/page3">Page 3</a>
</body></html>
"""

PAGE2_HTML = "<html><body><p>page 2</p></body></html>"
PAGE3_HTML = "<html><body><p>page 3</p></body></html>"


def _make_playwright_context_mock(url_to_html: dict[str, str]) -> MagicMock:
    """Return a BrowserContext mock whose pages respond based on goto URL."""
    context = MagicMock()

    def _new_page() -> MagicMock:
        page = MagicMock()
        visited: list[str] = []

        def _goto(url: str, **kwargs: Any) -> MagicMock:  # noqa: ARG001
            visited.append(url)
            page.url = url
            response = MagicMock()
            response.status = 200
            response.header_value.return_value = None  # no cf-ray
            return response

        def _content() -> str:
            return url_to_html.get(
                visited[-1] if visited else "", "<html><body></body></html>"
            )

        page.goto.side_effect = _goto
        page.content.side_effect = _content
        return page

    context.new_page.side_effect = _new_page
    return context


def _make_playwright_mock() -> MagicMock:
    playwright = MagicMock()
    playwright.stop = MagicMock()
    return playwright


def _make_page_mock(
    html: str, cf_ray: str | None = None, status: int = 200
) -> MagicMock:
    """Return a Playwright page mock with configurable status and CF header."""
    page = MagicMock()
    page.url = BASE_URL + "/"
    response = MagicMock()
    response.status = status
    response.header_value.side_effect = lambda h: cf_ray if h == "cf-ray" else None
    page.goto.return_value = response
    page.content.return_value = html
    return page


@patch("onyx.connectors.web.connector.check_internet_connection")
@patch("onyx.connectors.web.connector.requests.head")
@patch("onyx.connectors.web.connector.start_playwright")
def test_slim_yields_slim_documents(
    mock_start_playwright: MagicMock,
    mock_head: MagicMock,
    _mock_check: MagicMock,
) -> None:
    """retrieve_all_slim_docs yields SlimDocuments with the correct URL as id."""
    context = _make_playwright_context_mock({BASE_URL + "/": SINGLE_PAGE_HTML})
    mock_start_playwright.return_value = (_make_playwright_mock(), context)
    mock_head.return_value.headers = {"content-type": "text/html"}

    connector = WebConnector(
        base_url=BASE_URL + "/",
        web_connector_type=WEB_CONNECTOR_VALID_SETTINGS.SINGLE.value,
    )

    docs = [doc for batch in connector.retrieve_all_slim_docs() for doc in batch]

    assert len(docs) == 1
    assert isinstance(docs[0], SlimDocument)
    assert docs[0].id == BASE_URL + "/"


@patch("onyx.connectors.web.connector.check_internet_connection")
@patch("onyx.connectors.web.connector.requests.head")
@patch("onyx.connectors.web.connector.start_playwright")
def test_slim_skips_content_extraction(
    mock_start_playwright: MagicMock,
    mock_head: MagicMock,
    _mock_check: MagicMock,
) -> None:
    """web_html_cleanup is never called in slim mode."""
    context = _make_playwright_context_mock({BASE_URL + "/": SINGLE_PAGE_HTML})
    mock_start_playwright.return_value = (_make_playwright_mock(), context)
    mock_head.return_value.headers = {"content-type": "text/html"}

    connector = WebConnector(
        base_url=BASE_URL + "/",
        web_connector_type=WEB_CONNECTOR_VALID_SETTINGS.SINGLE.value,
    )

    with patch("onyx.connectors.web.connector.web_html_cleanup") as mock_cleanup:
        list(connector.retrieve_all_slim_docs())
        mock_cleanup.assert_not_called()


@patch("onyx.connectors.web.connector.check_internet_connection")
@patch("onyx.connectors.web.connector.requests.head")
@patch("onyx.connectors.web.connector.start_playwright")
def test_slim_discovers_links_recursively(
    mock_start_playwright: MagicMock,
    mock_head: MagicMock,
    _mock_check: MagicMock,
) -> None:
    """In RECURSIVE mode, internal <a href> links are followed and all URLs yielded."""
    url_to_html = {
        BASE_URL + "/": RECURSIVE_ROOT_HTML,
        BASE_URL + "/page2": PAGE2_HTML,
        BASE_URL + "/page3": PAGE3_HTML,
    }
    context = _make_playwright_context_mock(url_to_html)
    mock_start_playwright.return_value = (_make_playwright_mock(), context)
    mock_head.return_value.headers = {"content-type": "text/html"}

    connector = WebConnector(
        base_url=BASE_URL + "/",
        web_connector_type=WEB_CONNECTOR_VALID_SETTINGS.RECURSIVE.value,
    )

    ids = {
        doc.id
        for batch in connector.retrieve_all_slim_docs()
        for doc in batch
        if isinstance(doc, SlimDocument)
    }

    assert ids == {
        BASE_URL + "/",
        BASE_URL + "/page2",
        BASE_URL + "/page3",
    }


@patch("onyx.connectors.web.connector.check_internet_connection")
@patch("onyx.connectors.web.connector.requests.head")
@patch("onyx.connectors.web.connector.start_playwright")
def test_normal_200_skips_5s_wait(
    mock_start_playwright: MagicMock,
    mock_head: MagicMock,
    _mock_check: MagicMock,
) -> None:
    """Normal 200 responses without bot-detection signals skip the 5s render wait."""
    page = _make_page_mock(SINGLE_PAGE_HTML, cf_ray=None, status=200)
    context = MagicMock()
    context.new_page.return_value = page
    mock_start_playwright.return_value = (_make_playwright_mock(), context)
    mock_head.return_value.headers = {"content-type": "text/html"}

    connector = WebConnector(
        base_url=BASE_URL + "/",
        web_connector_type=WEB_CONNECTOR_VALID_SETTINGS.SINGLE.value,
    )

    list(connector.retrieve_all_slim_docs())

    page.wait_for_timeout.assert_not_called()


@patch("onyx.connectors.web.connector.check_internet_connection")
@patch("onyx.connectors.web.connector.requests.head")
@patch("onyx.connectors.web.connector.start_playwright")
def test_cloudflare_applies_5s_wait(
    mock_start_playwright: MagicMock,
    mock_head: MagicMock,
    _mock_check: MagicMock,
) -> None:
    """Pages with a cf-ray header trigger the 5s wait before networkidle."""
    page = _make_page_mock(SINGLE_PAGE_HTML, cf_ray="abc123-LAX")
    context = MagicMock()
    context.new_page.return_value = page
    mock_start_playwright.return_value = (_make_playwright_mock(), context)
    mock_head.return_value.headers = {"content-type": "text/html"}

    connector = WebConnector(
        base_url=BASE_URL + "/",
        web_connector_type=WEB_CONNECTOR_VALID_SETTINGS.SINGLE.value,
    )

    list(connector.retrieve_all_slim_docs())

    page.wait_for_timeout.assert_called_once_with(5000)


@patch("onyx.connectors.web.connector.time")
@patch("onyx.connectors.web.connector.check_internet_connection")
@patch("onyx.connectors.web.connector.requests.head")
@patch("onyx.connectors.web.connector.start_playwright")
def test_403_applies_5s_wait(
    mock_start_playwright: MagicMock,
    mock_head: MagicMock,
    _mock_check: MagicMock,
    _mock_time: MagicMock,
) -> None:
    """A 403 response triggers the 5s wait (common bot-detection challenge entry point)."""
    page = _make_page_mock(SINGLE_PAGE_HTML, cf_ray=None, status=403)
    context = MagicMock()
    context.new_page.return_value = page
    mock_start_playwright.return_value = (_make_playwright_mock(), context)
    mock_head.return_value.headers = {"content-type": "text/html"}

    connector = WebConnector(
        base_url=BASE_URL + "/",
        web_connector_type=WEB_CONNECTOR_VALID_SETTINGS.SINGLE.value,
    )

    # All retries return 403 so no docs are found — that's expected here.
    # We only care that the 5s wait fired.
    try:
        list(connector.retrieve_all_slim_docs())
    except RuntimeError:
        pass

    page.wait_for_timeout.assert_called_with(5000)
