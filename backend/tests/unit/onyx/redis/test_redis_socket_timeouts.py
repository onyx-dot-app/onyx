"""Socket deadlines on the app Redis client default on and reach every pool."""

import importlib
import os
from collections.abc import Mapping
from contextlib import ExitStack
from typing import Any
from unittest.mock import MagicMock, patch

import onyx.background.celery.celery_redis as celery_redis
import onyx.configs.app_configs as app_configs
import onyx.redis.redis_pool as redis_pool

_DEADLINES = {"socket_timeout": 30.0, "socket_connect_timeout": 10.0}


def test_defaults_are_thirty_second_read_and_ten_second_connect() -> None:
    env = {k: v for k, v in os.environ.items() if not k.startswith("REDIS_SOCKET_")}
    try:
        with patch.dict(os.environ, env, clear=True):
            importlib.reload(app_configs)
            assert app_configs.REDIS_SOCKET_TIMEOUT_KWARGS == _DEADLINES
        with patch.dict(os.environ, {"REDIS_SOCKET_TIMEOUT": "5", **env}, clear=True):
            importlib.reload(app_configs)
            assert app_configs.REDIS_SOCKET_TIMEOUT_KWARGS["socket_timeout"] == 5.0
    finally:
        importlib.reload(app_configs)


def _every_connection_kwargs(stack: ExitStack) -> list[Mapping[str, Any]]:
    stack.enter_context(patch.object(redis_pool, "REDIS_SENTINEL_HOSTS", []))
    stack.enter_context(patch.object(redis_pool, "USE_REDIS_IAM_AUTH", False))
    stack.enter_context(patch.object(redis_pool, "REDIS_SSL", False))
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


def test_deadlines_apply_to_sentinel_direct_and_async_connections() -> None:
    with ExitStack() as stack:
        stack.enter_context(
            patch.object(redis_pool, "REDIS_SOCKET_TIMEOUT_KWARGS", _DEADLINES)
        )
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


def test_timeout_pools_are_reused_without_changing_default_pool() -> None:
    from concurrent.futures import ThreadPoolExecutor

    with (
        patch.object(redis_pool.RedisPool, "_instance", None),
        patch.object(redis_pool.RedisPool, "create_pool") as create_pool,
        patch.object(redis_pool.redis, "Redis") as redis_client,
    ):
        pool = redis_pool.RedisPool()
        default_pool = pool._pool
        create_pool.reset_mock()
        with ThreadPoolExecutor(max_workers=4) as executor:
            clients = list(
                executor.map(
                    lambda _: pool.get_client("tenant", operation_timeout_s=0.5),
                    range(8),
                )
            )
        assert len(clients) == 8
        create_pool.assert_called_once_with(
            ssl=redis_pool.REDIS_SSL, operation_timeout=0.5
        )
        pool.get_client("tenant", operation_timeout_s=2)
        assert create_pool.call_count == 2
        pool.get_client("tenant")
        assert redis_client.call_args.kwargs["connection_pool"] is default_pool


def test_sentinel_retries_apply_to_data_connections_only() -> None:
    with (
        patch.object(redis_pool, "REDIS_SENTINEL_HOSTS", [("sentinel", 26379)]),
        patch.object(redis_pool, "Sentinel") as sentinel_cls,
    ):
        redis_pool.RedisPool.create_pool()
        kwargs = sentinel_cls.call_args.kwargs
        assert kwargs["retry_on_error"] == [redis_pool.BusyLoadingError]
        assert "retry" not in kwargs["sentinel_kwargs"]

        redis_pool.RedisPool.create_pool(operation_timeout=1)
        assert "retry" not in sentinel_cls.call_args.kwargs
