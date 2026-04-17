"""Setup function for indexing pipeline Prometheus collectors.

Called once by the monitoring celery worker after Redis and DB are ready.
"""

from celery import Celery
from prometheus_client.registry import REGISTRY

from onyx.server.metrics.indexing_pipeline import QueueDepthCollector
from onyx.server.metrics.indexing_pipeline import RedisHealthCollector
from onyx.server.metrics.indexing_pipeline import WorkerHealthCollector
from onyx.server.metrics.indexing_pipeline import WorkerHeartbeatMonitor
from onyx.utils.logger import setup_logger

logger = setup_logger()

# Module-level singletons — these are lightweight objects (no connections or DB
# state) until configure() / set_celery_app() is called. Keeping them at
# module level ensures they survive the lifetime of the worker process and are
# only registered with the Prometheus registry once.
_queue_collector = QueueDepthCollector()
_redis_health_collector = RedisHealthCollector()
_worker_health_collector = WorkerHealthCollector()
_heartbeat_monitor: WorkerHeartbeatMonitor | None = None


def setup_indexing_pipeline_metrics(celery_app: Celery) -> None:
    """Register all indexing pipeline collectors with the default registry.

    Args:
        celery_app: The Celery application instance. Used to obtain a
            broker Redis client on each scrape for queue depth metrics.

    Note: connector health and index attempt metrics are push-based
    (see connector_health_metrics.py) and do not use collectors.
    """
    _queue_collector.set_celery_app(celery_app)
    _redis_health_collector.set_celery_app(celery_app)

    # Start the heartbeat monitor daemon thread — uses a single persistent
    # connection to receive worker-heartbeat events.
    # Module-level singleton prevents duplicate threads on re-entry.
    global _heartbeat_monitor
    if _heartbeat_monitor is None:
        _heartbeat_monitor = WorkerHeartbeatMonitor(celery_app)
        _heartbeat_monitor.start()
    _worker_health_collector.set_monitor(_heartbeat_monitor)

    for collector in (
        _queue_collector,
        _redis_health_collector,
        _worker_health_collector,
    ):
        try:
            REGISTRY.register(collector)
        except ValueError:
            logger.debug("Collector already registered: %s", type(collector).__name__)
