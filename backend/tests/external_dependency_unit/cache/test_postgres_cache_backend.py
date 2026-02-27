"""Tests for PostgresCacheBackend against real PostgreSQL.

Covers every method on the backend: KV CRUD, TTL behaviour, advisory
locks (acquire / release / contention), list operations (rpush / blpop),
and the periodic cleanup function.
"""

import time
from uuid import uuid4

from onyx.cache.postgres_backend import cleanup_expired_cache_entries
from onyx.cache.postgres_backend import PostgresCacheBackend


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

    def test_set_overwrite(self, pg_cache: PostgresCacheBackend) -> None:
        k = _key()
        pg_cache.set(k, b"first")
        pg_cache.set(k, b"second")
        assert pg_cache.get(k) == b"second"

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
        assert pg_cache.ttl(k) == -1

    def test_ttl_missing_key(self, pg_cache: PostgresCacheBackend) -> None:
        assert pg_cache.ttl(_key()) == -2

    def test_ttl_remaining(self, pg_cache: PostgresCacheBackend) -> None:
        k = _key()
        pg_cache.set(k, b"x", ex=10)
        remaining = pg_cache.ttl(k)
        assert 8 <= remaining <= 10

    def test_ttl_expired_key(self, pg_cache: PostgresCacheBackend) -> None:
        k = _key()
        pg_cache.set(k, b"x", ex=1)
        time.sleep(1.5)
        assert pg_cache.ttl(k) == -2

    def test_expire_adds_ttl(self, pg_cache: PostgresCacheBackend) -> None:
        k = _key()
        pg_cache.set(k, b"x")
        assert pg_cache.ttl(k) == -1
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
        k = _key()
        pg_cache.set(k, b"stale", ex=1)
        time.sleep(1.5)
        cleanup_expired_cache_entries()
        assert pg_cache.ttl(k) == -2

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
