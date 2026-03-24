"""Setup function for indexing pipeline Prometheus collectors.

Called once by the monitoring celery worker after Redis and DB are ready.
"""

from collections.abc import Callable

from celery import Celery
from prometheus_client.registry import REGISTRY
from redis import Redis

from onyx.server.metrics.indexing_pipeline import ConnectorHealthCollector
from onyx.server.metrics.indexing_pipeline import IndexAttemptCollector
from onyx.server.metrics.indexing_pipeline import QueueDepthCollector
from onyx.utils.logger import setup_logger

logger = setup_logger()

# Module-level singletons so collectors survive the lifetime of the worker
_queue_collector = QueueDepthCollector()
_attempt_collector = IndexAttemptCollector()
_connector_collector = ConnectorHealthCollector()


def _make_broker_redis_factory(celery_app: Celery) -> Callable[[], Redis]:
    """Create a factory that returns a fresh broker Redis client on each call.

    Using a factory instead of a stored reference avoids holding a stale
    connection if the broker reconnects or the channel is recycled.
    """

    def _get_broker_redis() -> Redis:
        return celery_app.broker_connection().channel().client  # type: ignore

    return _get_broker_redis


def setup_indexing_pipeline_metrics(celery_app: Celery) -> None:
    """Register all indexing pipeline collectors with the default registry.

    Args:
        celery_app: The Celery application instance. Used to obtain a fresh
            broker Redis client on each scrape for queue depth metrics.
    """
    _queue_collector.set_redis_factory(_make_broker_redis_factory(celery_app))
    _attempt_collector.configure()
    _connector_collector.configure()

    for collector in (_queue_collector, _attempt_collector, _connector_collector):
        try:
            REGISTRY.register(collector)
        except ValueError:
            pass  # already registered (e.g. during tests or hot reload)
