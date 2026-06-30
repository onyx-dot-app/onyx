"""Drive/Gmail paginated retrieval must retry transient connection drops
(broken pipe, reset, SSL teardown, timeout) instead of letting one dropped
socket fail the whole crawl."""

import socket
import ssl
from collections.abc import Callable

import pytest

from onyx.connectors.google_utils.google_utils import _execute_single_retrieval


class _Request:
    def __init__(self, execute_fn: Callable[[], dict]) -> None:
        self._execute_fn = execute_fn

    def execute(self) -> dict:
        return self._execute_fn()


@pytest.mark.parametrize(
    "transient_error",
    [
        BrokenPipeError(32, "Broken pipe"),
        ConnectionResetError("connection reset by peer"),
        ssl.SSLError("decryption failed or bad record mac"),
        socket.timeout("timed out"),
    ],
)
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

    result = _execute_single_retrieval(retrieval_function)

    assert result == {"files": [{"id": "ok"}]}
    assert attempts["count"] == 2  # failed once, retried, succeeded
