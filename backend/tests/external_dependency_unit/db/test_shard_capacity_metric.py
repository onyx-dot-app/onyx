"""The per-shard tenant count that drives the capacity alert.

Counted against two real databases, because the value has to reflect where schemas
physically live — a mapping that disagrees with reality must not be able to hide
capacity from the alert.
"""

import time
from collections.abc import Generator
from concurrent.futures import ThreadPoolExecutor
from typing import Any
from uuid import uuid4

import pytest
from sqlalchemy.exc import OperationalError

from onyx.db.engine import shard_registry, shard_routing, tenant_utils
from onyx.db.engine.shard_registry import get_engine_for_shard
from onyx.db.engine.shard_routing import invalidate_shard_cache
from onyx.db.engine.sql_engine import SqlEngine
from onyx.server.metrics import shard_capacity
from onyx.server.metrics.shard_capacity import ShardCapacityCollector
from tests.external_dependency_unit.db.shard_test_utils import (
    DEFAULT_SHARD,
    create_schema,
    drop_schema,
)

SECOND_SHARD = "shard-test-b"


def _counts(collector: ShardCapacityCollector) -> dict[str, float]:
    """Sample the collector directly rather than through the global registry."""
    return {
        sample.labels["shard"]: sample.value
        for metric in collector.collect()
        for sample in metric.samples
    }


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
        drop_schema(get_engine_for_shard(shard), tenant_id)
    shard_registry.reset_shard_specs()
    invalidate_shard_cache()


def _make_tenant(two_shards: dict[str, Any], shard: str) -> str:
    tenant_id = f"tenant_{uuid4()}"
    create_schema(get_engine_for_shard(shard), tenant_id)
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


def test_concurrent_scrapes_refresh_once(
    two_shards: dict[str, Any],  # noqa: ARG001
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Prometheus can scrape a replica while a refresh is in flight. Without the lock
    held across the scan, each scrape runs its own, and a slower older one can overwrite
    a newer result on the way out."""
    scans = 0

    def _count(shard_name: str) -> int:  # noqa: ARG001
        nonlocal scans
        scans += 1
        time.sleep(0.05)
        return 3

    monkeypatch.setattr(shard_capacity, "count_tenant_schemas_on_shard", _count)
    collector = ShardCapacityCollector()

    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(lambda _: _counts(collector), range(4)))

    # Two shards, scanned once each — not once per concurrent scrape.
    assert scans == 2
    assert all(r == results[0] for r in results)


def test_no_series_outside_multi_tenant_mode(
    two_shards: dict[str, Any],  # noqa: ARG001
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Single-database deployments have no shards to report on."""
    monkeypatch.setattr(shard_capacity, "MULTI_TENANT", False)
    assert _counts(ShardCapacityCollector()) == {}
