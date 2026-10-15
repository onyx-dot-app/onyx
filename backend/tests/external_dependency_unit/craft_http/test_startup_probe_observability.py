import base64
import json
import logging
import re
import time
from collections.abc import Generator
from contextlib import contextmanager
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Lock, Thread

import httpx
import pytest

from onyx.server.features.build.sandbox.opencode import serve_client
from onyx.server.features.build.sandbox.opencode.serve_client import (
    ClientTimeouts,
    OpencodeServeClient,
)
from tests.integration.common_utils import http_client
from tests.integration.common_utils.managers import build_session
from tests.integration.common_utils.managers.build_session import BuildSessionManager
from tests.integration.common_utils.test_models import DATestUser

_PASSWORD = "probe-password-private"
_TOKEN = "probe-token-private"
_RESPONSE_BODY = b"probe-response-private token=probe-token-private"
_USER = DATestUser(
    id="11111111-1111-1111-1111-111111111111",
    email="startup-probe@example.com",
    password=_PASSWORD,
    headers={"Authorization": f"Bearer {_TOKEN}"},
    cookies={"session": "probe-cookie-private"},
    is_admin=False,
    is_active=True,
)


@dataclass(frozen=True)
class _Reply:
    status: int | None
    body: bytes = _RESPONSE_BODY
    delay: float = 0.0


@dataclass(frozen=True)
class _Request:
    method: str
    path: str
    body: bytes
    authorization: str | None
    cookie: str | None


@contextmanager
def _http_server(
    replies: list[_Reply],
) -> Generator[tuple[str, list[_Request]], None, None]:
    requests: list[_Request] = []
    request_lock = Lock()

    class Handler(BaseHTTPRequestHandler):
        def _respond(self) -> None:
            with request_lock:
                reply = replies[min(len(requests), len(replies) - 1)]
                requests.append(
                    _Request(
                        method=self.command,
                        path=self.path,
                        body=self.rfile.read(
                            int(self.headers.get("Content-Length", 0))
                        ),
                        authorization=self.headers.get("Authorization"),
                        cookie=self.headers.get("Cookie"),
                    )
                )
            if reply.status is None:
                self.close_connection = True
                return
            time.sleep(reply.delay)
            try:
                self.send_response(reply.status)
                self.send_header("Content-Length", str(len(reply.body)))
                self.end_headers()
                self.wfile.write(reply.body)
            except (BrokenPipeError, ConnectionResetError):
                pass

        do_GET = _respond
        do_POST = _respond
        do_DELETE = _respond

        def log_message(self, format: str, *args: object) -> None:
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    server.daemon_threads = False
    thread = Thread(target=server.serve_forever, kwargs={"poll_interval": 0.01})
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}", requests
    finally:
        server.shutdown()
        thread.join()
        server.server_close()


