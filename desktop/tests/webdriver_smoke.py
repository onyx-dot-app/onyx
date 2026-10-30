"""Runtime smoke test for the desktop shell's web-platform contract.

Drives the real desktop binary through tauri-driver (WebKitWebDriver on
Linux) against a local fixture server. Each check is a browser behaviour the
web app relies on and that the shell must provide: script popups with a
working `window.opener`, external links in the system browser, JavaScript
dialogs, and downloads.

Usage: python3 desktop/tests/webdriver_smoke.py <path-to-onyx-binary>
Requires `tauri-driver` and `WebKitWebDriver` on PATH and a display.
"""

from __future__ import annotations

import http.server
import json
import os
import socket
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from pathlib import Path
from typing import Any

DOWNLOAD_NAME = "onyx-smoke-download.txt"
DOWNLOAD_BODY = b"onyx desktop download\n"
FIXTURE_HTML = b"""<!doctype html>
<html><head><title>Onyx desktop smoke</title></head>
<body>
<a id="download" href="/download">download</a>
<button id="blank-popup" onclick="
  const popup = window.open('about:blank', '_blank');
  window.blankOpened = popup !== null;
  if (popup) popup.location.href = window.location.origin + '/popup';
">blank popup</button>
<button id="closable-popup" onclick="window.closablePopup = window.open('about:blank', '_blank');">
closable popup</button>
<button id="external" onclick="
  window.externalOpened = window.open('https://docs.onyx.app/smoke', '_blank') !== null;
">external</button>
<script>
window.popupMessages = [];
window.addEventListener("message", (event) => window.popupMessages.push(event.data));
</script>
</body></html>
"""
POPUP_HTML = b"""<!doctype html>
<html><body><script>
window.opener.postMessage("popup-ready", window.location.origin);
</script></body></html>
"""


class FixtureHandler(http.server.BaseHTTPRequestHandler):
    def do_HEAD(self) -> None:
        self._respond(include_body=False)

    def do_GET(self) -> None:
        self._respond(include_body=True)

    def _respond(self, include_body: bool) -> None:
        headers: dict[str, str] = {"Content-Type": "text/html"}
        body = FIXTURE_HTML
        if self.path.startswith("/popup"):
            body = POPUP_HTML
        elif self.path.startswith("/download"):
            body = DOWNLOAD_BODY
            headers = {
                "Content-Type": "text/plain",
                "Content-Disposition": f'attachment; filename="{DOWNLOAD_NAME}"',
            }
        self.send_response(200)
        for key, value in headers.items():
            self.send_header(key, value)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        if include_body:
            self.wfile.write(body)

    def log_message(self, format: str, *args: Any) -> None:  # noqa: ARG002
        return


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


