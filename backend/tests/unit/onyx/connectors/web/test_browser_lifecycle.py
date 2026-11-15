"""Browser teardown/relaunch behavior of the web connector.

Every Playwright teardown orphans Chromium helpers that zombify on the
docfetching subreaper; relaunches must not be wasted on deterministic
failures, and each teardown must drain what it orphaned."""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from playwright.sync_api import Error as PlaywrightError

from onyx.connectors.web.config import WEB_CONNECTOR_VALID_SETTINGS
from onyx.connectors.web.connector import ScrapeSessionContext, WebConnector

BASE_URL = "http://example.com"


@pytest.fixture(autouse=True)
def _skip_web_connector_ssrf_check(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "onyx.connectors.web.connector.protected_url_check", lambda _url: None
    )


def _download_context_mock() -> MagicMock:
    """A BrowserContext whose pages always turn navigation into a download."""
    context = MagicMock()

    def _new_page() -> MagicMock:
        page = MagicMock()

        def _goto(url: str, **kwargs: Any) -> MagicMock:  # noqa: ARG001
            raise PlaywrightError("Page.goto: Download is starting")

        page.goto.side_effect = _goto
        return page

    context.new_page.side_effect = _new_page
    return context


@patch("onyx.connectors.web.connector.time")
@patch("onyx.connectors.web.connector.check_internet_connection")
@patch("onyx.connectors.web.connector.requests.head")
@patch("onyx.connectors.web.connector.start_playwright")
def test_download_is_not_retried_and_does_not_relaunch_browser(
    mock_start_playwright: MagicMock,
    mock_head: MagicMock,
    _mock_check: MagicMock,
    _mock_time: MagicMock,
) -> None:
    context = _download_context_mock()
    mock_start_playwright.return_value = (MagicMock(), context)
    mock_head.return_value.headers = {"content-type": "application/zip"}

    connector = WebConnector(
        base_url=BASE_URL + "/archive.zip",
        web_connector_type=WEB_CONNECTOR_VALID_SETTINGS.SINGLE.value,
    )

    # a lone download yields no documents, which surfaces as the usual error
    with pytest.raises(RuntimeError):
        list(connector.load_from_state())

    assert context.new_page.call_count == 1, "a download is deterministic: no retries"
    assert mock_start_playwright.call_count == 1, "no browser relaunch for a download"


@patch("onyx.connectors.web.connector.reap_zombie_children")
def test_session_stop_reaps_orphaned_chromium_helpers(mock_reap: MagicMock) -> None:
    session_ctx = ScrapeSessionContext(BASE_URL, [BASE_URL])
    session_ctx.playwright = MagicMock()
    session_ctx.playwright_context = MagicMock()

    session_ctx.stop()

    mock_reap.assert_called_once()
