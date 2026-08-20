"""Fixtures for the web search integration suite."""

import os
import platform
import subprocess

import pytest


@pytest.fixture(scope="session", autouse=True)
def _install_playwright() -> None:
    # These tests exercise OnyxWebCrawler's Playwright fallback. The
    # devcontainer ships the apt deps; download the browser here so the
    # version tracks the lockfile's playwright-python. This is the only
    # integration suite that needs a browser, so the download stays here.
    # `--only-shell` skips the 179 MB full build: OnyxWebCrawler launches
    # headless with no channel, so it uses the 106 MB headless shell.
    # Playwright has no ubuntu26.04 build yet, so pin to the
    # binary-compatible 24.04 build.
    machine = platform.machine().lower()
    pw_arch = "x64" if machine in ("x86_64", "amd64") else "arm64"
    env = os.environ.copy()
    env["PLAYWRIGHT_HOST_PLATFORM_OVERRIDE"] = f"ubuntu24.04-{pw_arch}"
    subprocess.run(
        ["playwright", "install", "--only-shell", "chromium"], env=env, check=True
    )
