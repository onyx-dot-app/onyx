"""Parameterized tests that run the same CacheBackend operations against
both Redis and PostgreSQL, asserting identical return values.

Each test runs twice (once per backend) via the ``cache`` fixture defined
in conftest.py.
"""

import time
from uuid import uuid4

from onyx.cache.interface import CacheBackend


def _key() -> str:
    return f"parity_{uuid4().hex[:12]}"


class TestKVParity:
    def test_get_missing(self, cache: CacheBackend) -> None:
        assert cache.get(_key()) is None

    def test_get_set(self, cache: CacheBackend) -> None:
        k = _key()
        cache.set(k, b"value")
        assert cache.get(k) == b"value"

    def test_overwrite(self, cache: CacheBackend) -> None:
        k = _key()
        cache.set(k, b"a")
        cache.set(k, b"b")
        assert cache.get(k) == b"b"

    def test_set_string(self, cache: CacheBackend) -> None:
        k = _key()
        cache.set(k, "hello")
        assert cache.get(k) == b"hello"

    def test_set_int(self, cache: CacheBackend) -> None:
        k = _key()
        cache.set(k, 42)
        assert cache.get(k) == b"42"

    def test_delete(self, cache: CacheBackend) -> None:
        k = _key()
        cache.set(k, b"x")
        cache.delete(k)
        assert cache.get(k) is None

    def test_exists(self, cache: CacheBackend) -> None:
        k = _key()
        assert not cache.exists(k)
        cache.set(k, b"x")
        assert cache.exists(k)


class TestTTLParity:
    def test_ttl_missing(self, cache: CacheBackend) -> None:
        assert cache.ttl(_key()) == -2

    def test_ttl_no_expiry(self, cache: CacheBackend) -> None:
        k = _key()
        cache.set(k, b"x")
        assert cache.ttl(k) == -1

    def test_ttl_remaining(self, cache: CacheBackend) -> None:
        k = _key()
        cache.set(k, b"x", ex=10)
        remaining = cache.ttl(k)
        assert 8 <= remaining <= 10

    def test_set_with_ttl_expires(self, cache: CacheBackend) -> None:
        k = _key()
        cache.set(k, b"x", ex=1)
        assert cache.get(k) == b"x"
        time.sleep(1.5)
        assert cache.get(k) is None


class TestLockParity:
    def test_acquire_release(self, cache: CacheBackend) -> None:
        lock = cache.lock(f"parity_lock_{uuid4().hex[:8]}")
        assert lock.acquire(blocking=False)
        assert lock.owned()
        lock.release()
        assert not lock.owned()


class TestListParity:
    def test_rpush_blpop(self, cache: CacheBackend) -> None:
        k = f"parity_list_{uuid4().hex[:8]}"
        cache.rpush(k, b"item")
        result = cache.blpop([k], timeout=1)
        assert result is not None
        assert result[1] == b"item"

    def test_blpop_timeout(self, cache: CacheBackend) -> None:
        result = cache.blpop([f"parity_empty_{uuid4().hex[:8]}"], timeout=1)
        assert result is None
