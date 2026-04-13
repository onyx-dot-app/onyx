"""Tests for indexing pipeline setup."""

from unittest.mock import MagicMock

from onyx.server.metrics.indexing_pipeline import QueueDepthCollector
from onyx.server.metrics.indexing_pipeline import RedisHealthCollector


class TestCollectorCeleryAppSetup:
    def test_queue_depth_collector_uses_celery_app(self) -> None:
        """QueueDepthCollector.set_celery_app stores the app for broker access."""
        collector = QueueDepthCollector()
        mock_app = MagicMock()
        collector.set_celery_app(mock_app)
        assert collector._celery_app is mock_app

    def test_redis_health_collector_uses_celery_app(self) -> None:
        """RedisHealthCollector.set_celery_app stores the app for broker access."""
        collector = RedisHealthCollector()
        mock_app = MagicMock()
        collector.set_celery_app(mock_app)
        assert collector._celery_app is mock_app
