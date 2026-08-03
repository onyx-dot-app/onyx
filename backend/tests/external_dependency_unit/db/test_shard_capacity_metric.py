"""The per-shard tenant count that drives the capacity alert.

Counted against two real databases, because the value has to reflect where schemas
physically live — a mapping that disagrees with reality must not be able to hide
capacity from the alert.
"""

from collections.abc import Generator
from typing import Any
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import OperationalError

from onyx.db.engine import shard_registry, shard_routing, tenant_utils
from onyx.db.engine.shard_registry import get_engine_for_shard
from onyx.db.engine.shard_routing import invalidate_shard_cache
from onyx.db.engine.sql_engine import SYNC_DB_API, SqlEngine, build_connection_string
from onyx.server.metrics import shard_capacity
from onyx.server.metrics.shard_capacity import ShardCapacityCollector

DEFAULT_SHARD = "default"
SECOND_SHARD = "shard-test-b"


def _admin_engine() -> Engine:
    return create_engine(
        build_connection_string(db_api=SYNC_DB_API, db="postgres"),
        isolation_level="AUTOCOMMIT",
    )


def _counts(collector: ShardCapacityCollector) -> dict[str, float]:
    """Sample the collector directly rather than through the global registry."""
    return {
        sample.labels["shard"]: sample.value
        for metric in collector.collect()
        for sample in metric.samples
    }


@pytest.fixture(scope="module")
def second_database() -> Generator[str, None, None]:
    db_name = f"onyx_capacity_test_{uuid4().hex[:8]}"
    admin = _admin_engine()
    with admin.connect() as conn:
        conn.execute(text(f'CREATE DATABASE "{db_name}"'))
    try:
        yield db_name
    finally:
        with admin.connect() as conn:
            conn.execute(
                text(
                    "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                    "WHERE datname = :db AND pid <> pg_backend_pid()"
                ),
                {"db": db_name},
            )
            conn.execute(text(f'DROP DATABASE IF EXISTS "{db_name}"'))
        admin.dispose()


@pytest.fixture(scope="function")
def two_shards(
    second_database: str, monkeypatch: pytest.MonkeyPatch
) -> Generator[dict[str, Any], None, None]:
    SqlEngine.init_engine(pool_size=5, max_overflow=2)

    shards_json = f'{{"{SECOND_SHARD}": {{"db": "{second_database}"}}}}'
    monkeypatch.setattr(shard_registry, "ONYX_DB_SHARDS_JSON", shards_json)
    monkeypatch.setattr(shard_registry, "ONYX_DB_DEFAULT_SHARD", DEFAULT_SHARD)
    monkeypatch.setattr(shard_registry, "ONYX_DB_CATALOG_SHARD", DEFAULT_SHARD)
    monkeypatch.setattr(shard_routing, "MULTI_TENANT", True)
    monkeypatch.setattr(shard_capacity, "MULTI_TENANT", True)
    # Enumeration short-circuits to a single fake tenant outside multi-tenant mode.
    monkeypatch.setattr(tenant_utils, "MULTI_TENANT", True)

    shard_registry.reset_shard_specs()
    shard_routing.reset_shard_overrides()
    invalidate_shard_cache()

    created: list[tuple[str, str]] = []
    yield {"created": created}

    for shard, tenant_id in created:
        with get_engine_for_shard(shard).connect() as conn:
            conn.execute(text(f'DROP SCHEMA IF EXISTS "{tenant_id}" CASCADE'))
            conn.commit()
    shard_registry.reset_shard_specs()
    invalidate_shard_cache()


def _make_tenant(two_shards: dict[str, Any], shard: str) -> str:
    tenant_id = f"tenant_{uuid4()}"
    with get_engine_for_shard(shard).connect() as conn:
        conn.execute(text(f'CREATE SCHEMA IF NOT EXISTS "{tenant_id}"'))
        conn.commit()
    two_shards["created"].append((shard, tenant_id))
    return tenant_id


def test_counts_are_reported_per_shard(two_shards: dict[str, Any]) -> None:
    """Each shard reports the schemas physically on it, not what a catalog claims."""
    collector = ShardCapacityCollector()
    before = _counts(collector)

    _make_tenant(two_shards, DEFAULT_SHARD)
    _make_tenant(two_shards, SECOND_SHARD)
    _make_tenant(two_shards, SECOND_SHARD)

    # A fresh collector, since the previous one has the pre-change counts cached.
    after = _counts(ShardCapacityCollector())

    assert after[DEFAULT_SHARD] == before.get(DEFAULT_SHARD, 0) + 1
    assert after[SECOND_SHARD] == before.get(SECOND_SHARD, 0) + 2


def test_every_replica_reports_without_coordination(
    two_shards: dict[str, Any],  # noqa: ARG001
) -> None:
    """Collected on scrape precisely so each monitoring replica is self-sufficient.

    A beat task reaches one worker, so only that replica would hold a value and
    replacing it would blank the series until the next run.
    """
    first = _counts(ShardCapacityCollector())
    second = _counts(ShardCapacityCollector())

    assert first == second
    assert set(first) == {DEFAULT_SHARD, SECOND_SHARD}


def test_an_unreachable_shard_does_not_suppress_the_others(
    two_shards: dict[str, Any],  # noqa: ARG001
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """One database outage must not blank capacity data for unrelated shards.

    The *first* shard collected is the one made to fail: shards are walked in sorted
    order, so a version that aborts the whole loop still reports everything ahead of
    the failure and would pass otherwise.
    """

    def _count(shard_name: str) -> int:
        if shard_name == DEFAULT_SHARD:
            raise OperationalError("SELECT 1", {}, Exception("connection refused"))
        return 7

    monkeypatch.setattr(shard_capacity, "count_tenant_schemas_on_shard", _count)

    assert sorted(shard_registry.get_shard_specs())[0] == DEFAULT_SHARD
    counts = _counts(ShardCapacityCollector())

    assert counts == {SECOND_SHARD: 7}


def test_no_series_outside_multi_tenant_mode(
    two_shards: dict[str, Any],  # noqa: ARG001
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Single-database deployments have no shards to report on."""
    monkeypatch.setattr(shard_capacity, "MULTI_TENANT", False)
    assert _counts(ShardCapacityCollector()) == {}
