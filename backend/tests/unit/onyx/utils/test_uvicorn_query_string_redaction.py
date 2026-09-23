import io
import json
import logging
from collections.abc import Generator

import pytest

from onyx.utils.logger import ColoredFormatter, get_json_formatter, setup_uvicorn_logger
from shared_configs.contextvars import ONYX_REQUEST_ID_CONTEXTVAR

UVICORN_ACCESS_FORMAT = '%s - "%s %s HTTP/%s" %d'
UVICORN_WEBSOCKET_FORMAT = '%s - "WebSocket %s" [accepted]'
TEXT_FORMAT = "%(asctime)s %(filename)30s %(lineno)4s: [%(request_id)s] %(message)s"
REQUEST_ID = "req-abc123"
SECRET_VALUES = ("SECRET-CODE-VALUE", "SECRET-STATE-VALUE")

CALLBACK_PATHS = [
    "/auth/oidc/callback",
    "/auth/oidc/okta/callback",
    "/auth/oauth/callback",
    "/connector/oauth/callback/slack",
    "/manage/connector/gmail/callback",
]


@pytest.fixture(autouse=True)
def _restore_uvicorn_loggers() -> Generator[None, None, None]:
    loggers = [logging.getLogger("uvicorn.access"), logging.getLogger("uvicorn.error")]
    saved = [
        (logger, list(logger.handlers), list(logger.filters), logger.level)
        for logger in loggers
    ]
    request_id_token = ONYX_REQUEST_ID_CONTEXTVAR.set(REQUEST_ID)
    yield
    ONYX_REQUEST_ID_CONTEXTVAR.reset(request_id_token)
    for logger, handlers, filters, level in saved:
        logger.handlers = handlers
        logger.filters = filters
        logger.setLevel(level)


def _capture(logger_name: str, formatter: logging.Formatter) -> io.StringIO:
    setup_uvicorn_logger(log_level=logging.INFO)
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.setFormatter(formatter)
    logger = logging.getLogger(logger_name)
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    return stream


def _log_access_line(path: str, status: int = 302) -> None:
    logging.getLogger("uvicorn.access").info(
        UVICORN_ACCESS_FORMAT, "10.0.0.1:51234", "GET", path, "1.1", status
    )


@pytest.mark.parametrize("callback_path", CALLBACK_PATHS)
def test_text_access_log_drops_callback_query_values(callback_path: str) -> None:
    stream = _capture("uvicorn.access", ColoredFormatter(TEXT_FORMAT))

    _log_access_line(
        f"{callback_path}?code={SECRET_VALUES[0]}&state={SECRET_VALUES[1]}&next=/chat"
    )

    output = stream.getvalue()
    for secret in SECRET_VALUES:
        assert secret not in output
    assert "code=" not in output
    assert "?" not in output
    assert f'"GET {callback_path} HTTP/1.1" 302' in output
    assert f"[{REQUEST_ID}]" in output


def test_json_access_log_drops_callback_query_values() -> None:
    stream = _capture("uvicorn.access", get_json_formatter())

    _log_access_line(
        f"/auth/oidc/callback?code={SECRET_VALUES[0]}&state={SECRET_VALUES[1]}"
    )

    raw_output = stream.getvalue()
    for secret in SECRET_VALUES:
        assert secret not in raw_output
    record = json.loads(raw_output)
    assert (
        record["message"] == '10.0.0.1:51234 - "GET /auth/oidc/callback HTTP/1.1" 302'
    )
    assert record["request_id"] == REQUEST_ID
    assert record["logger"] == "uvicorn.access"


def test_saml_redirect_binding_response_is_dropped() -> None:
    stream = _capture("uvicorn.access", get_json_formatter())

    _log_access_line("/auth/saml/callback?SAMLResponse=PHNhbWw%2BU0VDUkVU&RelayState=x")

    output = stream.getvalue()
    assert "SAMLResponse" not in output
    assert "PHNhbWw" not in output
    assert "/auth/saml/callback HTTP/1.1" in output


def test_websocket_handshake_token_is_dropped() -> None:
    stream = _capture("uvicorn.error", ColoredFormatter("%(message)s"))

    logging.getLogger("uvicorn.error").info(
        UVICORN_WEBSOCKET_FORMAT, "10.0.0.1:51234", "/voice/transcribe?token=WS-SECRET"
    )

    output = stream.getvalue()
    assert "WS-SECRET" not in output
    assert '"WebSocket /voice/transcribe" [accepted]' in output


def test_path_without_query_string_is_unchanged() -> None:
    stream = _capture("uvicorn.access", ColoredFormatter("%(message)s"))

    _log_access_line("/api/persona/42", status=200)

    assert '10.0.0.1:51234 - "GET /api/persona/42 HTTP/1.1" 200' in stream.getvalue()


def test_non_path_args_with_question_marks_are_unchanged() -> None:
    stream = _capture("uvicorn.error", ColoredFormatter("%(message)s"))

    logging.getLogger("uvicorn.error").info(
        "Invalid HTTP request received: %s", "why? because=reasons"
    )

    assert "why? because=reasons" in stream.getvalue()
