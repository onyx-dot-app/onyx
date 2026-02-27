from typing import cast

from redis.client import Redis
from redis.lock import Lock as RedisLock

from onyx.cache.interface import CacheBackend
from onyx.cache.interface import CacheLock


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
        self._lock.release()

    def owned(self) -> bool:
        return bool(self._lock.owned())


class RedisCacheBackend(CacheBackend):
    """``CacheBackend`` implementation that delegates to a ``redis.Redis`` client.

    This is a thin pass-through — every method maps 1-to-1 to the underlying
    Redis command.  ``TenantRedis`` key-prefixing is handled by the client
    itself (provided by ``get_redis_client``).
    """

    def __init__(self, redis_client: Redis) -> None:
        self._r = redis_client

    # -- basic key/value ---------------------------------------------------

    def get(self, key: str) -> bytes | None:
        val = self._r.get(key)
        if val is None:
            return None
        if isinstance(val, bytes):
            return val
        return str(val).encode()

    def set(
        self,
        key: str,
        value: str | bytes | int | float,
        ex: int | None = None,
    ) -> None:
        self._r.set(key, value, ex=ex)

    def delete(self, key: str) -> None:
        self._r.delete(key)

    def exists(self, key: str) -> bool:
        return bool(self._r.exists(key))

    # -- TTL ---------------------------------------------------------------

    def expire(self, key: str, seconds: int) -> None:
        self._r.expire(key, seconds)

    def ttl(self, key: str) -> int:
        return cast(int, self._r.ttl(key))

    # -- distributed lock --------------------------------------------------

    def lock(self, name: str, timeout: float | None = None) -> CacheLock:
        return RedisCacheLock(self._r.lock(name, timeout=timeout))

    # -- blocking list (MCP OAuth BLPOP pattern) ---------------------------

    def rpush(self, key: str, value: str | bytes) -> None:
        self._r.rpush(key, value)

    def blpop(self, keys: list[str], timeout: int = 0) -> tuple[bytes, bytes] | None:
        result = cast(list[bytes] | None, self._r.blpop(keys, timeout=timeout))
        if result is None:
            return None
        return (result[0], result[1])
