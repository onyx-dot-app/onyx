from __future__ import annotations

from onyx.cache.interface import CacheBackend
from onyx.cache.interface import CacheLock


class FakeLock(CacheLock):
    def __init__(self) -> None:
        self._owned = False

    def acquire(
        self,
        blocking: bool = True,
        blocking_timeout: float | None = None,
    ) -> bool:
        _ = blocking
        _ = blocking_timeout
        if self._owned:
            return False
        self._owned = True
        return True

    def release(self) -> None:
        self._owned = False

    def owned(self) -> bool:
        return self._owned


class FakeCache(CacheBackend):
    def __init__(self) -> None:
        self.store: dict[str, bytes] = {}
        self.expiries: dict[str, int] = {}
        self.locks: dict[str, FakeLock] = {}

    def get(self, key: str) -> bytes | None:
        return self.store.get(key)

    def set(
        self,
        key: str,
        value: str | bytes | int | float,
        ex: int | None = None,
    ) -> None:
        self.store[key] = value if isinstance(value, bytes) else str(value).encode()
        if ex is not None:
            self.expiries[key] = ex

    def delete(self, key: str) -> None:
        self.store.pop(key, None)
        self.expiries.pop(key, None)

    def exists(self, key: str) -> bool:
        return key in self.store

    def expire(self, key: str, seconds: int) -> None:
        self.expiries[key] = seconds

    def ttl(self, key: str) -> int:
        return 60 if key in self.store else -2

    def lock(self, name: str, timeout: float | None = None) -> CacheLock:
        _ = timeout
        return self.locks.setdefault(name, FakeLock())

    def rpush(self, key: str, value: str | bytes) -> None:
        raise NotImplementedError

    def blpop(self, keys: list[str], timeout: int = 0) -> tuple[bytes, bytes] | None:
        raise NotImplementedError
