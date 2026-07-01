"""End-to-end proxy test for response streaming.

Drives a chunked upstream response through a *real* mitmproxy instance with
the `GateAddon` wired in, and asserts the client receives a byte *before* the
upstream has finished generating — i.e. the body is relayed incrementally,
not buffered whole. This is the only assertion that catches the real failure
mode (hooking `response` instead of `responseheaders`); pinning
`flow.response.stream` on a mock would not, since the relay never runs.

Uses real local TCP sockets only; no Onyx services are touched (the db/cache
factories are wired to raise if consulted), so this lives in the unit suite.
"""

from __future__ import annotations

import asyncio
import http.client
import socket
import threading
import time
from collections.abc import Callable
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler
from http.server import ThreadingHTTPServer
from pathlib import Path
from typing import Any
from uuid import UUID
from uuid import uuid4

import pytest
from mitmproxy import http as mitm_http
from mitmproxy.options import Options
from mitmproxy.tools.dump import DumpMaster

from onyx.sandbox_proxy.addons import gate
from onyx.sandbox_proxy.addons.gate import _IdentityResolver
from onyx.sandbox_proxy.addons.gate import GateAddon
from onyx.sandbox_proxy.credential_injection import CredentialInjectionDispatcher
from onyx.sandbox_proxy.identity import ResolvedSandbox
from onyx.sandbox_proxy.request_evaluator import RequestEvaluator

# Inter-chunk delay on the upstream. The whole stream takes
# `(_CHUNK_COUNT - 1) * _CHUNK_DELAY_S`, during which a streamed client must
# observe its first byte while `upstream_done_at` is still unset. A wide
# window keeps the structural assertion robust against scheduler jitter.
_CHUNK_DELAY_S = 0.4
_CHUNK_COUNT = 6
_FIXED_BODY = b"a fixed-length body delivered intact\n"


class _UpstreamHandler(BaseHTTPRequestHandler):
    # Stamped right before the terminator: a client byte read while this is
    # still None proves incremental relay. Stamping after the terminator would
    # race the buffered-mode client, which unblocks the instant it arrives.
    upstream_done_at: float | None = None

    def log_message(self, format: str, *args: Any) -> None:  # noqa: A002, ARG002
        return

    def do_GET(self) -> None:
        if self.path == "/stream":
            self._serve_chunked()
        else:
            self._serve_fixed()
        self.close_connection = True

    def _serve_chunked(self) -> None:
        self.wfile.write(
            b"HTTP/1.1 200 OK\r\n"
            b"Content-Type: text/event-stream\r\n"
            b"Transfer-Encoding: chunked\r\n"
            b"\r\n"
        )
        self.wfile.flush()
        for i in range(_CHUNK_COUNT):
            data = f"data: chunk-{i}\n\n".encode()
            self.wfile.write(f"{len(data):x}\r\n".encode() + data + b"\r\n")
            self.wfile.flush()
            if i < _CHUNK_COUNT - 1:
                time.sleep(_CHUNK_DELAY_S)
        type(self).upstream_done_at = time.monotonic()
        self.wfile.write(b"0\r\n\r\n")
        self.wfile.flush()

    def _serve_fixed(self) -> None:
        self.wfile.write(
            b"HTTP/1.1 200 OK\r\n"
            b"Content-Type: text/plain\r\n"
            + f"Content-Length: {len(_FIXED_BODY)}\r\n".encode()
            + b"\r\n"
            + _FIXED_BODY
        )
        self.wfile.flush()


class _StubResolver(_IdentityResolver):
    """Resolves any source IP to one sandbox so the request is forwarded."""

    def resolve_sandbox(self, src_ip: str) -> ResolvedSandbox:  # noqa: ARG002
        return ResolvedSandbox(
            sandbox_id=UUID("11111111-1111-1111-1111-111111111111"),
            user_id=uuid4(),
            tenant_id="public",
            sandbox_name="sandbox-test",
            sandbox_ip="127.0.0.1",
        )

    def resolve_session_by_id(
        self,
        session_id: UUID,  # noqa: ARG002
        user_id: UUID,  # noqa: ARG002
        tenant_id: str,  # noqa: ARG002
    ) -> UUID | None:
        return None


class _NonGatingMatcher(RequestEvaluator):
    """Never matches, so every request fails open and is forwarded."""

    def evaluate(
        self,
        request: mitm_http.Request,  # noqa: ARG002
        tenant_id: str,  # noqa: ARG002
        user_id: UUID,  # noqa: ARG002
    ) -> None:
        return None


def _unused_factory(_tenant_id: str) -> Any:
    raise AssertionError("forward path must not touch db/cache factories")


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def _wait_for_port(port: int, timeout_s: float = 5.0) -> bool:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.5):
                return True
        except OSError:
            time.sleep(0.05)
    return False


