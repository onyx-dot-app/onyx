"""Unit tests for WebConnector.poll_source (incremental sitemap indexing)."""

from __future__ import annotations

from datetime import datetime
from datetime import timezone
from typing import Any
from unittest.mock import MagicMock
from unittest.mock import patch

from onyx.connectors.web.connector import ScrapeResult
from onyx.connectors.web.connector import WEB_CONNECTOR_VALID_SETTINGS
from onyx.connectors.web.connector import WebConnector

SITEMAP_URL = "http://example.com/sitemap.xml"


def _ts(year: int, month: int, day: int) -> float:
    return datetime(year, month, day, tzinfo=timezone.utc).timestamp()


def _make_playwright_mocks() -> tuple[MagicMock, MagicMock]:
    """Return (playwright, context) mocks sufficient to let _scrape_urls run."""
    context = MagicMock()
    page = MagicMock()
    page.url = ""
    response = MagicMock()
    response.status = 200
    response.header_value.return_value = None
    page.goto.return_value = response
    page.content.return_value = "<html><body>ok</body></html>"
    context.new_page.return_value = page
    playwright = MagicMock()
    return playwright, context


@patch("onyx.connectors.web.connector.extract_urls_from_sitemap")
def test_poll_source_filters_by_sitemap_lastmod(
    mock_extract: MagicMock,
) -> None:
    """Only URLs with lastmod >= start (or lastmod is None) survive the filter."""
    mock_extract.return_value = {
        "http://example.com/old": datetime(2024, 1, 1, tzinfo=timezone.utc),
        "http://example.com/new": datetime(2026, 6, 1, tzinfo=timezone.utc),
        "http://example.com/no-lastmod": None,
    }

    connector = WebConnector(
        base_url=SITEMAP_URL,
        web_connector_type=WEB_CONNECTOR_VALID_SETTINGS.SITEMAP.value,
    )

    visited: list[str] = []

    def _fake_scrape_urls(
        _self: WebConnector,  # noqa: ARG001
        session_ctx: Any,
        slim: bool,  # noqa: ARG001
        poll_start: float | None,  # noqa: ARG001
    ) -> Any:
        visited.extend(session_ctx.to_visit)
        return iter([])

    with (
        patch.object(WebConnector, "_scrape_urls", _fake_scrape_urls),
        patch("onyx.connectors.web.connector.check_internet_connection"),
    ):
        list(connector.poll_source(start=_ts(2025, 1, 1), end=_ts(2027, 1, 1)))

    assert "http://example.com/old" not in visited
    assert "http://example.com/new" in visited
    assert "http://example.com/no-lastmod" in visited


@patch("onyx.connectors.web.connector.extract_urls_from_sitemap")
def test_poll_source_empty_result_yields_nothing_no_raise(
    mock_extract: MagicMock,
) -> None:
    """All URLs filtered out → generator exhausts cleanly, no exception."""
    mock_extract.return_value = {
        "http://example.com/old": datetime(2024, 1, 1, tzinfo=timezone.utc),
    }

    connector = WebConnector(
        base_url=SITEMAP_URL,
        web_connector_type=WEB_CONNECTOR_VALID_SETTINGS.SITEMAP.value,
    )

    # Don't even need to patch _scrape_urls — it should never be called.
    batches = list(connector.poll_source(start=_ts(2025, 1, 1), end=_ts(2027, 1, 1)))

    assert batches == []


@patch("onyx.connectors.web.connector.extract_urls_from_sitemap")
def test_poll_source_non_sitemap_delegates_to_load_from_state(
    mock_extract: MagicMock,  # noqa: ARG001
) -> None:
    """RECURSIVE / SINGLE / UPLOAD modes have no <lastmod>; poll reuses full scan."""
    connector = WebConnector(
        base_url="http://example.com/",
        web_connector_type=WEB_CONNECTOR_VALID_SETTINGS.RECURSIVE.value,
    )

    sentinel = [[MagicMock(id="http://example.com/")]]
    with patch.object(
        WebConnector, "load_from_state", return_value=iter(sentinel)
    ) as mock_load:
        result = list(connector.poll_source(start=_ts(2025, 1, 1), end=_ts(2027, 1, 1)))

    mock_load.assert_called_once()
    assert result == sentinel


@patch("onyx.connectors.web.connector.extract_urls_from_sitemap")
def test_conditional_head_304_skips_scrape(mock_extract: MagicMock) -> None:
    """When poll_start is set and HEAD returns 304, Playwright is not invoked."""
    mock_extract.return_value = {"http://example.com/unchanged": None}

    connector = WebConnector(
        base_url=SITEMAP_URL,
        web_connector_type=WEB_CONNECTOR_VALID_SETTINGS.SITEMAP.value,
    )

    playwright, context = _make_playwright_mocks()

    session_ctx = MagicMock()
    session_ctx.playwright = playwright
    session_ctx.playwright_context = context

    head_resp = MagicMock()
    head_resp.status_code = 304
    head_resp.headers = {}

    with (
        patch(
            "onyx.connectors.web.connector.requests.head", return_value=head_resp
        ) as mock_head,
        patch("onyx.connectors.web.connector._handle_cookies"),
    ):
        result = connector._do_scrape(
            index=1,
            initial_url="http://example.com/unchanged",
            session_ctx=session_ctx,
            slim=False,
            poll_start=_ts(2025, 1, 1),
        )

    assert isinstance(result, ScrapeResult)
    assert result.doc is None
    # Playwright must not have been touched.
    context.new_page.assert_not_called()
    # The HEAD should carry the conditional header.
    _, kwargs = mock_head.call_args
    assert "If-Modified-Since" in kwargs["headers"]


@patch("onyx.connectors.web.connector.extract_urls_from_sitemap")
def test_head_without_poll_start_has_no_if_modified_since(
    mock_extract: MagicMock,
) -> None:
    """full-rescan path (load_from_state) must not send If-Modified-Since."""
    mock_extract.return_value = {"http://example.com/x": None}

    connector = WebConnector(
        base_url=SITEMAP_URL,
        web_connector_type=WEB_CONNECTOR_VALID_SETTINGS.SITEMAP.value,
    )

    playwright, context = _make_playwright_mocks()

    session_ctx = MagicMock()
    session_ctx.playwright = playwright
    session_ctx.playwright_context = context

    head_resp = MagicMock()
    head_resp.status_code = 200
    head_resp.headers = {"content-type": "text/html"}

    with (
        patch(
            "onyx.connectors.web.connector.requests.head", return_value=head_resp
        ) as mock_head,
        patch("onyx.connectors.web.connector._handle_cookies"),
        patch("onyx.connectors.web.connector.is_pdf_resource", return_value=False),
        # Short-circuit before Playwright navigation by raising — we only care
        # about the HEAD request's headers here.
        patch.object(context, "new_page", side_effect=RuntimeError("stop here")),
    ):
        try:
            connector._do_scrape(
                index=1,
                initial_url="http://example.com/x",
                session_ctx=session_ctx,
                slim=False,
                poll_start=None,
            )
        except RuntimeError:
            pass

    _, kwargs = mock_head.call_args
    assert "If-Modified-Since" not in kwargs["headers"]
