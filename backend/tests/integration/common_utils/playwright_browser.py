"""Chromium download for the suites that crawl the web.

Two suites launch Playwright: `tests/web_search` (OnyxWebCrawler's fallback)
and `tests/pruning` (the WEB connector). Every other suite must not pay the
download, so each of those two opts in from its own conftest.
"""

import os
import platform
import subprocess


def install_chromium_headless_shell() -> None:
    """Download the chromium headless shell.

    The devcontainer ships the apt deps; download the browser here so the
    version tracks the lockfile's playwright-python. `--only-shell` skips the
    179 MB full build: both consumers launch headless with no channel, so they
    use the 106 MB headless shell. Playwright has no ubuntu26.04 build yet, so
    pin to the binary-compatible 24.04 build.
    """
    machine = platform.machine().lower()
    pw_arch = "x64" if machine in ("x86_64", "amd64") else "arm64"
    env = os.environ.copy()
    env["PLAYWRIGHT_HOST_PLATFORM_OVERRIDE"] = f"ubuntu24.04-{pw_arch}"
    subprocess.run(
        ["playwright", "install", "--only-shell", "chromium"], env=env, check=True
    )
