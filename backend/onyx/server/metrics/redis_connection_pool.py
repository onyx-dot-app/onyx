"""Redis connection pool Prometheus collector.

Reads pool internals from redis.BlockingConnectionPool on each
Prometheus scrape to report utilization metrics.

Metrics:
- onyx_redis_pool_in_use: Currently checked-out connections
- onyx_redis_pool_available: Idle connections in the pool
- onyx_redis_pool_max: Configured max_connections
- onyx_redis_pool_created: Lifetime connections created
"""

from prometheus_client.core import GaugeMetricFamily
from prometheus_client.registry import Collector
from prometheus_client.registry import REGISTRY
from redis import BlockingConnectionPool

from onyx.utils.logger import setup_logger

logger = setup_logger()


class RedisPoolCollector(Collector):
    """Custom collector that reads BlockingConnectionPool internals on scrape.

    NOTE: Uses private redis-py attributes (_in_use_connections,
    _available_connections, _created_connections) because there is no
    public API for pool statistics. Wrapped in try/except so a redis-py
    upgrade changing internals degrades gracefully (metrics go to 0)
    instead of crashing every scrape.
    """

    def __init__(self) -> None:
        self._pools: list[tuple[str, BlockingConnectionPool]] = []

    def add_pool(self, label: str, pool: BlockingConnectionPool) -> None:
        self._pools.append((label, pool))

    def collect(self) -> list[GaugeMetricFamily]:
        in_use = GaugeMetricFamily(
            "onyx_redis_pool_in_use",
            "Currently checked-out Redis connections",
            labels=["pool"],
        )
        available = GaugeMetricFamily(
            "onyx_redis_pool_available",
            "Idle Redis connections in the pool",
            labels=["pool"],
        )
        max_conns = GaugeMetricFamily(
            "onyx_redis_pool_max",
            "Configured max Redis connections",
            labels=["pool"],
        )
        created = GaugeMetricFamily(
            "onyx_redis_pool_created",
            "Lifetime Redis connections created",
            labels=["pool"],
        )

        for label, pool in self._pools:
            try:
                in_use.add_metric([label], len(pool._in_use_connections))
                available.add_metric([label], len(pool._available_connections))
                max_conns.add_metric([label], pool.max_connections)
                created.add_metric([label], pool._created_connections)
            except (AttributeError, TypeError):
                # Degrade to zeros so the time series stays visible
                # instead of disappearing when internals change.
                in_use.add_metric([label], 0)
                available.add_metric([label], 0)
                max_conns.add_metric([label], 0)
                created.add_metric([label], 0)
                logger.warning(
                    "Redis pool %s: falling back to zero metrics — "
                    "redis-py internals may have changed",
                    label,
                    exc_info=True,
                )

        return [in_use, available, max_conns, created]

    def describe(self) -> list[GaugeMetricFamily]:
        return []


_redis_collector: RedisPoolCollector | None = None


def setup_redis_connection_pool_metrics() -> None:
    """Register Redis pool metrics using the RedisPool singleton.

    Idempotent — safe to call multiple times (e.g. Uvicorn hot-reload).
    """
    global _redis_collector
    if _redis_collector is not None:
        return

    from onyx.redis.redis_pool import RedisPool

    pool_instance = RedisPool()
    collector = RedisPoolCollector()
    collector.add_pool("primary", pool_instance._pool)
    # Replica pool always exists (defaults to same host as primary when
    # REDIS_REPLICA_HOST is not set). Still worth monitoring separately
    # since it maintains an independent connection pool.
    collector.add_pool("replica", pool_instance._replica_pool)

    REGISTRY.register(collector)
    _redis_collector = collector
    logger.info("Registered Redis connection pool metrics")
