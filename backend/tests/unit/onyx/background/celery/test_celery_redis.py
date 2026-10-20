"""Tests for celery_get_broker_client singleton."""

from collections.abc import Iterator
from unittest.mock import MagicMock, patch

import pytest

from onyx.background.celery import celery_redis


@pytest.fixture(autouse=True)
def reset_singleton() -> Iterator[None]:
    """Reset the module-level singleton between tests."""
    celery_redis._broker_client = None
    celery_redis._broker_url = None
    yield
    celery_redis._broker_client = None
    celery_redis._broker_url = None


def _make_mock_app(broker_url: str = "redis://localhost:6379/15") -> MagicMock:
    app = MagicMock()
    app.conf.broker_url = broker_url
    return app


class TestCeleryGetBrokerClient:
    @patch("onyx.background.celery.celery_redis.Redis")
    def test_creates_client_on_first_call(self, mock_redis_cls: MagicMock) -> None:
        mock_client = MagicMock()
        mock_redis_cls.from_url.return_value = mock_client

        app = _make_mock_app()
        result = celery_redis.celery_get_broker_client(app)

        assert result is mock_client
        call_args = mock_redis_cls.from_url.call_args
        assert call_args[0][0] == "redis://localhost:6379/15"
        assert call_args[1]["decode_responses"] is False
        assert call_args[1]["socket_keepalive"] is True
        assert call_args[1]["retry_on_timeout"] is True

    @patch("onyx.background.celery.celery_redis.Redis")
    def test_reuses_cached_client(self, mock_redis_cls: MagicMock) -> None:
        mock_client = MagicMock()
        mock_client.ping.return_value = True
        mock_redis_cls.from_url.return_value = mock_client

        app = _make_mock_app()
        client1 = celery_redis.celery_get_broker_client(app)
        client2 = celery_redis.celery_get_broker_client(app)

        assert client1 is client2
        # from_url called only once
        assert mock_redis_cls.from_url.call_count == 1

    @patch("onyx.background.celery.celery_redis.Redis")
    def test_reconnects_on_ping_failure(self, mock_redis_cls: MagicMock) -> None:
        stale_client = MagicMock()
        stale_client.ping.side_effect = ConnectionError("disconnected")

        fresh_client = MagicMock()
        fresh_client.ping.return_value = True

        mock_redis_cls.from_url.side_effect = [stale_client, fresh_client]

        app = _make_mock_app()

        # First call creates stale_client
        client1 = celery_redis.celery_get_broker_client(app)
        assert client1 is stale_client

        # Second call: ping fails, creates fresh_client
        client2 = celery_redis.celery_get_broker_client(app)
        assert client2 is fresh_client
        assert mock_redis_cls.from_url.call_count == 2

    @patch("onyx.background.celery.celery_redis.Redis")
    def test_uses_broker_url_from_app_config(self, mock_redis_cls: MagicMock) -> None:
        mock_redis_cls.from_url.return_value = MagicMock()

        app = _make_mock_app("redis://custom-host:6380/3")
        celery_redis.celery_get_broker_client(app)

        call_args = mock_redis_cls.from_url.call_args
        assert call_args[0][0] == "redis://custom-host:6380/3"

    @patch("onyx.background.celery.celery_redis.RedisPool")
    @patch("onyx.background.celery.celery_redis.Redis")
    @patch(
        "onyx.background.celery.celery_redis.REDIS_SENTINEL_HOSTS",
        [("sentinel-1", 26379)],
    )
    def test_sentinel_broker_url_resolves_master_via_sentinel(
        self, mock_redis_cls: MagicMock, mock_redis_pool_cls: MagicMock
    ) -> None:
        sentinel_pool = MagicMock()
        mock_redis_pool_cls._create_sentinel_pool.return_value = sentinel_pool
        mock_client = MagicMock()
        mock_redis_cls.return_value = mock_client

        app = _make_mock_app(
            "sentinel://:pw@sentinel-1:26379/15;sentinel://:pw@sentinel-2:26379/15"
        )
        result = celery_redis.celery_get_broker_client(app)

        assert result is mock_client
        mock_redis_cls.from_url.assert_not_called()
        mock_redis_cls.assert_called_once_with(connection_pool=sentinel_pool)
        pool_kwargs = mock_redis_pool_cls._create_sentinel_pool.call_args.kwargs
        assert pool_kwargs["db"] == celery_redis.REDIS_DB_NUMBER_CELERY
        assert pool_kwargs["replica"] is False

    @patch("onyx.background.celery.celery_redis.RedisPool")
    @patch("onyx.background.celery.celery_redis.Redis")
    @patch(
        "onyx.background.celery.celery_redis.REDIS_SENTINEL_HOSTS",
        [("sentinel-1", 26379)],
    )
    def test_non_sentinel_url_uses_from_url_even_with_sentinel_hosts(
        self, mock_redis_cls: MagicMock, mock_redis_pool_cls: MagicMock
    ) -> None:
        mock_redis_cls.from_url.return_value = MagicMock()

        app = _make_mock_app("redis://override-host:6379/15")
        celery_redis.celery_get_broker_client(app)

        mock_redis_pool_cls._create_sentinel_pool.assert_not_called()
        assert (
            mock_redis_cls.from_url.call_args[0][0] == "redis://override-host:6379/15"
        )
