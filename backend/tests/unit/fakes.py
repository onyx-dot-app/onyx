from __future__ import annotations

import builtins
from collections.abc import Collection

from onyx.cache.interface import CacheBackend, CacheLock


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

    def extend(self, ttl_seconds: float) -> None:
        pass

    def owned(self) -> bool:
        return self._owned


class FakeCache(CacheBackend):
    def __init__(self) -> None:
        self.store: dict[str, bytes] = {}
        self.sets: dict[str, set[bytes]] = {}
        self.expiries: dict[str, int] = {}
        self.locks: dict[str, FakeLock] = {}

    def get(self, key: str) -> bytes | None:
        return self.store.get(key)

    def getdel(self, key: str) -> bytes | None:
        self.expiries.pop(key, None)
        return self.store.pop(key, None)

    def set(
        self,
        key: str,
        value: str | bytes | int | float,
        ex: int | None = None,
    ) -> None:
        self.store[key] = value if isinstance(value, bytes) else str(value).encode()
        if ex is not None:
            self.expiries[key] = ex

    def set_if_absent(
        self,
        key: str,
        value: str | bytes | int | float,
        ex: int | None = None,
    ) -> bool:
        if key in self.store:
            return False
        self.set(key, value, ex=ex)
        return True

    def delete(self, key: str) -> None:
        self.store.pop(key, None)
        self.expiries.pop(key, None)

    def delete_prefix(self, prefix: str) -> None:
        if not prefix:
            raise ValueError("Cache deletion requires a nonempty prefix")
        for key in list(self.store):
            if key.startswith(prefix):
                self.delete(key)

    def exists_many(self, keys: Collection[str]) -> builtins.set[str]:
        return {key for key in keys if key in self.store}

    def set_add(self, key: str, member: str | bytes) -> None:
        value = member if isinstance(member, bytes) else member.encode()
        self.sets.setdefault(key, set()).add(value)

    def set_remove(self, key: str, member: str | bytes) -> None:
        value = member if isinstance(member, bytes) else member.encode()
        self.sets.get(key, set()).discard(value)

    def set_members(self, key: str, *, limit: int) -> list[bytes]:
        if limit < 1:
            raise ValueError("Cache set member limit must be positive")
        return list(self.sets.get(key, set()))[:limit]

    def exists(self, key: str) -> bool:
        return key in self.store

    def expire(self, key: str, seconds: int) -> None:
        self.expiries[key] = seconds

    def renew_if_value(self, key: str, expected: bytes, seconds: int) -> bool:
        if self.get(key) != expected:
            return False
        self.expire(key, seconds)
        return True

    def ttl(self, key: str) -> int:
        return 60 if key in self.store else -2

    def lock(self, name: str, timeout: float | None = None) -> CacheLock:
        _ = timeout
        return self.locks.setdefault(name, FakeLock())

    def rpush(self, key: str, value: str | bytes) -> None:
        raise NotImplementedError

    def blpop(self, keys: list[str], timeout: int = 0) -> tuple[bytes, bytes] | None:
        raise NotImplementedError
