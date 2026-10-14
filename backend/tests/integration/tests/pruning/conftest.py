"""Fixtures for the pruning integration suite."""

import pytest

from tests.integration.common_utils.playwright_browser import (
    install_chromium_headless_shell,
)


@pytest.fixture(scope="session", autouse=True)
def _install_playwright() -> None:
    """test_web_pruning indexes with the WEB connector, which uses Playwright."""
    install_chromium_headless_shell()
