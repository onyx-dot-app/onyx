"""Tests for PostgresCacheBackend against real PostgreSQL.

Covers every method on the backend: KV CRUD, TTL behaviour, advisory
locks (acquire / release / contention), list operations (rpush / blpop),
and the periodic cleanup function.
"""

import math
import time
from uuid import uuid4

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import OperationalError

from onyx.cache import factory as cache_factory
from onyx.cache.factory import get_cache_backend
from onyx.cache.interface import TTL_KEY_NOT_FOUND, TTL_NO_EXPIRY, CacheBackendType
from onyx.cache.postgres_backend import (
    PostgresCacheBackend,
    PostgresCacheLock,
    cleanup_expired_cache_entries,
)
from onyx.db.engine.sql_engine import get_session_with_tenant
from onyx.db.models import CacheStore
from shared_configs.configs import POSTGRES_DEFAULT_SCHEMA_STANDARD_VALUE


def _key() -> str:
    return f"test_{uuid4().hex[:12]}"


# ------------------------------------------------------------------
# Basic KV
# ------------------------------------------------------------------


class TestKV:
    def test_get_set(self, pg_cache: PostgresCacheBackend) -> None:
        k = _key()
        pg_cache.set(k, b"hello")
        assert pg_cache.get(k) == b"hello"

    def test_get_missing(self, pg_cache: PostgresCacheBackend) -> None:
        assert pg_cache.get(_key()) is None

    def test_getdel_is_one_time(self, pg_cache: PostgresCacheBackend) -> None:
        k = _key()
        pg_cache.set(k, b"one-time")

        assert pg_cache.getdel(k) == b"one-time"
        assert pg_cache.getdel(k) is None

    def test_getdel_rejects_expired_value(self, pg_cache: PostgresCacheBackend) -> None:
        k = _key()
        pg_cache.set(k, b"expired", ex=0)

        assert pg_cache.getdel(k) is None

    def test_set_overwrite(self, pg_cache: PostgresCacheBackend) -> None:
        k = _key()
        pg_cache.set(k, b"first")
        pg_cache.set(k, b"second")
        assert pg_cache.get(k) == b"second"

    def test_set_if_absent_does_not_overwrite(
        self, pg_cache: PostgresCacheBackend
    ) -> None:
        k = _key()

        assert pg_cache.set_if_absent(k, b"first", ex=10)
        assert not pg_cache.set_if_absent(k, b"second", ex=10)
        assert pg_cache.get(k) == b"first"

    def test_set_if_absent_replaces_expired_value(
        self, pg_cache: PostgresCacheBackend
    ) -> None:
        k = _key()
        pg_cache.set(k, b"expired", ex=0)

        assert pg_cache.set_if_absent(k, b"replacement", ex=10)
        assert pg_cache.get(k) == b"replacement"

    def test_set_string_value(self, pg_cache: PostgresCacheBackend) -> None:
        k = _key()
        pg_cache.set(k, "string_val")
        assert pg_cache.get(k) == b"string_val"

    def test_set_int_value(self, pg_cache: PostgresCacheBackend) -> None:
        k = _key()
        pg_cache.set(k, 42)
        assert pg_cache.get(k) == b"42"

    def test_delete(self, pg_cache: PostgresCacheBackend) -> None:
        k = _key()
        pg_cache.set(k, b"to_delete")
        pg_cache.delete(k)
        assert pg_cache.get(k) is None

    def test_delete_missing_is_noop(self, pg_cache: PostgresCacheBackend) -> None:
        pg_cache.delete(_key())

    def test_exists(self, pg_cache: PostgresCacheBackend) -> None:
        k = _key()
        assert not pg_cache.exists(k)
        pg_cache.set(k, b"x")
        assert pg_cache.exists(k)


# ------------------------------------------------------------------
# TTL
# ------------------------------------------------------------------


