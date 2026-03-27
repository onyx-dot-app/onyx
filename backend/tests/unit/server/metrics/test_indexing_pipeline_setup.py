"""Tests for indexing pipeline setup (broker Redis factory)."""

from unittest.mock import MagicMock
from unittest.mock import patch

from onyx.server.metrics.indexing_pipeline_setup import _make_broker_redis_factory


class TestMakeBrokerRedisFactory:
    @patch(
        "onyx.background.celery.celery_redis.celery_get_broker_client",
        wraps=None,
    )
    def test_delegates_to_singleton(self, mock_get_client: MagicMock) -> None:
        """Factory should delegate to celery_get_broker_client."""
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client

        mock_app = MagicMock()
        factory = _make_broker_redis_factory(mock_app)

        result = factory()

        assert result is mock_client
        mock_get_client.assert_called_once_with(mock_app)

    @patch(
        "onyx.background.celery.celery_redis.celery_get_broker_client",
        wraps=None,
    )
    def test_passes_app_on_each_call(self, mock_get_client: MagicMock) -> None:
        """Factory should pass the app on every call."""
        mock_get_client.return_value = MagicMock()

        mock_app = MagicMock()
        factory = _make_broker_redis_factory(mock_app)

        factory()
        factory()

        assert mock_get_client.call_count == 2
        for call in mock_get_client.call_args_list:
            assert call[0][0] is mock_app
