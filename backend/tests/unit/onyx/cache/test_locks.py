"""Unit tests for the shared cache lock helpers in onyx.cache.locks.

Runs the real ``async_cache_shared_lock`` against a fake cache backend so
acquisition, contention, timeout, and release semantics are all exercised
without live Redis/Postgres.
"""

import asyncio
import threading
import time
from types import SimpleNamespace
from typing import cast

import pytest

import onyx.cache.locks as locks_module
from onyx.cache.interface import CacheBackend, CacheLock, CacheLockAcquisitionError
from onyx.utils.logger import setup_logger

logger = setup_logger()


class _FakeLock(CacheLock):
    """In-memory lock mimicking the backend contract: ``acquire`` honors
    blocking/blocking_timeout, ``owned`` reports holder state, ``release``
    frees it. All state guarded by a threading.Lock since the helper runs
    backend calls on a worker thread."""

    def __init__(self) -> None:
        self._owner: int | None = None
        self._guard = threading.Lock()
        self.release_calls = 0
        self._token = 0

    def acquire(
        self, blocking: bool = True, blocking_timeout: float | None = None
    ) -> bool:
        with self._guard:
            self._token += 1
            token = self._token
        deadline = (time.monotonic() + blocking_timeout) if blocking_timeout else None
        while True:
            with self._guard:
                if self._owner is None:
                    self._owner = token
                    return True
            if not blocking or (deadline and time.monotonic() >= deadline):
                return False
            time.sleep(0.005)

    def release(self) -> None:
        with self._guard:
            assert self._owner is not None
            self._owner = None
            self.release_calls += 1

    def owned(self) -> bool:
        with self._guard:
            return self._owner is not None

    def extend(self, ttl_seconds: float) -> None:
        pass


def _fake_backend(lock: _FakeLock) -> CacheBackend:
    backend = SimpleNamespace()
    backend.lock = lambda _name, **_kwargs: lock
    return cast(CacheBackend, backend)


def test_async_lock_acquires_and_releases(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = _FakeLock()
    monkeypatch.setattr(
        locks_module, "get_shared_cache_backend", lambda: _fake_backend(fake)
    )

    async def run() -> None:
        async with locks_module.async_cache_shared_lock("test-lock", 60.0, 5.0, logger):
            assert fake.owned()

    asyncio.run(run())

    assert fake.release_calls == 1
    assert not fake.owned()


def test_async_lock_serializes_concurrent_contenders(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Two coroutines on one event loop must enter the critical section one
    at a time — and the waiter must not block the loop (the holder's own
    progress depends on it)."""
    fake = _FakeLock()
    monkeypatch.setattr(
        locks_module, "get_shared_cache_backend", lambda: _fake_backend(fake)
    )
    inside = 0
    max_inside = 0
    entered: list[str] = []

    async def contender(name: str) -> None:
        nonlocal inside, max_inside
        async with locks_module.async_cache_shared_lock("test-lock", 60.0, 5.0, logger):
            inside += 1
            max_inside = max(max_inside, inside)
            entered.append(name)
            await asyncio.sleep(0.05)
            inside -= 1

    async def run() -> None:
        await asyncio.gather(contender("a"), contender("b"), contender("c"))

    asyncio.run(run())

    assert max_inside == 1
    assert len(entered) == 3
    assert fake.release_calls == 3


def test_async_lock_times_out_when_held(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = _FakeLock()
    monkeypatch.setattr(
        locks_module, "get_shared_cache_backend", lambda: _fake_backend(fake)
    )

    async def run() -> None:
        assert fake.acquire(blocking=False)
        with pytest.raises(CacheLockAcquisitionError):
            async with locks_module.async_cache_shared_lock(
                "test-lock", 60.0, 0.2, logger
            ):
                raise AssertionError("must not enter while held")

    asyncio.run(run())


def test_async_lock_does_not_release_unowned_on_timeout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = _FakeLock()
    monkeypatch.setattr(
        locks_module, "get_shared_cache_backend", lambda: _fake_backend(fake)
    )

    async def run() -> None:
        assert fake.acquire(blocking=False)
        with pytest.raises(CacheLockAcquisitionError):
            async with locks_module.async_cache_shared_lock(
                "test-lock", 60.0, 0.1, logger
            ):
                pass
        assert fake.owned()

    asyncio.run(run())


def test_async_lock_releases_on_body_exception(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = _FakeLock()
    monkeypatch.setattr(
        locks_module, "get_shared_cache_backend", lambda: _fake_backend(fake)
    )

    async def run() -> None:
        with pytest.raises(RuntimeError):
            async with locks_module.async_cache_shared_lock(
                "test-lock", 60.0, 5.0, logger
            ):
                raise RuntimeError("boom")

    asyncio.run(run())

    assert fake.release_calls == 1
    assert not fake.owned()


def test_sync_lock_still_acquires_for_sync_callers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = _FakeLock()
    monkeypatch.setattr(
        locks_module, "get_shared_cache_backend", lambda: _fake_backend(fake)
    )

    with locks_module.cache_shared_lock("test-lock", 60.0, 5.0, logger):
        assert fake.owned()

    assert fake.release_calls == 1


def test_async_lock_releases_late_acquire_after_cancellation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """If the awaiting coroutine is cancelled while the worker is still
    acquiring, whatever it eventually acquires must be released — a late
    Postgres advisory lock would otherwise be stranded forever."""
    fake = _FakeLock()
    monkeypatch.setattr(
        locks_module, "get_shared_cache_backend", lambda: _fake_backend(fake)
    )

    async def run() -> None:
        assert fake.acquire(blocking=False)
        task = asyncio.create_task(
            locks_module.async_cache_shared_lock(
                "test-lock", 60.0, 5.0, logger
            ).__aenter__()
        )
        await asyncio.sleep(0.05)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        # release_calls also counts this test's own release of holder.
        releases_before = fake.release_calls
        fake.release()
        for _ in range(200):
            await asyncio.sleep(0.01)
            if fake.release_calls > releases_before + 1:
                break
        assert fake.release_calls == releases_before + 2
        assert not fake.owned()

    asyncio.run(run())
