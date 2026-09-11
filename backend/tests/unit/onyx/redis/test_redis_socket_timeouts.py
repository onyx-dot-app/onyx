"""Socket deadlines on the app Redis client are opt-in and reach every pool."""

from contextlib import ExitStack
from unittest.mock import patch

import onyx.redis.redis_pool as redis_pool


def _direct_pool_patches(stack: ExitStack) -> None:
    stack.enter_context(patch.object(redis_pool, "REDIS_SENTINEL_HOSTS", []))
    stack.enter_context(patch.object(redis_pool, "USE_REDIS_IAM_AUTH", False))
    stack.enter_context(patch.object(redis_pool, "REDIS_SSL", False))


def test_unset_deadlines_leave_every_pool_on_library_defaults() -> None:
    with ExitStack() as stack:
        stack.enter_context(patch.object(redis_pool, "REDIS_SOCKET_TIMEOUT", None))
        stack.enter_context(
            patch.object(redis_pool, "REDIS_SOCKET_CONNECT_TIMEOUT", None)
        )
        _direct_pool_patches(stack)
        pool_cls = stack.enter_context(
            patch.object(redis_pool.redis, "BlockingConnectionPool")
        )
        aioredis = stack.enter_context(patch.object(redis_pool, "aioredis"))

        connection_kwargs, sentinel_kwargs = redis_pool._sentinel_connection_kwargs()
        redis_pool.RedisPool.create_pool(ssl=False)
        redis_pool._build_async_redis_connection()

        for kwargs in (
            connection_kwargs,
            sentinel_kwargs,
            pool_cls.call_args.kwargs,
            aioredis.Redis.call_args.kwargs,
        ):
            assert "socket_timeout" not in kwargs
            assert "socket_connect_timeout" not in kwargs


def test_deadlines_apply_to_sentinel_direct_and_async_connections() -> None:
    with ExitStack() as stack:
        stack.enter_context(patch.object(redis_pool, "REDIS_SOCKET_TIMEOUT", 30.0))
        stack.enter_context(
            patch.object(redis_pool, "REDIS_SOCKET_CONNECT_TIMEOUT", 10.0)
        )
        _direct_pool_patches(stack)
        pool_cls = stack.enter_context(
            patch.object(redis_pool.redis, "BlockingConnectionPool")
        )
        aioredis = stack.enter_context(patch.object(redis_pool, "aioredis"))

        connection_kwargs, sentinel_kwargs = redis_pool._sentinel_connection_kwargs()
        redis_pool.RedisPool.create_pool(ssl=False)
        redis_pool._build_async_redis_connection()

        # The sentinel nodes get the deadlines too: a hung sentinel would
        # otherwise stall master discovery on every new connection.
        for kwargs in (
            connection_kwargs,
            sentinel_kwargs,
            pool_cls.call_args.kwargs,
            aioredis.Redis.call_args.kwargs,
        ):
            assert kwargs["socket_timeout"] == 30.0
            assert kwargs["socket_connect_timeout"] == 10.0
