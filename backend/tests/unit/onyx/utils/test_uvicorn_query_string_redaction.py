import io
import json
import logging
import socket
import threading
import time
from collections.abc import Generator
from typing import Any

import pytest
import uvicorn
from websockets.sync.client import connect as websocket_connect

from onyx.utils.logger import (
    UVICORN_ACCESS_LOGGER_NAME,
    UVICORN_ERROR_LOGGER_NAME,
    ColoredFormatter,
    _strip_query_string_from_path,
    get_json_formatter,
    setup_uvicorn_logger,
)

SECRET_CODE = "SECRET-CODE-VALUE"
SECRET_STATE = "SECRET-STATE-VALUE"

CALLBACK_PATHS = [
    "/auth/oidc/callback",
    "/auth/oidc/okta/callback",
    "/auth/oauth/callback",
    "/connector/oauth/callback/slack",
    "/manage/connector/gmail/callback",
]


async def _app(scope: dict[str, Any], receive: Any, send: Any) -> None:
    if scope["type"] == "websocket":
        await receive()
        await send({"type": "websocket.accept"})
        await send({"type": "websocket.close"})
        return
    await send({"type": "http.response.start", "status": 302, "headers": []})
    await send({"type": "http.response.body", "body": b""})


class _Capture:
    def __init__(self, port: int, access: io.StringIO, error: io.StringIO) -> None:
        self.port = port
        self.access = access
        self.error = error


def _add_capture_handler(logger_name: str, formatter: logging.Formatter) -> io.StringIO:
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.setFormatter(formatter)
    logging.getLogger(logger_name).addHandler(handler)
    return stream


@pytest.fixture(params=["text", "json"])
def server(request: pytest.FixtureRequest) -> Generator[_Capture, None, None]:
    loggers = [
        logging.getLogger(UVICORN_ACCESS_LOGGER_NAME),
        logging.getLogger(UVICORN_ERROR_LOGGER_NAME),
    ]
    saved = [(lg, list(lg.handlers), list(lg.filters), lg.level) for lg in loggers]

    setup_uvicorn_logger(log_level=logging.INFO)
    formatter: logging.Formatter = (
        get_json_formatter()
        if request.param == "json"
        else ColoredFormatter("%(message)s")
    )
    access = _add_capture_handler(UVICORN_ACCESS_LOGGER_NAME, formatter)
    error = _add_capture_handler(UVICORN_ERROR_LOGGER_NAME, formatter)
    logging.getLogger(UVICORN_ERROR_LOGGER_NAME).setLevel(logging.INFO)

    uvicorn_server = uvicorn.Server(
        uvicorn.Config(_app, host="127.0.0.1", port=0, log_config=None, lifespan="off")
    )
    thread = threading.Thread(target=uvicorn_server.run, daemon=True)
    thread.start()
    deadline = time.monotonic() + 10
    while not uvicorn_server.started:
        assert time.monotonic() < deadline, "uvicorn did not start"
        time.sleep(0.01)
    port = uvicorn_server.servers[0].sockets[0].getsockname()[1]

    yield _Capture(port, access, error)

    uvicorn_server.should_exit = True
    thread.join(10)
    for lg, handlers, filters, level in saved:
        lg.handlers = handlers
        lg.filters = filters
        lg.setLevel(level)


def _send_raw_request(port: int, target: str) -> None:
    with socket.create_connection(("127.0.0.1", port), timeout=5) as sock:
        sock.sendall(
            f"GET {target} HTTP/1.1\r\nHost: onyx.test\r\nConnection: close\r\n\r\n".encode()
        )
        while sock.recv(4096):
            pass


@pytest.mark.parametrize("callback_path", CALLBACK_PATHS)
def test_callback_query_values_are_dropped(
    server: _Capture, callback_path: str
) -> None:
    _send_raw_request(
        server.port, f"{callback_path}?code={SECRET_CODE}&state={SECRET_STATE}"
    )

    output = server.access.getvalue()
    assert SECRET_CODE not in output
    assert SECRET_STATE not in output
    assert f"GET {callback_path} HTTP/1.1" in output
    assert "302" in output


def test_absolute_form_request_target_query_is_dropped(server: _Capture) -> None:
    _send_raw_request(
        server.port, f"http://onyx.test/auth/oidc/callback?code={SECRET_CODE}"
    )

    output = server.access.getvalue()
    assert SECRET_CODE not in output
    assert "onyx.test/auth/oidc/callback HTTP/1.1" in output


def test_saml_redirect_binding_response_is_dropped(server: _Capture) -> None:
    _send_raw_request(
        server.port, "/auth/saml/callback?SAMLResponse=PHNhbWw%2BU0VDUkVU&RelayState=x"
    )

    output = server.access.getvalue()
    assert "PHNhbWw" not in output
    assert "/auth/saml/callback HTTP/1.1" in output


def test_websocket_handshake_token_is_dropped(server: _Capture) -> None:
    with websocket_connect(
        f"ws://127.0.0.1:{server.port}/voice/transcribe?token=WS-SECRET"
    ):
        pass

    output = server.error.getvalue()
    assert "WS-SECRET" not in output
    assert "/voice/transcribe" in output


def test_path_without_query_string_is_unchanged(server: _Capture) -> None:
    _send_raw_request(server.port, "/api/persona/42")

    assert "GET /api/persona/42 HTTP/1.1" in server.access.getvalue()


def test_json_record_keeps_request_id_field() -> None:
    record = logging.LogRecord(
        UVICORN_ACCESS_LOGGER_NAME, logging.INFO, __file__, 1, "%s", ("/x",), None
    )
    record.request_id = "req-abc123"

    assert json.loads(get_json_formatter().format(record))["request_id"] == "req-abc123"


@pytest.mark.parametrize(
    "arg, expected",
    [
        ("/auth/callback?code=x", "/auth/callback"),
        ("http%3A//host/auth/callback?code=x", "http%3A//host/auth/callback"),
        ("//host/path?code=x", "//host/path"),
        ("/no/query", "/no/query"),
        ("why? because/reasons", "why? because/reasons"),
        ("127.0.0.1:51234", "127.0.0.1:51234"),
        (302, 302),
    ],
)
def test_strip_query_string_from_path(arg: object, expected: object) -> None:
    assert _strip_query_string_from_path(arg) == expected
