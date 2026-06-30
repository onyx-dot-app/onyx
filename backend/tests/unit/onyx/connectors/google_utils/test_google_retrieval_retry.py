"""Drive/Gmail paginated retrieval must retry transient connection drops
(broken pipe, reset, TLS EOF, timeout) instead of letting one dropped socket
fail the whole crawl, and must re-raise when the drop persists."""

import socket
import ssl
from collections.abc import Callable

import pytest

from onyx.connectors.google_utils import google_utils


class _Request:
    def __init__(self, execute_fn: Callable[[], dict]) -> None:
        self._execute_fn = execute_fn

    def execute(self) -> dict:
        return self._execute_fn()


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
