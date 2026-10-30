import builtins
import math
from collections.abc import Collection
from itertools import batched, islice

from redis.exceptions import LockNotOwnedError
from redis.lock import Lock as RedisLock

from onyx.cache.interface import CacheBackend, CacheLock, CacheLockLostError
from onyx.redis.tenant_redis_client import TenantRedisClient

_SCAN_BATCH_SIZE = 100
_EXISTS_BATCH_SIZE = 1000


class RedisCacheLock(CacheLock):
    """Wraps ``redis.lock.Lock`` behind the ``CacheLock`` interface."""

    def __init__(self, lock: RedisLock) -> None:
        self._lock = lock

    def acquire(
        self,
        blocking: bool = True,
        blocking_timeout: float | None = None,
    ) -> bool:
        return bool(
            self._lock.acquire(
                blocking=blocking,
                blocking_timeout=blocking_timeout,
            )
        )

    def release(self) -> None:
        try:
            self._lock.release()
        except LockNotOwnedError as error:
            raise CacheLockLostError(str(error)) from error

    def extend(self, ttl_seconds: float) -> None:
        try:
            # redis-py extend takes int seconds; ceil so the lease is never shortened.
            self._lock.extend(math.ceil(ttl_seconds), replace_ttl=True)
        except LockNotOwnedError as e:
            raise CacheLockLostError(str(e)) from e

    def owned(self) -> bool:
        return bool(self._lock.owned())


class RedisCacheBackend(CacheBackend):
    """``CacheBackend`` implementation that delegates to a tenant Redis client.

    ``TenantRedisClient`` applies the tenant prefix to every command and pipeline.
    """

    def __init__(self, redis_client: TenantRedisClient) -> None:
        self._r = redis_client

    # -- basic key/value ---------------------------------------------------

    def get(self, key: str) -> bytes | None:
        return self._r.get(key)

    def getdel(self, key: str) -> bytes | None:
        return self._r.getdel(key)

    def set(
        self,
        key: str,
        value: str | bytes | int | float,
        ex: int | None = None,
    ) -> None:
        self._r.set(key, value, ex=ex)

    def set_if_absent(
        self,
        key: str,
        value: str | bytes | int | float,
        ex: int | None = None,
    ) -> bool:
        return bool(self._r.set(key, value, ex=ex, nx=True))

    def delete(self, key: str) -> None:
        self._r.delete(key)

    def delete_prefix(self, prefix: str) -> None:
        if not prefix:
            raise ValueError("Cache deletion requires a nonempty prefix")
        pattern = (
            "".join("\\" + char if char in "\\*?[]" else char for char in prefix) + "*"
        )
        batch: list[bytes] = []
        for key in self._r.scan_iter(match=pattern, count=_SCAN_BATCH_SIZE):
            batch.append(key)
            if len(batch) == _SCAN_BATCH_SIZE:
                self._r.delete(*batch)
                batch.clear()
        if batch:
            self._r.delete(*batch)

    def exists(self, key: str) -> bool:
        return bool(self._r.exists(key))

    def exists_many(self, keys: Collection[str]) -> builtins.set[str]:
        existing: set[str] = set()
        for names in batched(keys, _EXISTS_BATCH_SIZE, strict=False):
            with self._r.pipeline(transaction=False) as pipeline:
                for name in names:
                    pipeline.exists(name)
                results = pipeline.execute()
            existing.update(
                name for name, exists in zip(names, results, strict=True) if exists
            )
        return existing

    def set_add(self, key: str, member: str | bytes) -> None:
        self._r.sadd(key, member)

    def set_remove(self, key: str, member: str | bytes) -> None:
        self._r.srem(key, member)

    def set_members(self, key: str, *, limit: int) -> list[bytes]:
        if limit < 1:
            raise ValueError("Cache set member limit must be positive")
        return list(islice(self._r.sscan_iter(key, count=_SCAN_BATCH_SIZE), limit))

    # -- TTL ---------------------------------------------------------------

    def expire(self, key: str, seconds: int) -> None:
        self._r.expire(key, seconds)

    def renew_if_value(self, key: str, expected: bytes, seconds: int) -> bool:
        return self._r.renew_if_value(key, expected, seconds)

    def ttl(self, key: str) -> int:
        return self._r.ttl(key)

    # -- distributed lock --------------------------------------------------

    def lock(self, name: str, timeout: float | None = None) -> CacheLock:
        return RedisCacheLock(self._r.lock(name, timeout=timeout, thread_local=False))

    # -- blocking list (MCP OAuth BLPOP pattern) ---------------------------

    def rpush(self, key: str, value: str | bytes) -> None:
        self._r.rpush(key, value)

    def blpop(self, keys: list[str], timeout: int = 0) -> tuple[bytes, bytes] | None:
        return self._r.blpop(keys, timeout=timeout)