class TestTTL:
    def test_set_with_ttl_expires(self, pg_cache: PostgresCacheBackend) -> None:
        k = _key()
        pg_cache.set(k, b"ephemeral", ex=1)
        assert pg_cache.get(k) == b"ephemeral"
        time.sleep(1.5)
        assert pg_cache.get(k) is None

    def test_ttl_no_expiry(self, pg_cache: PostgresCacheBackend) -> None:
        k = _key()
        pg_cache.set(k, b"forever")
        assert pg_cache.ttl(k) == TTL_NO_EXPIRY

    def test_ttl_missing_key(self, pg_cache: PostgresCacheBackend) -> None:
        assert pg_cache.ttl(_key()) == TTL_KEY_NOT_FOUND

    def test_ttl_remaining(self, pg_cache: PostgresCacheBackend) -> None:
        k = _key()
        pg_cache.set(k, b"x", ex=10)
        remaining = pg_cache.ttl(k)
        assert 8 <= remaining <= 10

    def test_ttl_expired_key(self, pg_cache: PostgresCacheBackend) -> None:
        k = _key()
        pg_cache.set(k, b"x", ex=1)
        time.sleep(1.5)
        assert pg_cache.ttl(k) == TTL_KEY_NOT_FOUND

    def test_expire_adds_ttl(self, pg_cache: PostgresCacheBackend) -> None:
        k = _key()
        pg_cache.set(k, b"x")
        assert pg_cache.ttl(k) == TTL_NO_EXPIRY
        pg_cache.expire(k, 10)
        assert 8 <= pg_cache.ttl(k) <= 10

    def test_exists_respects_ttl(self, pg_cache: PostgresCacheBackend) -> None:
        k = _key()
        pg_cache.set(k, b"x", ex=1)
        assert pg_cache.exists(k)
        time.sleep(1.5)
        assert not pg_cache.exists(k)


# ------------------------------------------------------------------
# Locks
# ------------------------------------------------------------------


class TestLock:
    def test_acquire_release(self, pg_cache: PostgresCacheBackend) -> None:
        lock = pg_cache.lock(f"lock_{uuid4().hex[:8]}")
        assert lock.acquire(blocking=False)
        assert lock.owned()
        lock.release()
        assert not lock.owned()

    def test_contention(self, pg_cache: PostgresCacheBackend) -> None:
        name = f"contention_{uuid4().hex[:8]}"
        lock1 = pg_cache.lock(name)
        lock2 = pg_cache.lock(name)

        assert lock1.acquire(blocking=False)
        assert not lock2.acquire(blocking=False)

        lock1.release()
        assert lock2.acquire(blocking=False)
        lock2.release()

    def test_context_manager(self, pg_cache: PostgresCacheBackend) -> None:
        with pg_cache.lock(f"ctx_{uuid4().hex[:8]}") as lock:
            assert lock.owned()
        assert not lock.owned()

    def test_blocking_timeout(self, pg_cache: PostgresCacheBackend) -> None:
        name = f"timeout_{uuid4().hex[:8]}"
        holder = pg_cache.lock(name)
        holder.acquire(blocking=False)

        waiter = pg_cache.lock(name, timeout=0.3)
        start = time.monotonic()
        assert not waiter.acquire(blocking=True, blocking_timeout=0.3)
        elapsed = time.monotonic() - start
        assert elapsed >= 0.25

        holder.release()


# ------------------------------------------------------------------
# List (rpush / blpop)
# ------------------------------------------------------------------


class TestList:
    def test_rpush_blpop(self, pg_cache: PostgresCacheBackend) -> None:
        k = f"list_{uuid4().hex[:8]}"
        pg_cache.rpush(k, b"item1")
        result = pg_cache.blpop([k], timeout=1)
        assert result is not None
        assert result == (k.encode(), b"item1")

    def test_blpop_timeout(self, pg_cache: PostgresCacheBackend) -> None:
        result = pg_cache.blpop([f"empty_{uuid4().hex[:8]}"], timeout=1)
        assert result is None

    def test_fifo_order(self, pg_cache: PostgresCacheBackend) -> None:
        k = f"fifo_{uuid4().hex[:8]}"
        pg_cache.rpush(k, b"first")
        time.sleep(0.01)
        pg_cache.rpush(k, b"second")

        r1 = pg_cache.blpop([k], timeout=1)
        r2 = pg_cache.blpop([k], timeout=1)
        assert r1 is not None and r1[1] == b"first"
        assert r2 is not None and r2[1] == b"second"

    def test_multiple_keys(self, pg_cache: PostgresCacheBackend) -> None:
        k1 = f"mk1_{uuid4().hex[:8]}"
        k2 = f"mk2_{uuid4().hex[:8]}"
        pg_cache.rpush(k2, b"from_k2")

        result = pg_cache.blpop([k1, k2], timeout=1)
        assert result is not None
        assert result == (k2.encode(), b"from_k2")


