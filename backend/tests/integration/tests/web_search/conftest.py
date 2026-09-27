"""Fixtures for the web search integration suite."""

import pytest

from tests.integration.common_utils.playwright_browser import (
    install_chromium_headless_shell,
)


@pytest.fixture(scope="session", autouse=True)
def _install_playwright() -> None:
    """These tests exercise OnyxWebCrawler's Playwright fallback."""
    install_chromium_headless_shell()
