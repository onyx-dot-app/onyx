"""Socket deadlines on the app Redis client are opt-in and reach every pool."""

from collections.abc import Mapping
from contextlib import ExitStack
from typing import Any
from unittest.mock import MagicMock, patch

import onyx.background.celery.celery_redis as celery_redis
import onyx.redis.redis_pool as redis_pool

_DEADLINES = {"socket_timeout": 30.0, "socket_connect_timeout": 10.0}


def _direct_pool_patches(stack: ExitStack) -> None:
    stack.enter_context(patch.object(redis_pool, "REDIS_SENTINEL_HOSTS", []))
    stack.enter_context(patch.object(redis_pool, "USE_REDIS_IAM_AUTH", False))
    stack.enter_context(patch.object(redis_pool, "REDIS_SSL", False))


def _every_connection_kwargs(stack: ExitStack) -> list[Mapping[str, Any]]:
    pool_cls = stack.enter_context(
        patch.object(redis_pool.redis, "BlockingConnectionPool")
    )
    aioredis = stack.enter_context(patch.object(redis_pool, "aioredis"))
    connection_kwargs, sentinel_kwargs = redis_pool._sentinel_connection_kwargs()
    redis_pool.RedisPool.create_pool(ssl=False)
    redis_pool._build_async_redis_connection()
    return [
        connection_kwargs,
        sentinel_kwargs,
        pool_cls.call_args.kwargs,
        aioredis.Redis.call_args.kwargs,
    ]


def test_unset_deadlines_leave_every_pool_on_library_defaults() -> None:
    with ExitStack() as stack:
        stack.enter_context(patch.object(redis_pool, "REDIS_SOCKET_TIMEOUT_KWARGS", {}))
        _direct_pool_patches(stack)
        for kwargs in _every_connection_kwargs(stack):
            assert "socket_timeout" not in kwargs
            assert "socket_connect_timeout" not in kwargs


def test_deadlines_apply_to_sentinel_direct_and_async_connections() -> None:
    with ExitStack() as stack:
        stack.enter_context(
            patch.object(redis_pool, "REDIS_SOCKET_TIMEOUT_KWARGS", _DEADLINES)
        )
        _direct_pool_patches(stack)
        # The sentinel nodes get the deadlines too: a hung sentinel would
        # otherwise stall master discovery on every new connection.
        for kwargs in _every_connection_kwargs(stack):
            assert kwargs["socket_timeout"] == 30.0
            assert kwargs["socket_connect_timeout"] == 10.0


def test_deadlines_apply_to_the_broker_client() -> None:
    app = MagicMock()
    app.conf.broker_url = "redis://broker:6379/15"
    with (
        patch.object(celery_redis, "REDIS_SOCKET_TIMEOUT_KWARGS", _DEADLINES),
        patch.object(celery_redis, "_broker_client", None),
        patch.object(celery_redis, "Redis") as redis_cls,
    ):
        celery_redis.celery_get_broker_client(app)
        kwargs = redis_cls.from_url.call_args.kwargs
    assert kwargs["socket_timeout"] == 30.0
    assert kwargs["socket_connect_timeout"] == 10.0
