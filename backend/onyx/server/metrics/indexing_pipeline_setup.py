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
from onyx.server.metrics.indexing_pipeline import RedisHealthCollector
from onyx.server.metrics.indexing_pipeline import WorkerHealthCollector
from onyx.server.metrics.indexing_pipeline import WorkerHeartbeatMonitor
from onyx.utils.logger import setup_logger

logger = setup_logger()

# Module-level singletons — these are lightweight objects (no connections or DB
# state) until configure() / set_redis_factory() is called. Keeping them at
# module level ensures they survive the lifetime of the worker process and are
# only registered with the Prometheus registry once.
_queue_collector = QueueDepthCollector()
_attempt_collector = IndexAttemptCollector()
_connector_collector = ConnectorHealthCollector()
_redis_health_collector = RedisHealthCollector()
_worker_health_collector = WorkerHealthCollector()
_heartbeat_monitor: WorkerHeartbeatMonitor | None = None


def _make_broker_redis_factory(celery_app: Celery) -> Callable[[], Redis]:
    """Create a factory that returns a shared broker Redis client.

    Delegates to celery_get_broker_client() which maintains a module-level
    singleton connected directly to the broker DB.
    """
    from onyx.background.celery.celery_redis import celery_get_broker_client

    def _get_broker_redis() -> Redis:
        return celery_get_broker_client(celery_app)

    return _get_broker_redis


def setup_indexing_pipeline_metrics(celery_app: Celery) -> None:
    """Register all indexing pipeline collectors with the default registry.

    Args:
        celery_app: The Celery application instance. Used to obtain a fresh
            broker Redis client on each scrape for queue depth metrics.
    """
    redis_factory = _make_broker_redis_factory(celery_app)
    _queue_collector.set_redis_factory(redis_factory)
    _redis_health_collector.set_redis_factory(redis_factory)

    # Start the heartbeat monitor daemon thread — uses a single persistent
    # connection to receive worker-heartbeat events.
    # Module-level singleton prevents duplicate threads on re-entry.
    global _heartbeat_monitor
    if _heartbeat_monitor is None:
        _heartbeat_monitor = WorkerHeartbeatMonitor(celery_app)
        _heartbeat_monitor.start()
    _worker_health_collector.set_monitor(_heartbeat_monitor)

    _attempt_collector.configure()
    _connector_collector.configure()

    for collector in (
        _queue_collector,
        _attempt_collector,
        _connector_collector,
        _redis_health_collector,
        _worker_health_collector,
    ):
        try:
            REGISTRY.register(collector)
        except ValueError:
            logger.debug("Collector already registered: %s", type(collector).__name__)
