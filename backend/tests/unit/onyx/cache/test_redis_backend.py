from __future__ import annotations

import threading
from queue import Queue
from types import SimpleNamespace
from typing import cast

from onyx.cache.redis_backend import RedisCacheBackend
from onyx.redis.tenant_redis_client import TenantRedisClient


class _RedisLikeLock:
    """Minimal redis-py Lock behavior needed to reproduce token locality."""

    def __init__(self, *, thread_local: bool) -> None:
        self.local = threading.local() if thread_local else SimpleNamespace()
        self.local.token = None

    def acquire(
        self,
        blocking: bool = True,  # noqa: ARG002
        blocking_timeout: float | None = None,  # noqa: ARG002
    ) -> bool:
        self.local.token = b"token"
        return True

    def release(self) -> None:
        token = getattr(self.local, "token", None)
        if token is None:
            raise RuntimeError("Cannot release an unlocked lock")
        self.local.token = None

    def owned(self) -> bool:
        return getattr(self.local, "token", None) is not None


class _RecordingRedisClient:
    def __init__(self) -> None:
        self.lock_calls: list[dict[str, object]] = []
        self.lock_obj: _RedisLikeLock | None = None

    def lock(
        self,
        name: str,
        timeout: float | None = None,
        *,
        thread_local: bool = True,
    ) -> object:
        self.lock_calls.append(
            {"name": name, "timeout": timeout, "thread_local": thread_local}
        )
        self.lock_obj = _RedisLikeLock(thread_local=thread_local)
        return self.lock_obj


def test_redis_cache_locks_can_release_from_a_different_thread() -> None:
    redis_client = _RecordingRedisClient()
    backend = RedisCacheBackend(cast(TenantRedisClient, redis_client))
    lock = backend.lock("lock-key", timeout=90)

    assert lock.acquire()

    release_errors: Queue[BaseException] = Queue()

    def release_lock() -> None:
        try:
            lock.release()
        except BaseException as e:
            release_errors.put(e)

    release_thread = threading.Thread(target=release_lock)
    release_thread.start()
    release_thread.join(timeout=2)

    assert redis_client.lock_calls == [
        {"name": "lock-key", "timeout": 90, "thread_local": False}
    ]
    assert release_thread.is_alive() is False
    assert release_errors.empty()