# ------------------------------------------------------------------
# Cleanup
# ------------------------------------------------------------------


class TestCleanup:
    def test_removes_expired_rows(self, pg_cache: PostgresCacheBackend) -> None:
        from onyx.db.engine.sql_engine import get_session_with_current_tenant

        k = _key()
        pg_cache.set(k, b"stale", ex=1)
        time.sleep(1.5)
        cleanup_expired_cache_entries()

        stmt = select(CacheStore.key).where(CacheStore.key == k)
        with get_session_with_current_tenant() as session:
            row = session.execute(stmt).first()
        assert row is None, "expired row should be physically deleted"

    def test_preserves_unexpired_rows(self, pg_cache: PostgresCacheBackend) -> None:
        k = _key()
        pg_cache.set(k, b"fresh", ex=300)
        cleanup_expired_cache_entries()
        assert pg_cache.get(k) == b"fresh"

    def test_preserves_no_ttl_rows(self, pg_cache: PostgresCacheBackend) -> None:
        k = _key()
        pg_cache.set(k, b"permanent")
        cleanup_expired_cache_entries()
        assert pg_cache.get(k) == b"permanent"


def test_statement_timeout_bounds_wait_on_a_locked_cache_row(
    pg_cache: PostgresCacheBackend,
) -> None:
    tenant_id = POSTGRES_DEFAULT_SCHEMA_STANDARD_VALUE
    bounded = PostgresCacheBackend(tenant_id, statement_timeout_ms=1000)
    key = _key()
    pg_cache.set(key, b"owner", ex=60)
    try:
        with get_session_with_tenant(tenant_id=tenant_id) as session:
            session.execute(
                select(CacheStore).where(CacheStore.key == key).with_for_update()
            )
            with pytest.raises(OperationalError, match="timeout"):
                bounded.expire(key, 120)
        bounded.expire(key, 120)
        assert bounded.ttl(key) > 60
    finally:
        pg_cache.delete(key)


@pytest.mark.parametrize("timeout", [0, -1, math.inf, math.nan])
def test_invalid_operation_timeout_is_rejected(timeout: float) -> None:
    with pytest.raises(ValueError, match="finite and positive"):
        get_cache_backend(operation_timeout_s=timeout)


@pytest.mark.parametrize(
    ("operation_timeout_s", "expected"),
    # Sub-millisecond values round up: a 0 ms timeout would disable it.
    [(1, "1s"), (0.0001, "1ms")],
)
def test_operation_timeout_applies_to_lock_session(
    monkeypatch: pytest.MonkeyPatch, operation_timeout_s: float, expected: str
) -> None:
    monkeypatch.setattr(cache_factory, "CACHE_BACKEND", CacheBackendType.POSTGRES)
    bounded = get_cache_backend(operation_timeout_s=operation_timeout_s)
    lock = bounded.lock(_key())
    assert isinstance(lock, PostgresCacheLock)
    assert lock.acquire(blocking=False)
    try:
        assert lock._session is not None
        for setting in ("statement_timeout", "lock_timeout"):
            value = lock._session.execute(text(f"SHOW {setting}")).scalar()
            assert value == expected
    finally:
        lock.release()


def test_control_lease_renewal_does_not_wait_for_a_locked_cache_row(
    pg_cache: PostgresCacheBackend,
) -> None:
    tenant_id = POSTGRES_DEFAULT_SCHEMA_STANDARD_VALUE
    control = PostgresCacheBackend(tenant_id, statement_timeout_ms=1000)
    key = _key()
    pg_cache.set(key, b"owner", ex=60)
    try:
        with get_session_with_tenant(tenant_id=tenant_id) as session:
            session.execute(
                select(CacheStore).where(CacheStore.key == key).with_for_update()
            )
            with pytest.raises(OperationalError, match="timeout"):
                control.expire_if_value(key, b"owner", 60)
        assert control.expire_if_value(key, b"owner", 60)
    finally:
        pg_cache.delete(key)
