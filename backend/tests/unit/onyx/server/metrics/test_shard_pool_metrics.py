"""Shard engines must export pool metrics.

Pool metrics were registered once at startup for the default shard's engines
only, so every lazily-created shard engine's pool was invisible — the
Grafana connection-pool dashboard went dark when sharding rolled out.
"""

from collections.abc import Generator
from unittest.mock import MagicMock

import pytest
from prometheus_client.core import GaugeMetricFamily
from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.ext.asyncio import AsyncEngine
from sqlalchemy.pool import QueuePool

import onyx.db.engine.async_sql_engine as async_sql_engine
import onyx.db.engine.shard_registry as shard_registry
import onyx.server.metrics.postgres_connection_pool as pool_metrics


def _make_engine() -> Engine:
    return create_engine("sqlite://", poolclass=QueuePool)


def _make_async_engine() -> AsyncEngine:
    # aiosqlite is not a dependency; a spec'd mock over a real sync engine
    # exercises the same AsyncEngine-resolution path in the collector.
    engine = MagicMock(spec=AsyncEngine)
    engine.sync_engine = _make_engine()
    return engine


def _gauge_labels(metric_name: str) -> set[str]:
    families: list[GaugeMetricFamily] = pool_metrics._collector.collect()
    for family in families:
        if family.name == metric_name:
            return {sample.labels["engine"] for sample in family.samples}
    return set()


@pytest.fixture
def clean_metrics_state(
    monkeypatch: pytest.MonkeyPatch,
) -> Generator[None, None, None]:
    monkeypatch.setattr(pool_metrics, "_collector", pool_metrics.PoolStateCollector())
    monkeypatch.setattr(pool_metrics, "_registered_labels", set())
    # The hooks are stable singletons imported by value elsewhere; isolate by
    # clearing their subscriber lists, never by replacing the objects.
    monkeypatch.setattr(shard_registry.shard_engine_hooks, "_callbacks", [])
    monkeypatch.setattr(async_sql_engine.async_engine_hooks, "_callbacks", [])
    # setup() registers the collector with the global REGISTRY; undo after.
    yield
    try:
        pool_metrics.REGISTRY.unregister(pool_metrics._collector)
    except KeyError:
        pass


@pytest.mark.usefixtures("clean_metrics_state")
def test_existing_shard_engines_register_at_setup(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    shard_engine = _make_engine()
    monkeypatch.setattr(shard_registry.ShardRegistry, "_engines", {"s1": shard_engine})

    pool_metrics.setup_postgres_connection_pool_metrics(
        engines={"sync": _make_engine()}
    )

    assert _gauge_labels("onyx_db_pool_checked_out") == {"sync", "sync_s1"}


@pytest.mark.usefixtures("clean_metrics_state")
def test_shard_engines_created_later_register_too(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(shard_registry.ShardRegistry, "_engines", {})
    pool_metrics.setup_postgres_connection_pool_metrics(
        engines={"sync": _make_engine()}
    )
    assert _gauge_labels("onyx_db_pool_checked_out") == {"sync"}

    shard_registry.shard_engine_hooks.notify("s2", _make_engine())

    assert _gauge_labels("onyx_db_pool_checked_out") == {"sync", "sync_s2"}


@pytest.mark.usefixtures("clean_metrics_state")
def test_default_async_shard_keeps_its_historical_label(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(shard_registry.ShardRegistry, "_engines", {})
    pool_metrics.setup_postgres_connection_pool_metrics(
        engines={"async": _make_engine()}
    )

    default = shard_registry.get_default_shard_name()
    # The default async engine registers under "async" via setup(); the
    # creation hook must not add a duplicate "async_<default>" series.
    async_sql_engine.async_engine_hooks.notify(default, _make_async_engine())
    async_sql_engine.async_engine_hooks.notify("s3", _make_async_engine())

    assert _gauge_labels("onyx_db_pool_checked_out") == {"async", "async_s3"}
