"""Unit tests for Redis connection pool metrics collector."""

from unittest.mock import MagicMock

from onyx.server.metrics.redis_connection_pool import RedisPoolCollector


def test_redis_pool_collector_reports_metrics() -> None:
    """Verify the collector reads pool internals correctly."""
    mock_pool = MagicMock()
    mock_pool._in_use_connections = {"conn1", "conn2", "conn3"}
    mock_pool._available_connections = ["conn4", "conn5"]
    mock_pool.max_connections = 128
    mock_pool._created_connections = 5

    collector = RedisPoolCollector()
    collector.add_pool("primary", mock_pool)

    families = collector.collect()
    assert len(families) == 4

    metrics: dict[str, float] = {}
    for family in families:
        for sample in family.samples:
            metrics[f"{sample.name}:{sample.labels['pool']}"] = sample.value

    assert metrics["onyx_redis_pool_in_use:primary"] == 3
    assert metrics["onyx_redis_pool_available:primary"] == 2
    assert metrics["onyx_redis_pool_max:primary"] == 128
    assert metrics["onyx_redis_pool_created:primary"] == 5


def test_redis_pool_collector_handles_multiple_pools() -> None:
    """Verify the collector supports primary + replica pools."""
    primary = MagicMock()
    primary._in_use_connections = {"a"}
    primary._available_connections = ["b", "c"]
    primary.max_connections = 128
    primary._created_connections = 3

    replica = MagicMock()
    replica._in_use_connections = set()
    replica._available_connections = ["d"]
    replica.max_connections = 64
    replica._created_connections = 1

    collector = RedisPoolCollector()
    collector.add_pool("primary", primary)
    collector.add_pool("replica", replica)

    families = collector.collect()
    metrics: dict[str, float] = {}
    for family in families:
        for sample in family.samples:
            metrics[f"{sample.name}:{sample.labels['pool']}"] = sample.value

    assert metrics["onyx_redis_pool_in_use:primary"] == 1
    assert metrics["onyx_redis_pool_in_use:replica"] == 0
    assert metrics["onyx_redis_pool_max:replica"] == 64


def test_redis_pool_collector_falls_back_to_zeros_on_attribute_error() -> None:
    """Verify collector degrades gracefully when redis-py internals change."""
    mock_pool = MagicMock(spec=[])  # empty spec — no attributes at all
    collector = RedisPoolCollector()
    collector.add_pool("primary", mock_pool)

    families = collector.collect()
    assert len(families) == 4

    metrics: dict[str, float] = {}
    for family in families:
        for sample in family.samples:
            metrics[f"{sample.name}:{sample.labels['pool']}"] = sample.value

    # All metrics should fall back to zero
    assert metrics["onyx_redis_pool_in_use:primary"] == 0
    assert metrics["onyx_redis_pool_available:primary"] == 0
    assert metrics["onyx_redis_pool_max:primary"] == 0
    assert metrics["onyx_redis_pool_created:primary"] == 0


def test_redis_pool_collector_describe_returns_empty() -> None:
    """Unchecked collector pattern — describe() returns empty."""
    collector = RedisPoolCollector()
    assert collector.describe() == []
