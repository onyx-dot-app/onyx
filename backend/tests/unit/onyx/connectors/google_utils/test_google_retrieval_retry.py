"""Drive/Gmail retrieval and access probes must retry transient connection
drops (broken pipe, reset, TLS EOF, timeout) instead of letting one dropped
socket fail the whole crawl, and must re-raise when the drop persists."""

import json
import socket
import ssl
from collections.abc import Callable

import httplib2
import pytest
from googleapiclient.errors import HttpError

from onyx.connectors.google_utils import google_utils


class _Request:
    def __init__(self, execute_fn: Callable[[], dict]) -> None:
        self._execute_fn = execute_fn

    def execute(self) -> dict:
        return self._execute_fn()


# tries of retry_transient_connection_errors
_PROBE_CONNECTION_TRIES = 5

_TRANSIENT_ERRORS = [
    BrokenPipeError(32, "Broken pipe"),
    ConnectionResetError("connection reset by peer"),
    ssl.SSLEOFError("EOF occurred in violation of protocol"),
    socket.timeout("timed out"),
]


@pytest.mark.parametrize("transient_error", _TRANSIENT_ERRORS)
def test_retrieval_retries_transient_connection_errors(
    transient_error: Exception,
) -> None:
    attempts = {"count": 0}

    def execute() -> dict:
        attempts["count"] += 1
        if attempts["count"] == 1:
            raise transient_error
        return {"files": [{"id": "ok"}]}

    def retrieval_function(**_kwargs: object) -> _Request:
        return _Request(execute)

    result = google_utils._execute_single_retrieval(retrieval_function)

    assert result == {"files": [{"id": "ok"}]}
    assert attempts["count"] == 2  # failed once, retried, succeeded


@pytest.mark.parametrize("transient_error", _TRANSIENT_ERRORS)
def test_retrieval_reraises_when_retries_exhausted(
    transient_error: Exception,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """If the drop persists across retries the error propagates, not swallowed."""

    # Stand in for add_retries with an instant (no-backoff) retry that re-raises,
    # matching tenacity's reraise=True without the real delay.
    def instant_retries(fn: Callable[[], dict]) -> Callable[[], dict]:
        def wrapper() -> dict:
            error: Exception | None = None
            for _ in range(3):
                try:
                    return fn()
                except Exception as exc:
                    error = exc
            assert error is not None
            raise error

        return wrapper

    monkeypatch.setattr(google_utils, "add_retries", instant_retries)

    def execute() -> dict:
        raise transient_error

    def retrieval_function(**_kwargs: object) -> _Request:
        return _Request(execute)

    with pytest.raises(type(transient_error)):
        google_utils._execute_single_retrieval(retrieval_function)


@pytest.mark.parametrize("transient_error", _TRANSIENT_ERRORS)
def test_access_probe_retries_transient_connection_errors(
    transient_error: Exception,
) -> None:
    attempts = {"count": 0}

    def execute() -> dict:
        attempts["count"] += 1
        if attempts["count"] == 1:
            raise transient_error
        return {"id": "drive"}

    assert google_utils.execute_access_probe(_Request(execute)) == {"id": "drive"}
    assert attempts["count"] == 2


@pytest.mark.parametrize("transient_error", _TRANSIENT_ERRORS)
def test_access_probe_reraises_when_retries_exhausted(
    transient_error: Exception,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The real retry wrapper, with only its sleep removed: the probe gives up
    after the configured tries and the original error escapes."""
    monkeypatch.setattr("tenacity.nap.time.sleep", lambda _seconds: None)
    attempts = {"count": 0}

    def execute() -> dict:
        attempts["count"] += 1
        raise transient_error

    with pytest.raises(type(transient_error)):
        google_utils.execute_access_probe(_Request(execute))
    assert attempts["count"] == _PROBE_CONNECTION_TRIES


def test_rate_limit_retry_waits_for_the_retry_after_header(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """httplib2 stores header names in lowercase. The retry must still find
    Retry-After, or it waits a full minute."""
    waits: list[float] = []
    monkeypatch.setattr(google_utils.time, "sleep", waits.append)
    response = httplib2.Response({"status": "429", "Retry-After": "2"})
    content = json.dumps(
        {"error": {"errors": [{"reason": "rateLimitExceeded"}], "code": 429}}
    ).encode()
    attempts = {"count": 0}

    def execute() -> dict:
        attempts["count"] += 1
        if attempts["count"] == 1:
            raise HttpError(response, content)
        return {"files": []}

    assert google_utils._execute_with_retry(_Request(execute)) == {"files": []}
    # The header value plus the 3 s buffer.
    assert waits == [5]
