"""Tests for indexing pipeline setup (Redis factory caching)."""

from unittest.mock import MagicMock

from onyx.server.metrics.indexing_pipeline_setup import _make_broker_redis_factory


def _make_mock_app(client: MagicMock) -> MagicMock:
    """Create a mock Celery app whose connection_or_acquire context manager
    returns a connection with a channel that exposes the given client."""
    mock_app = MagicMock()
    mock_conn = MagicMock()
    mock_conn.channel.return_value.client = client

    # connection_or_acquire() returns a context manager
    mock_app.connection_or_acquire.return_value.__enter__ = MagicMock(
        return_value=mock_conn
    )
    mock_app.connection_or_acquire.return_value.__exit__ = MagicMock(return_value=False)

    return mock_app


class TestMakeBrokerRedisFactory:
    def test_caches_redis_client_across_calls(self) -> None:
        """Factory should reuse the same client on subsequent calls."""
        mock_client = MagicMock()
        mock_client.ping.return_value = True
        mock_app = _make_mock_app(mock_client)

        factory = _make_broker_redis_factory(mock_app)

        client1 = factory()
        client2 = factory()

        assert client1 is client2
        # connection_or_acquire should only be called once
        assert mock_app.connection_or_acquire.call_count == 1

    def test_reconnects_when_ping_fails(self) -> None:
        """Factory should create a new client if ping fails (stale connection)."""
        mock_client_stale = MagicMock()
        mock_client_stale.ping.side_effect = ConnectionError("disconnected")

        mock_client_fresh = MagicMock()
        mock_client_fresh.ping.return_value = True

        mock_app = _make_mock_app(mock_client_stale)

        factory = _make_broker_redis_factory(mock_app)

        # First call — creates and caches
        client1 = factory()
        assert client1 is mock_client_stale
        assert mock_app.connection_or_acquire.call_count == 1

        # Switch to fresh client for next connection
        mock_conn_fresh = MagicMock()
        mock_conn_fresh.channel.return_value.client = mock_client_fresh
        mock_app.connection_or_acquire.return_value.__enter__ = MagicMock(
            return_value=mock_conn_fresh
        )

        # Second call — ping fails on stale, reconnects
        client2 = factory()
        assert client2 is mock_client_fresh
        assert mock_app.connection_or_acquire.call_count == 2

    def test_reconnect_closes_stale_client(self) -> None:
        """When ping fails, the old client should be closed before reconnecting."""
        mock_client_stale = MagicMock()
        mock_client_stale.ping.side_effect = ConnectionError("disconnected")

        mock_client_fresh = MagicMock()
        mock_client_fresh.ping.return_value = True

        mock_app = _make_mock_app(mock_client_stale)

        factory = _make_broker_redis_factory(mock_app)

        # First call — creates and caches
        factory()

        # Switch to fresh client
        mock_conn_fresh = MagicMock()
        mock_conn_fresh.channel.return_value.client = mock_client_fresh
        mock_app.connection_or_acquire.return_value.__enter__ = MagicMock(
            return_value=mock_conn_fresh
        )

        # Second call — ping fails, should close stale client
        factory()
        mock_client_stale.close.assert_called_once()

    def test_first_call_creates_connection(self) -> None:
        """First call should always create a new connection."""
        mock_client = MagicMock()
        mock_app = _make_mock_app(mock_client)

        factory = _make_broker_redis_factory(mock_app)
        client = factory()

        assert client is mock_client
        mock_app.connection_or_acquire.assert_called_once()
