"""Readiness must use one deadline across real HTTP probes and metadata loads."""

import time
from collections.abc import Generator
from contextlib import contextmanager
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Lock, Thread
from unittest.mock import patch
from uuid import UUID

import pytest

from onyx.server.features.build.sandbox import serve_transport
from onyx.server.features.build.sandbox.serve_transport import (
    ServeConnectionInfo,
    _ServeMixin,
)

_SANDBOX_ID = UUID("12345678-1234-1234-1234-1234567890ab")


@dataclass(frozen=True)
class _HealthResponse:
    status: int
    delay: float = 0.0
    header_interval: float = 0.0


@contextmanager
def _health_server(
    responses: list[_HealthResponse],
) -> Generator[tuple[str, list[str | None]], None, None]:
    authorizations: list[str | None] = []
    request_lock = Lock()

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            with request_lock:
                response = responses[min(len(authorizations), len(responses) - 1)]
                authorizations.append(self.headers.get("Authorization"))
            time.sleep(response.delay)
            try:
                self.send_response(response.status)
                if response.header_interval:
                    self.flush_headers()
                    time.sleep(response.header_interval)
                    self.send_header("Content-Length", "0")
                    self.flush_headers()
                    time.sleep(response.header_interval)
                self.end_headers()
            except (BrokenPipeError, ConnectionResetError):
                pass

        def log_message(self, format: str, *args: object) -> None:
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    server.daemon_threads = False
    thread = Thread(target=server.serve_forever, kwargs={"poll_interval": 0.01})
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}", authorizations
    finally:
        server.shutdown()
        thread.join()
        server.server_close()


class _ReadinessManager(_ServeMixin):
    def __init__(
        self,
        base_url: str,
        *,
        load_delay: float = 0.0,
        refresh_delay: float = 0.0,
    ) -> None:
        self.base_url = base_url
        self.load_delay = load_delay
        self.refresh_delay = refresh_delay
        self.loads = 0
        self._init_serve_state()

    def _load_serve_connection_info(
        self,
        sandbox_id: UUID,  # noqa: ARG002
    ) -> ServeConnectionInfo:
        self.loads += 1
        time.sleep(self.load_delay if self.loads == 1 else self.refresh_delay)
        return ServeConnectionInfo(
            base_url=self.base_url,
            password="stale" if self.loads == 1 else "fresh",
        )


def test_retry_cannot_accept_http_success_after_readiness_deadline(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(serve_transport, "POLL_INTERVAL_SECONDS", 0.01)
    with _health_server(
        [_HealthResponse(503, delay=0.4), _HealthResponse(200, delay=0.85)]
    ) as (base_url, authorizations):
        manager = _ReadinessManager(base_url)
        ready = manager._wait_for_opencode_serve_ready(_SANDBOX_ID, timeout=1.0)

        assert ready is False
        assert len(authorizations) == 2


def test_readiness_accepts_http_success_before_deadline() -> None:
    with _health_server([_HealthResponse(200)]) as (base_url, authorizations):
        manager = _ReadinessManager(base_url)

        assert manager._wait_for_opencode_serve_ready(_SANDBOX_ID, timeout=1.0)
        assert authorizations == ["Basic b3BlbmNvZGU6c3RhbGU="]


def test_password_refresh_authenticates_before_deadline(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(serve_transport, "POLL_INTERVAL_SECONDS", 0.01)
    with _health_server([_HealthResponse(401), _HealthResponse(200)]) as (
        base_url,
        authorizations,
    ):
        manager = _ReadinessManager(base_url)

        assert manager._wait_for_opencode_serve_ready(_SANDBOX_ID, timeout=1.0)
        assert manager.loads == 2
        assert authorizations == [
            "Basic b3BlbmNvZGU6c3RhbGU=",
            "Basic b3BlbmNvZGU6ZnJlc2g=",
        ]


def test_poll_sleep_uses_remaining_readiness_budget() -> None:
    with _health_server([_HealthResponse(503)]) as (base_url, authorizations):
        manager = _ReadinessManager(base_url)

        with patch.object(serve_transport, "time", wraps=time) as observed_time:
            assert (
                manager._wait_for_opencode_serve_ready(_SANDBOX_ID, timeout=0.2)
                is False
            )

        assert authorizations == ["Basic b3BlbmNvZGU6c3RhbGU="]
        sleep_durations = [call.args[0] for call in observed_time.sleep.call_args_list]
        assert sleep_durations
        assert all(0 < duration <= 0.2 for duration in sleep_durations)


def test_late_http_success_is_rejected_even_when_each_read_meets_its_timeout() -> None:
    with _health_server([_HealthResponse(200, header_interval=0.25)]) as (
        base_url,
        authorizations,
    ):
        manager = _ReadinessManager(base_url)

        assert manager._wait_for_opencode_serve_ready(_SANDBOX_ID, timeout=0.4) is False
        assert authorizations == ["Basic b3BlbmNvZGU6c3RhbGU="]


def test_connection_load_consumes_readiness_budget() -> None:
    with _health_server([_HealthResponse(200)]) as (base_url, authorizations):
        manager = _ReadinessManager(base_url, load_delay=0.3)

        assert manager._wait_for_opencode_serve_ready(_SANDBOX_ID, timeout=0.1) is False
        assert manager.loads == 1
        assert authorizations == []


def test_password_refresh_cannot_restart_readiness_budget() -> None:
    with _health_server([_HealthResponse(401), _HealthResponse(200)]) as (
        base_url,
        authorizations,
    ):
        manager = _ReadinessManager(base_url, refresh_delay=0.3)

        assert manager._wait_for_opencode_serve_ready(_SANDBOX_ID, timeout=0.2) is False
        assert manager.loads == 2
        assert authorizations == ["Basic b3BlbmNvZGU6c3RhbGU="]
