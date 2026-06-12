from collections.abc import Iterator

from redis.lock import Lock as RedisLock

from onyx.cache.interface import CacheBackend
from onyx.cache.interface import CacheLock
from onyx.redis.tenant_redis_client import TenantRedisClient


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
    """``CacheBackend`` implementation that delegates to a tenant Redis client.

    This is a thin pass-through — every method maps 1-to-1 to the underlying
    Redis command. Key-prefixing is handled by the ``TenantRedisClient``
    itself (provided by ``get_redis_client``).
    """

    def __init__(self, redis_client: TenantRedisClient) -> None:
        self._r = redis_client

    # -- basic key/value ---------------------------------------------------

    def get(self, key: str) -> bytes | None:
        return self._r.get(key)

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
        return self._r.ttl(key)

    # -- distributed lock --------------------------------------------------

    def lock(self, name: str, timeout: float | None = None) -> CacheLock:
        return RedisCacheLock(self._r.lock(name, timeout=timeout, thread_local=False))

    # -- blocking list (MCP OAuth BLPOP pattern) ---------------------------

    def rpush(self, key: str, value: str | bytes) -> None:
        self._r.rpush(key, value)

    def blpop(self, keys: list[str], timeout: int = 0) -> tuple[bytes, bytes] | None:
        return self._r.blpop(keys, timeout=timeout)

    # -- pub/sub -----------------------------------------------------------
    #
    # Use the *raw* (non-prefixed) client: pub/sub channels are global, so the
    # name must be identical across tenants and processes.

    def publish(self, channel: str, message: str | bytes) -> None:
        self._r.raw_client.publish(channel, message)

    def subscribe(self, channel: str) -> Iterator[bytes]:
        pubsub = self._r.raw_client.pubsub()
        try:
            pubsub.subscribe(channel)
            for message in pubsub.listen():
                # listen() also emits a 'subscribe' confirmation; skip non-messages.
                if message.get("type") != "message":
                    continue
                data = message.get("data")
                if isinstance(data, bytes):
                    yield data
        finally:
            # close() can itself raise if the connection already died.
            try:
                pubsub.close()
            except Exception:
                pass
