"""Tests for the tenant work-gating Redis helpers.

Requires a running Redis instance. Run with::

    python -m dotenv -f .vscode/.env run -- pytest \
        backend/tests/external_dependency_unit/tenant_work_gating/test_tenant_work_gating.py
"""

import time
from collections.abc import Generator
from unittest.mock import patch

import pytest

from onyx.configs.constants import ONYX_CLOUD_TENANT_ID
from onyx.redis import redis_tenant_work_gating as twg
from onyx.redis.redis_pool import get_redis_client
from onyx.redis.redis_tenant_work_gating import _SET_KEY
from onyx.redis.redis_tenant_work_gating import cleanup_expired
from onyx.redis.redis_tenant_work_gating import get_active_tenants
from onyx.redis.redis_tenant_work_gating import mark_tenant_active


@pytest.fixture(autouse=True)
def _multi_tenant_true() -> Generator[None, None, None]:
    """Force MULTI_TENANT=True for the helper module so public functions are
    not no-ops during tests."""
    with patch.object(twg, "MULTI_TENANT", True):
        yield


@pytest.fixture(autouse=True)
def _clean_set() -> Generator[None, None, None]:
    """Clear the active_tenants sorted set before and after each test."""
    client = get_redis_client(tenant_id=ONYX_CLOUD_TENANT_ID)
    client.delete(_SET_KEY)
    yield
    client.delete(_SET_KEY)


def test_mark_adds_tenant_to_set() -> None:
    mark_tenant_active("tenant_a")

    assert get_active_tenants(ttl_seconds=60) == {"tenant_a"}


def test_mark_refreshes_timestamp() -> None:
    """ZADD overwrites the score on existing members. Without a refresh,
    reading with a TTL that excludes the first write should return empty;
    after a second mark_tenant_active at a newer timestamp, the same TTL
    read should include the tenant. Pins `_now_ms` so the test is
    deterministic."""
    base_ms = int(time.time() * 1000)

    # First write at t=0.
    with patch.object(twg, "_now_ms", return_value=base_ms):
        mark_tenant_active("tenant_a")

    # Read 5s later with a 1s TTL — first write is outside the window.
    with patch.object(twg, "_now_ms", return_value=base_ms + 5000):
        assert get_active_tenants(ttl_seconds=1) == set()

    # Refresh at t=5s.
    with patch.object(twg, "_now_ms", return_value=base_ms + 5000):
        mark_tenant_active("tenant_a")

    # Read at t=5s with a 1s TTL — refreshed write is inside the window.
    with patch.object(twg, "_now_ms", return_value=base_ms + 5000):
        assert get_active_tenants(ttl_seconds=1) == {"tenant_a"}


def test_get_active_tenants_filters_by_ttl() -> None:
    """Tenant marked in the past, read with a TTL short enough to exclude it."""
    # Pin _now_ms so the write happens at t=0 and the read cutoff is
    # well after that.
    base_ms = int(time.time() * 1000)
    with patch.object(twg, "_now_ms", return_value=base_ms):
        mark_tenant_active("tenant_old")

    # Read 5 seconds later with a 1-second TTL — tenant_old is outside.
    with patch.object(twg, "_now_ms", return_value=base_ms + 5000):
        assert get_active_tenants(ttl_seconds=1) == set()

    # Read 5 seconds later with a 10-second TTL — tenant_old is inside.
    with patch.object(twg, "_now_ms", return_value=base_ms + 5000):
        assert get_active_tenants(ttl_seconds=10) == {"tenant_old"}


def test_get_active_tenants_multiple_members() -> None:
    mark_tenant_active("tenant_a")
    mark_tenant_active("tenant_b")
    mark_tenant_active("tenant_c")

    assert get_active_tenants(ttl_seconds=60) == {"tenant_a", "tenant_b", "tenant_c"}


def test_get_active_tenants_empty_set() -> None:
    """Genuinely-empty set returns an empty set (not None)."""
    assert get_active_tenants(ttl_seconds=60) == set()


def test_get_active_tenants_returns_none_on_redis_error() -> None:
    """Callers need to distinguish Redis failure from "no tenants active" so
    they can fail open. Simulate failure by patching the client to raise."""
    from unittest.mock import MagicMock

    failing_client = MagicMock()
    failing_client.zrangebyscore.side_effect = RuntimeError("simulated outage")

    with patch.object(twg, "_client", return_value=failing_client):
        assert get_active_tenants(ttl_seconds=60) is None


def test_get_active_tenants_returns_none_in_single_tenant_mode() -> None:
    """Single-tenant mode returns None so callers can skip the gate entirely
    (same fail-open handling as Redis unavailability)."""
    with patch.object(twg, "MULTI_TENANT", False):
        assert get_active_tenants(ttl_seconds=60) is None


def test_cleanup_expired_removes_only_stale_members() -> None:
    """Seed one stale and one fresh member directly; cleanup should drop only
    the stale one."""
    now_ms = int(time.time() * 1000)

    client = get_redis_client(tenant_id=ONYX_CLOUD_TENANT_ID)
    client.zadd(_SET_KEY, mapping={"tenant_old": now_ms - 10 * 60 * 1000})
    client.zadd(_SET_KEY, mapping={"tenant_new": now_ms})

    removed = cleanup_expired(ttl_seconds=60)

    assert removed == 1
    assert get_active_tenants(ttl_seconds=60 * 60) == {"tenant_new"}


def test_cleanup_expired_empty_set_noop() -> None:
    assert cleanup_expired(ttl_seconds=60) == 0


def test_noop_when_multi_tenant_false() -> None:
    with patch.object(twg, "MULTI_TENANT", False):
        mark_tenant_active("tenant_a")
        assert get_active_tenants(ttl_seconds=60) is None
        assert cleanup_expired(ttl_seconds=60) == 0

    # Verify nothing was written while MULTI_TENANT was False.
    assert get_active_tenants(ttl_seconds=60) == set()


def test_rendered_key_is_cloud_prefixed() -> None:
    """Exercises TenantRedis auto-prefixing on sorted-set ops. The rendered
    Redis key should be `cloud:active_tenants`, not bare `active_tenants`."""
    mark_tenant_active("tenant_a")

    from onyx.redis.redis_pool import RedisPool

    raw = RedisPool().get_raw_client()
    assert raw.zscore("cloud:active_tenants", "tenant_a") is not None
    assert raw.zscore("active_tenants", "tenant_a") is None
