import http.client
import threading
from collections.abc import Iterator
from http.server import HTTPServer

import pytest

from onyx.sandbox_proxy.identity import SandboxIPLookup
from onyx.sandbox_proxy.server import _build_healthz_handler
from onyx.sandbox_proxy.server import _Readiness


class _FakeLookup(SandboxIPLookup):
    def __init__(self, synced: bool) -> None:
        self._synced = synced

    def start(self) -> None:
        return None

    def lookup(self, src_ip: str) -> None:  # noqa: ARG002
        return None

    def wait_for_initial_sync(
        self,
        timeout_seconds: float,  # noqa: ARG002
    ) -> bool:
        return self._synced

    def is_synced(self) -> bool:
        return self._synced

    def stop(self) -> None:
        return None


def _serve(handler_cls: type) -> tuple[HTTPServer, int]:
    server = HTTPServer(("127.0.0.1", 0), handler_cls)
    port = server.server_address[1]
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, port


def _get(port: int, path: str) -> tuple[int, str]:
    conn = http.client.HTTPConnection("127.0.0.1", port)
    try:
        conn.request("GET", path)
        resp = conn.getresponse()
        return resp.status, resp.read().decode()
    finally:
        conn.close()


@pytest.fixture
def healthz() -> Iterator[tuple[_Readiness, _FakeLookup, int]]:
    readiness = _Readiness()
    lookup = _FakeLookup(synced=False)
    handler_cls = _build_healthz_handler(readiness, lookup)
    server, port = _serve(handler_cls)
    try:
        yield readiness, lookup, port
    finally:
        server.shutdown()
        server.server_close()


def test_returns_503_before_ca_ready(
    healthz: tuple[_Readiness, _FakeLookup, int],
) -> None:
    _readiness, _lookup, port = healthz
    status, body = _get(port, "/healthz")
    assert status == 503
    assert "not ready" in body


def test_returns_503_when_lookup_unsynced(
    healthz: tuple[_Readiness, _FakeLookup, int],
) -> None:
    readiness, _lookup, port = healthz
    readiness.ca_ready = True
    status, _ = _get(port, "/healthz")
    assert status == 503


def test_returns_200_when_fully_ready(
    healthz: tuple[_Readiness, _FakeLookup, int],
) -> None:
    readiness, lookup, port = healthz
    readiness.ca_ready = True
    lookup._synced = True
    status, body = _get(port, "/healthz")
    assert status == 200
    assert "ok" in body


def test_returns_503_when_shutting_down(
    healthz: tuple[_Readiness, _FakeLookup, int],
) -> None:
    readiness, lookup, port = healthz
    readiness.ca_ready = True
    lookup._synced = True
    readiness.shutting_down = True
    status, _ = _get(port, "/healthz")
    assert status == 503


def test_returns_404_for_unknown_path(
    healthz: tuple[_Readiness, _FakeLookup, int],
) -> None:
    _readiness, _lookup, port = healthz
    status, _ = _get(port, "/elsewhere")
    assert status == 404


def test_loses_readiness_on_watch_disconnect_even_after_initial_sync(
    healthz: tuple[_Readiness, _FakeLookup, int],
) -> None:
    # Watch-reconnect scenario: is_synced() flips back to False after a sync.
    readiness, lookup, port = healthz
    readiness.ca_ready = True
    lookup._synced = True
    assert _get(port, "/healthz")[0] == 200

    lookup._synced = False
    assert _get(port, "/healthz")[0] == 503
