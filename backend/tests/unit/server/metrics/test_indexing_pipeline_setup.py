"""Tests for indexing pipeline setup (Redis factory caching)."""

from unittest.mock import MagicMock

from onyx.server.metrics.indexing_pipeline_setup import _make_broker_redis_factory


class TestMakeBrokerRedisFactory:
    def test_caches_redis_client_across_calls(self) -> None:
        """Factory should reuse the same client on subsequent calls."""
        mock_app = MagicMock()
        mock_client = MagicMock()
        mock_client.ping.return_value = True
        mock_app.broker_connection.return_value.channel.return_value.client = (
            mock_client
        )

        factory = _make_broker_redis_factory(mock_app)

        client1 = factory()
        client2 = factory()

        assert client1 is client2
        # broker_connection should only be called once
        assert mock_app.broker_connection.call_count == 1

    def test_reconnects_when_ping_fails(self) -> None:
        """Factory should create a new client if ping fails (stale connection)."""
        mock_app = MagicMock()
        mock_client_stale = MagicMock()
        mock_client_stale.ping.side_effect = ConnectionError("disconnected")

        mock_client_fresh = MagicMock()
        mock_client_fresh.ping.return_value = True

        # First call returns stale client, second returns fresh
        mock_app.broker_connection.return_value.channel.return_value.client = (
            mock_client_stale
        )

        factory = _make_broker_redis_factory(mock_app)

        # First call — creates and caches
        client1 = factory()
        assert client1 is mock_client_stale
        assert mock_app.broker_connection.call_count == 1

        # Switch to fresh client for next broker_connection call
        mock_app.broker_connection.return_value.channel.return_value.client = (
            mock_client_fresh
        )

        # Second call — ping fails on stale, reconnects
        client2 = factory()
        assert client2 is mock_client_fresh
        assert mock_app.broker_connection.call_count == 2

    def test_first_call_creates_connection(self) -> None:
        """First call should always create a new connection."""
        mock_app = MagicMock()
        mock_client = MagicMock()
        mock_app.broker_connection.return_value.channel.return_value.client = (
            mock_client
        )

        factory = _make_broker_redis_factory(mock_app)
        client = factory()

        assert client is mock_client
        mock_app.broker_connection.assert_called_once()