@pytest.fixture
def upstream() -> Iterator[int]:
    _UpstreamHandler.upstream_done_at = None
    server = ThreadingHTTPServer(("127.0.0.1", 0), _UpstreamHandler)
    port = int(server.server_address[1])
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield port
    finally:
        server.shutdown()
        server.server_close()


@pytest.fixture(autouse=True)
def _allow_loopback_egress(monkeypatch: pytest.MonkeyPatch) -> None:
    """These tests route through 127.0.0.1 (loopback = internal), which the egress
    guard correctly blocks in production. They exercise response streaming, not the
    egress boundary, so bypass the guard here."""
    monkeypatch.setattr(gate, "destination_is_blocked", lambda _host, _port: False)


def _start_proxy(
    *, stream_responses: bool, confdir: Path, attempts: int = 5
) -> tuple[int, Callable[[], None]]:
    """Start a real DumpMaster with the GateAddon; return (port, stop).

    Retries on a lost port race (`_free_port` releases the port before
    mitmproxy binds it), so it's resilient under parallel test runs.
    """
    gate = GateAddon(
        identity=_StubResolver(),
        request_evaluator=_NonGatingMatcher(),
        cache_factory=_unused_factory,
        proxy_instance_id="proxy-test",
        credential_dispatcher=CredentialInjectionDispatcher([]),
        stream_responses=stream_responses,
    )

    last_error = "unknown"
    for _ in range(attempts):
        port = _free_port()
        holder: dict[str, Any] = {}
        ready = threading.Event()

        async def _amain(bind_port: int) -> None:
            options = Options(
                listen_host="127.0.0.1",
                listen_port=bind_port,
                confdir=str(confdir),
                mode=["regular"],
            )
            master = DumpMaster(options, with_termlog=False, with_dumper=False)
            master.addons.add(gate)
            holder["master"] = master
            holder["loop"] = asyncio.get_running_loop()
            ready.set()
            await master.run()

        thread = threading.Thread(
            target=lambda p=port: asyncio.run(_amain(p)), daemon=True
        )
        thread.start()

        def _stop() -> None:
            loop = holder.get("loop")
            master = holder.get("master")
            if loop is not None and master is not None:
                loop.call_soon_threadsafe(master.shutdown)
            thread.join(timeout=10.0)

        if not ready.wait(timeout=10.0):
            last_error = "DumpMaster never signalled readiness"
            _stop()
            continue
        if _wait_for_port(port):
            return port, _stop
        last_error = f"proxy did not bind 127.0.0.1:{port} (lost-port race)"
        _stop()

    raise RuntimeError(f"could not start proxy after {attempts} attempts: {last_error}")


@pytest.mark.parametrize(
    "stream_responses", [True, False], ids=["streamed", "buffered"]
)
def test_chunked_response_relayed_incrementally(
    stream_responses: bool, upstream: int, tmp_path: Path
) -> None:
    """With streaming on, the client holds a byte while the upstream is still
    generating (`upstream_done_at` unset); with it off (buffered), the first
    byte only arrives after the upstream has finished."""
    proxy_port, stop = _start_proxy(stream_responses=stream_responses, confdir=tmp_path)
    try:
        conn = http.client.HTTPConnection("127.0.0.1", proxy_port, timeout=15)
        conn.request("GET", f"http://127.0.0.1:{upstream}/stream")
        resp = conn.getresponse()

        first_byte = resp.read(1)
        # None here means the upstream was still streaming when the byte landed.
        done_at_first_byte = _UpstreamHandler.upstream_done_at
        body = first_byte + resp.read()
        conn.close()
    finally:
        stop()

    assert resp.status == 200
    assert body.count(b"data: chunk-") == _CHUNK_COUNT

    if stream_responses:
        assert done_at_first_byte is None, (
            "expected incremental relay: client should hold a byte before the "
            "upstream finished, but the upstream was already done"
        )
    else:
        assert done_at_first_byte is not None, (
            "expected buffered relay: client should see no byte until the "
            "upstream finished, but it received one early"
        )


def test_fixed_length_response_delivered_intact(upstream: int, tmp_path: Path) -> None:
    """Streaming a fixed-Content-Length response is a harmless chunked relay:
    the body still arrives byte-for-byte intact."""
    proxy_port, stop = _start_proxy(stream_responses=True, confdir=tmp_path)
    try:
        conn = http.client.HTTPConnection("127.0.0.1", proxy_port, timeout=15)
        conn.request("GET", f"http://127.0.0.1:{upstream}/fixed")
        resp = conn.getresponse()
        body = resp.read()
        conn.close()
    finally:
        stop()

    assert resp.status == 200
    assert body == _FIXED_BODY
