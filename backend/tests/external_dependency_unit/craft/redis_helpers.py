"""Redis helper assertions shared by Craft tests."""

from __future__ import annotations

import threading

from redis import Redis

from onyx.redis.tenant_redis_client import TenantRedisClient


def assert_lock_serializes_two_threads(
    redis_client: Redis | TenantRedisClient,  # type: ignore[type-arg]
    lock_key: str,
) -> None:
    """Verify two concurrent acquirers contend on ``lock_key`` — one waits.

    Spawns two threads that race for the same Redis lock; the first
    thread acquires + holds, the second observes that a non-blocking
    acquire fails (the serialization point). Cleans the key before and
    after.
    """
    redis_client.delete(lock_key)

    first_holds_lock = threading.Event()
    release_event = threading.Event()
    second_saw_lock_held: list[bool] = []

    def first() -> None:
        lock = redis_client.lock(lock_key, timeout=30)
        assert lock.acquire(blocking=True, blocking_timeout=5) is True
        first_holds_lock.set()
        try:
            release_event.wait(timeout=5)
        finally:
            lock.release()

    def second() -> None:
        assert first_holds_lock.wait(timeout=5)
        lock = redis_client.lock(lock_key, timeout=30)
        acquired_immediately = lock.acquire(blocking=False)
        second_saw_lock_held.append(not acquired_immediately)
        if acquired_immediately:
            lock.release()
            return
        release_event.set()
        assert lock.acquire(blocking=True, blocking_timeout=5) is True
        lock.release()

    t1 = threading.Thread(target=first)
    t2 = threading.Thread(target=second)
    t1.start()
    t2.start()
    t1.join(timeout=10)
    t2.join(timeout=10)

    assert second_saw_lock_held == [True]
    redis_client.delete(lock_key)
