"""The crawler must bound response bodies while it reads them, against a real
local HTTP server (gzip bomb and slow-drip body)."""

from __future__ import annotations

import os
import subprocess
import sys
import threading
import time
import tracemalloc
import zlib
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest
import requests
from pydantic import ValidationError

import onyx.tools.tool_implementations.open_url.onyx_web_crawler as crawler_module
from onyx.server.features.web_search.models import OpenUrlsToolRequest
from onyx.tools.tool_implementations.open_url.onyx_web_crawler import (
    FailureReason,
    OnyxWebCrawler,
)
from onyx.utils.url import MAX_REDIRECTS, SSRFException, ssrf_safe_get

_BOMB_DECODED_BYTES = 256 * 1024 * 1024
_CAP_BYTES = 1024 * 1024
_DRIP_SECONDS = 8.0


def _gzip_bomb() -> bytes:
    compressor = zlib.compressobj(9, zlib.DEFLATED, 16 + zlib.MAX_WBITS)
    block = b"\0" * (1024 * 1024)
    parts = [
        compressor.compress(block) for _ in range(_BOMB_DECODED_BYTES // len(block))
    ]
    parts.append(compressor.flush())
    return b"".join(parts)


class _Handler(BaseHTTPRequestHandler):
    bomb: bytes = b""

    def log_message(self, format: str, *args: Any) -> None:  # noqa: A002, ARG002
        return None

    def do_GET(self) -> None:
        if self.path == "/bomb":
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.send_header("Content-Encoding", "gzip")
            self.send_header("Content-Length", str(len(self.bomb)))
            self.end_headers()
            self.wfile.write(self.bomb)
            return
        if self.path == "/bomb-redirect":
            self.send_response(302)
            self.send_header("Location", "/ok")
            self.send_header("Content-Encoding", "gzip")
            self.send_header("Content-Length", str(len(self.bomb)))
            self.end_headers()
            try:
                self.wfile.write(self.bomb)
            except (BrokenPipeError, ConnectionResetError):
                pass
            return
        if self.path == "/ok":
            body = b"<html><body><p>hello world</p></body></html>"
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        if self.path == "/drip":
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.end_headers()
            end = time.monotonic() + _DRIP_SECONDS
            try:
                while time.monotonic() < end:
                    self.wfile.write(b"<p>x</p>")
                    self.wfile.flush()
                    time.sleep(0.05)
            except (BrokenPipeError, ConnectionResetError):
                pass
            return
        if self.path == "/stall":
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.end_headers()
            self.wfile.write(b"<p>partial</p>")
            self.wfile.flush()
            time.sleep(_DRIP_SECONDS)
            return
        if self.path.startswith("/loop"):
            self.send_response(302)
            self.send_header("Location", "/loop")
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        self.send_response(404)
        self.end_headers()


@pytest.fixture(scope="module")
def server_url() -> Iterator[str]:
    _Handler.bomb = _gzip_bomb()
    server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    server.daemon_threads = True
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}"
    finally:
        server.shutdown()
        server.server_close()


@pytest.fixture(autouse=True)
def _allow_loopback() -> Iterator[None]:
    """The test server is on loopback; keep the real fetch path otherwise."""

    def _get(url: str, **kwargs: Any) -> Any:
        return ssrf_safe_get(
            url,
            **kwargs,
            block_loopback_and_link_local=False,
            block_link_local_only=True,
        )

    with patch.object(crawler_module, "ssrf_safe_get", side_effect=_get):
        yield


def test_gzip_bomb_is_rejected_with_bounded_memory(server_url: str) -> None:
    crawler = OnyxWebCrawler(
        max_html_size_bytes=_CAP_BYTES,
        max_pdf_size_bytes=_CAP_BYTES,
        validate_ssrf=False,
    )
    tracemalloc.start()
    try:
        [result] = crawler.contents([f"{server_url}/bomb"])
        _, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()

    assert not result.scrape_successful
    assert result.failure_reason == FailureReason.OVERSIZED_BODY
    assert peak < 32 * 1024 * 1024


def test_redirect_body_is_not_read(server_url: str) -> None:
    crawler = OnyxWebCrawler(validate_ssrf=False)
    tracemalloc.start()
    try:
        [result] = crawler.contents([f"{server_url}/bomb-redirect"])
        _, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()

    assert result.scrape_successful
    assert "hello world" in result.full_content
    assert peak < 32 * 1024 * 1024


def test_slow_drip_body_hits_deadline(server_url: str) -> None:
    crawler = OnyxWebCrawler(validate_ssrf=False, body_deadline_seconds=1)
    start = time.monotonic()
    [result] = crawler.contents([f"{server_url}/drip"])
    elapsed = time.monotonic() - start

    assert result.failure_reason == FailureReason.BODY_TIMEOUT
    assert elapsed < _DRIP_SECONDS / 2


def test_stalled_body_hits_configured_deadline_before_read_timeout(
    server_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(crawler_module, "OPEN_URL_BODY_DEADLINE_SECONDS", 1.0)
    crawler = OnyxWebCrawler(validate_ssrf=False, timeout_seconds=15)
    start = time.monotonic()
    [result] = crawler.contents([f"{server_url}/stall"])
    elapsed = time.monotonic() - start

    assert result.failure_reason == FailureReason.BODY_TIMEOUT
    assert elapsed < _DRIP_SECONDS / 2


def test_redirect_limit_closes_final_response(server_url: str) -> None:
    opened: list[requests.Response] = []
    closed: set[int] = set()
    real_send = requests.Session.send
    real_close = requests.Response.close

    def _send(self: requests.Session, *args: Any, **kwargs: Any) -> Any:
        response = real_send(self, *args, **kwargs)
        opened.append(response)
        return response

    def _close(self: requests.Response) -> None:
        closed.add(id(self))
        real_close(self)

    with (
        patch.object(requests.Session, "send", _send),
        patch.object(requests.Response, "close", _close),
        pytest.raises(SSRFException, match="Too many redirects"),
    ):
        ssrf_safe_get(
            f"{server_url}/loop",
            allow_private_network=True,
            block_loopback_and_link_local=False,
            block_link_local_only=True,
            stream=True,
        )

    assert len(opened) == MAX_REDIRECTS + 1
    assert all(id(response) in closed for response in opened)


def test_open_urls_request_caps_url_count() -> None:
    with pytest.raises(ValidationError):
        OpenUrlsToolRequest(urls=[f"https://example.com/{i}" for i in range(21)])


@pytest.mark.parametrize(
    "name, value",
    [
        ("OPEN_URL_MAX_HTML_SIZE_BYTES", "1234"),
        ("OPEN_URL_MAX_PDF_SIZE_BYTES", "5678"),
        ("OPEN_URL_BODY_DEADLINE_SECONDS", "7.5"),
        ("OPEN_URLS_MAX_URLS_PER_REQUEST", "3"),
    ],
)
def test_open_url_limits_read_from_env(name: str, value: str) -> None:
    code = f"from onyx.configs import app_configs as c; print(repr(c.{name}))"
    env = {**os.environ, name: value}
    out = subprocess.run(
        [sys.executable, "-c", code],
        env=env,
        capture_output=True,
        text=True,
        check=True,
        cwd=Path(__file__).parents[6],
    ).stdout.strip()
    assert float(out) == float(value)