class WebDriver:
    def __init__(self, base_url: str) -> None:
        self.base_url = base_url
        self.session_id = ""

    def request(self, method: str, path: str, payload: object | None = None) -> Any:
        data = None if payload is None else json.dumps(payload).encode()
        # Only ever the local tauri-driver URL built in main().
        request = urllib.request.Request(  # noqa: S310
            f"{self.base_url}{path}",
            data=data,
            method=method,
            headers={"Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(request, timeout=60) as response:  # noqa: S310
                return json.loads(response.read() or b"{}").get("value")
        except urllib.error.HTTPError as error:
            raise RuntimeError(f"{method} {path}: {error.read().decode()}") from error

    def session(
        self, path: str, method: str = "GET", payload: object | None = None
    ) -> Any:
        return self.request(method, f"/session/{self.session_id}{path}", payload)

    def execute(self, script: str) -> Any:
        return self.session("/execute/sync", "POST", {"script": script, "args": []})

    def click(self, element_id: str) -> None:
        """A WebDriver click is real input, so it carries the user gesture
        that `window.open` needs."""
        element = self.session(
            "/element", "POST", {"using": "css selector", "value": f"#{element_id}"}
        )
        reference = next(iter(element.values()))
        self.session(f"/element/{reference}/click", "POST", {})

    def execute_async(self, script: str) -> Any:
        return self.session("/execute/async", "POST", {"script": script, "args": []})


def wait_for(description: str, check: Callable[[], bool], timeout: float = 20) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            if check():
                return
        except (RuntimeError, OSError):
            pass
        time.sleep(0.25)
    raise AssertionError(f"Timed out waiting for {description}")


def main() -> int:
    binary = Path(sys.argv[1]).resolve()
    fixture_port = free_port()
    fixture_url = f"http://127.0.0.1:{fixture_port}"
    server = http.server.ThreadingHTTPServer(
        ("127.0.0.1", fixture_port), FixtureHandler
    )
    threading.Thread(target=server.serve_forever, daemon=True).start()

    home = Path(tempfile.mkdtemp(prefix="onyx-desktop-smoke-"))
    config_dir = home / ".config" / "onyx-desktop"
    config_dir.mkdir(parents=True)
    (config_dir / "config.json").write_text(json.dumps({"server_url": fixture_url}))
    downloads = home / "Downloads"
    downloads.mkdir()
    (home / ".config" / "user-dirs.dirs").write_text(
        f'XDG_DOWNLOAD_DIR="{downloads}"\n'
    )

    # The shell hands external links to `xdg-open`; record them instead.
    bin_dir = home / "bin"
    bin_dir.mkdir()
    opened_log = home / "opened-urls.txt"
    fake_opener = bin_dir / "xdg-open"
    fake_opener.write_text(f'#!/bin/sh\necho "$1" >> "{opened_log}"\n')
    fake_opener.chmod(0o755)

    env = {
        **os.environ,
        # Moving HOME would otherwise hide the X server's auth cookie.
        "XAUTHORITY": os.environ.get("XAUTHORITY", str(Path.home() / ".Xauthority")),
        "HOME": str(home),
        "XDG_CONFIG_HOME": str(home / ".config"),
        "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}",
    }
    driver_port = free_port()
    driver_process = subprocess.Popen(
        ["tauri-driver", "--port", str(driver_port)],
        env=env,
        stdout=sys.stderr,
        stderr=sys.stderr,
    )
    driver = WebDriver(f"http://127.0.0.1:{driver_port}")
    failures: list[str] = []
    try:
        wait_for(
            "tauri-driver",
            lambda: (
                socket.create_connection(("127.0.0.1", driver_port)).close() is None
            ),
        )
        created = driver.request(
            "POST",
            "/session",
            {
                "capabilities": {
                    "alwaysMatch": {"tauri:options": {"application": str(binary)}}
                }
            },
        )
        driver.session_id = created["sessionId"]
        main_handle = driver.session("/window")
        wait_for(
            "the fixture page to load",
            lambda: driver.execute("return document.title") == "Onyx desktop smoke",
        )

        def check(name: str, run: Callable[[], None]) -> None:
            try:
                run()
                print(f"PASS {name}")
            except Exception as error:
                failures.append(name)
                print(f"FAIL {name}: {error}")
            finally:
                for handle in driver.session("/window/handles"):
                    if handle != main_handle:
                        driver.session("/window", "POST", {"handle": handle})
                        driver.session("/window", "DELETE")
                driver.session("/window", "POST", {"handle": main_handle})

        def blank_popup_navigated_later() -> None:
            driver.click("blank-popup")
            assert driver.execute("return window.blankOpened") is True, (
                "window.open returned null"
            )
            wait_for(
                "the popup to postMessage its opener",
                lambda: "popup-ready" in driver.execute("return window.popupMessages"),
            )

        def popup_closes_itself() -> None:
            driver.click("closable-popup")
            wait_for(
                "the popup window", lambda: len(driver.session("/window/handles")) == 2
            )
            driver.execute("window.closablePopup.close();")
            wait_for(
                "the popup to close",
                lambda: len(driver.session("/window/handles")) == 1,
            )

        def external_link_opens_in_browser() -> None:
            driver.click("external")
            assert driver.execute("return window.externalOpened") is False, (
                "external link opened inside the app"
            )
            wait_for(
                "the system browser to receive the URL",
                lambda: (
                    opened_log.exists() and "docs.onyx.app" in opened_log.read_text()
                ),
            )

        def javascript_dialogs() -> None:
            driver.execute_async(
                "const done = arguments[arguments.length - 1];"
                "setTimeout(() => { window.confirmResult = confirm('Delete?'); }, 0);"
                "done();"
            )
            wait_for(
                "the confirm dialog", lambda: driver.session("/alert/text") == "Delete?"
            )
            driver.session("/alert/accept", "POST", {})
            wait_for(
                "confirm to return",
                lambda: driver.execute("return window.confirmResult") is True,
            )

        def download_saves_file() -> None:
            driver.execute("document.getElementById('download').click();")
            wait_for(
                "the downloaded file",
                lambda: (
                    (downloads / DOWNLOAD_NAME).exists()
                    and (downloads / DOWNLOAD_NAME).read_bytes() == DOWNLOAD_BODY
                ),
            )

        check(
            "blank popup navigated later keeps window.opener",
            blank_popup_navigated_later,
        )
        check("script popup can close itself", popup_closes_itself)
        check(
            "external link opens in the system browser", external_link_opens_in_browser
        )
        check("confirm() shows a dialog and returns the choice", javascript_dialogs)
        check("download saves to the Downloads folder", download_saves_file)
    finally:
        if driver.session_id:
            try:
                driver.request("DELETE", f"/session/{driver.session_id}")
            except RuntimeError:
                pass
        driver_process.terminate()
        server.shutdown()

    if failures:
        print(f"{len(failures)} desktop smoke check(s) failed")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
