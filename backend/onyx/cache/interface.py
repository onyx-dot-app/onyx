import abc
from enum import Enum


class CacheBackendType(str, Enum):
    REDIS = "redis"
    POSTGRES = "postgres"


class CacheLock(abc.ABC):
    """Abstract distributed lock returned by CacheBackend.lock()."""

    @abc.abstractmethod
    def acquire(
        self,
        blocking: bool = True,
        blocking_timeout: float | None = None,
    ) -> bool:
        raise NotImplementedError

    @abc.abstractmethod
    def release(self) -> None:
        raise NotImplementedError

    @abc.abstractmethod
    def owned(self) -> bool:
        raise NotImplementedError


class CacheBackend(abc.ABC):
    """Thin abstraction over a key-value cache with TTL, locks, and blocking lists.

    Covers the subset of Redis operations used outside of Celery. When
    CACHE_BACKEND=postgres, a PostgreSQL-backed implementation is used instead.
    """

    # -- basic key/value ---------------------------------------------------

    @abc.abstractmethod
    def get(self, key: str) -> bytes | None:
        raise NotImplementedError

    @abc.abstractmethod
    def set(
        self,
        key: str,
        value: str | bytes | int | float,
        ex: int | None = None,
    ) -> None:
        raise NotImplementedError

    @abc.abstractmethod
    def delete(self, key: str) -> None:
        raise NotImplementedError

    @abc.abstractmethod
    def exists(self, key: str) -> bool:
        raise NotImplementedError

    # -- TTL ---------------------------------------------------------------

    @abc.abstractmethod
    def expire(self, key: str, seconds: int) -> None:
        raise NotImplementedError

    @abc.abstractmethod
    def ttl(self, key: str) -> int:
        """Return remaining TTL in seconds. -1 if no expiry, -2 if key missing."""
        raise NotImplementedError

    # -- distributed lock --------------------------------------------------

    @abc.abstractmethod
    def lock(self, name: str, timeout: float | None = None) -> CacheLock:
        raise NotImplementedError

    # -- blocking list (used by MCP OAuth BLPOP pattern) -------------------

    @abc.abstractmethod
    def rpush(self, key: str, value: str | bytes) -> None:
        raise NotImplementedError

    @abc.abstractmethod
    def blpop(self, keys: list[str], timeout: int = 0) -> tuple[bytes, bytes] | None:
        """Block until a value is available on one of *keys*, or *timeout* expires.

        Returns ``(key, value)`` or ``None`` on timeout.
        """
        raise NotImplementedError
