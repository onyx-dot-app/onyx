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

# Module-level singletons — these are lightweight objects (no connections or DB
# state) until configure() / set_redis_factory() is called. Keeping them at
# module level ensures they survive the lifetime of the worker process and are
# only registered with the Prometheus registry once.
_queue_collector = QueueDepthCollector()
_attempt_collector = IndexAttemptCollector()
_connector_collector = ConnectorHealthCollector()


def _make_broker_redis_factory(celery_app: Celery) -> Callable[[], Redis]:
    """Create a factory that returns a cached broker Redis client.

    Reuses a single connection across scrapes to avoid leaking connections.
    Reconnects automatically if the cached connection becomes stale.
    """
    _cached_client: list[Redis | None] = [None]

    def _close_client(client: Redis) -> None:
        """Best-effort close of a Redis client."""
        try:
            client.close()
        except Exception:
            logger.debug("Failed to close stale Redis client", exc_info=True)

    def _get_broker_redis() -> Redis:
        client = _cached_client[0]
        if client is not None:
            try:
                client.ping()
                return client
            except Exception:
                logger.debug("Cached Redis client stale, reconnecting")
                _close_client(client)
                _cached_client[0] = None

        # Get a fresh Redis client from the broker connection.
        # We hold this client long-term (cached above) rather than using a
        # context manager, because we need it to persist across scrapes.
        # The caching logic above ensures we only ever hold one connection,
        # and we close it explicitly on reconnect.
        conn = celery_app.broker_connection()
        # kombu's Channel exposes .client at runtime (the underlying Redis
        # client) but the type stubs don't declare it.
        new_client: Redis = conn.channel().client  # type: ignore[attr-defined]
        _cached_client[0] = new_client
        return new_client

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
            logger.debug("Collector already registered: %s", type(collector).__name__)
