"""Pooled Redis clients retry connection errors, but not timeouts."""

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from typing import Any
from unittest.mock import patch
from uuid import uuid4

import pytest
import redis
from redis.connection import Connection
from redis.exceptions import BusyLoadingError
from redis.exceptions import ConnectionError as RedisConnectionError
from redis.exceptions import TimeoutError as RedisTimeoutError

from onyx.redis.redis_pool import RedisPool


@contextmanager
def _fail_first_send(error: Exception) -> Iterator[list[int]]:
    """Raise *error* on the first command sent, then send normally."""
    calls: list[int] = []
    send: Callable[..., Any] = Connection.send_packed_command

    def flaky_send(self: Connection, *args: Any, **kwargs: Any) -> Any:
        calls.append(1)
        if len(calls) == 1:
            raise error
        return send(self, *args, **kwargs)

    with patch.object(Connection, "send_packed_command", flaky_send):
        yield calls


def _connected_client(operation_timeout: float | None = None) -> redis.Redis:
    """Return a client whose pooled connection is open, so faults hit commands."""
    client = redis.Redis(
        connection_pool=RedisPool.create_pool(operation_timeout=operation_timeout)
    )
    client.ping()
    return client


@pytest.fixture
def key() -> Iterator[str]:
    key = f"retry-test:{uuid4()}"
    yield key
    redis.Redis(connection_pool=RedisPool.create_pool()).delete(key)


@pytest.mark.parametrize(
    "error", [RedisConnectionError("reset"), BusyLoadingError("loading")]
)
def test_default_pool_retries_connection_errors(error: Exception, key: str) -> None:
    client = _connected_client()
    with _fail_first_send(error):
        client.set(key, b"value")
    assert client.get(key) == b"value"


def test_default_pool_does_not_retry_timeouts(key: str) -> None:
    client = _connected_client()
    with _fail_first_send(RedisTimeoutError("slow")), pytest.raises(RedisTimeoutError):
        client.set(key, b"value")
    assert client.get(key) is None


def test_timeout_pool_does_not_retry(key: str) -> None:
    client = _connected_client(operation_timeout=1)
    with (
        _fail_first_send(RedisConnectionError("reset")) as calls,
        pytest.raises(RedisConnectionError),
    ):
        client.set(key, b"value")
    assert len(calls) == 1