def test_first_session_creation_error_does_not_retry_or_delete(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with _http_server([_Reply(500, b"startup failed")]) as (base_url, requests):
        monkeypatch.setattr(build_session, "API_SERVER_URL", base_url)
        with httpx.Client() as client:
            http_client.set_test_client(client)
            try:
                with pytest.raises(
                    AssertionError,
                    match="POST /build/sessions failed: 500 Internal Server Error",
                ):
                    BuildSessionManager.create(_USER, name="first failure")
            finally:
                http_client.set_test_client(None)

        assert [(request.method, request.path) for request in requests] == [
            ("POST", "/build/sessions")
        ]
        assert json.loads(requests[0].body) == {
            "headless": True,
            "name": "first failure",
        }


def test_session_creation_keeps_owned_empty_session_isolation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fresh_session = {
        "id": "22222222-2222-2222-2222-222222222222",
        "user_id": _USER.id,
        "name": "fresh session",
        "status": "active",
        "created_at": "2026-10-15T00:00:00Z",
        "last_activity_at": "2026-10-15T00:00:00Z",
        "nextjs_port": None,
        "sandbox": None,
        "artifacts": [],
        "sharing_scope": "private",
        "origin": "INTERACTIVE",
        "agent_provider": None,
        "agent_model": None,
        "skills_stale": False,
        "session_loaded_in_sandbox": True,
    }
    with _http_server(
        [
            _Reply(200, b'{"id":"owned-empty-session"}'),
            _Reply(204, b""),
            _Reply(200, json.dumps(fresh_session).encode()),
        ]
    ) as (base_url, requests):
        monkeypatch.setattr(build_session, "API_SERVER_URL", base_url)
        with httpx.Client() as client:
            http_client.set_test_client(client)
            try:
                session = BuildSessionManager.create(
                    _USER, headless=False, name="fresh session"
                )
            finally:
                http_client.set_test_client(None)

        assert session.id == "22222222-2222-2222-2222-222222222222"
        assert session.name == "fresh session"
        assert session.session_loaded_in_sandbox is True
        assert [(request.method, request.path) for request in requests] == [
            ("POST", "/build/sessions"),
            ("DELETE", "/build/sessions/owned-empty-session"),
            ("POST", "/build/sessions"),
        ]
        assert [json.loads(request.body) for request in requests if request.body] == [
            {"headless": False, "name": "fresh session"},
            {"headless": False, "name": "fresh session"},
        ]
        assert [request.authorization for request in requests] == [
            f"Bearer {_TOKEN}",
            f"Bearer {_TOKEN}",
            f"Bearer {_TOKEN}",
        ]
        assert [request.cookie for request in requests] == [
            "session=probe-cookie-private",
            "session=probe-cookie-private",
            "session=probe-cookie-private",
        ]


@pytest.mark.parametrize("status", [200, 401, 503, None])
@pytest.mark.parametrize(
    "timeout,expected_timeout", [(None, 0.5), (0.25, 0.25), (0.75, 0.5)]
)
def test_health_probe_logs_only_safe_failure_metadata(
    caplog: pytest.LogCaptureFixture,
    status: int | None,
    timeout: float | None,
    expected_timeout: float,
) -> None:
    caplog.set_level(logging.INFO, logger=serve_client.logger.name)
    with _http_server([_Reply(status)]) as (base_url, requests):
        with OpencodeServeClient(
            base_url=base_url,
            password=_PASSWORD,
            timeouts=ClientTimeouts(connect_timeout=0.5),
        ) as client:
            assert client.health_check_status(timeout=timeout) == status

        authorization = (
            "Basic " + base64.b64encode(f"opencode:{_PASSWORD}".encode()).decode()
        )
        assert [(request.method, request.path) for request in requests] == [
            ("GET", "/global/health")
        ]
        assert requests[0].authorization == authorization
        records = [
            record
            for record in caplog.records
            if record.name == serve_client.logger.name
        ]
        if status == 200:
            assert records == []
            return
        assert len(records) == 1
        assert records[0].levelno == logging.INFO
        message = records[0].getMessage()
        outcome = (
            "exception=RemoteProtocolError" if status is None else f"status={status}"
        )
        assert outcome in message
        assert re.search(r"elapsed=\d+\.\d+s", message)
        assert f"timeout={expected_timeout:.3f}s" in message
        for private_value in (
            _PASSWORD,
            _TOKEN,
            _RESPONSE_BODY.decode(),
            authorization,
            base_url,
            "Server disconnected",
        ):
            assert private_value not in message


@pytest.mark.parametrize(
    "connect_timeout,remaining_timeout", [(0.5, 0.01), (0.01, 0.75)]
)
def test_health_probe_read_timeout_keeps_none_contract_and_safe_log(
    caplog: pytest.LogCaptureFixture,
    connect_timeout: float,
    remaining_timeout: float,
) -> None:
    caplog.set_level(logging.INFO, logger=serve_client.logger.name)
    with _http_server([_Reply(200, delay=0.05)]) as (base_url, requests):
        with OpencodeServeClient(
            base_url=base_url,
            password=_PASSWORD,
            timeouts=ClientTimeouts(connect_timeout=connect_timeout),
        ) as client:
            assert client.health_check_status(timeout=remaining_timeout) is None
        assert [(request.method, request.path) for request in requests] == [
            ("GET", "/global/health")
        ]
    messages = [
        record.getMessage()
        for record in caplog.records
        if record.name == serve_client.logger.name
    ]
    assert len(messages) == 1
    assert "exception=ReadTimeout" in messages[0]
    assert "timeout=0.010s" in messages[0]
    assert _PASSWORD not in messages[0]
    assert _RESPONSE_BODY.decode() not in messages[0]


def test_health_check_keeps_boolean_contract() -> None:
    with _http_server([_Reply(200), _Reply(401)]) as (base_url, requests):
        with OpencodeServeClient(base_url=base_url, password=_PASSWORD) as client:
            assert client.health_check() is True
            assert client.health_check() is False
        assert [(request.method, request.path) for request in requests] == [
            ("GET", "/global/health"),
            ("GET", "/global/health"),
        ]
