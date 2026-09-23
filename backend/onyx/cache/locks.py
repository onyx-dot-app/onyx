import asyncio
import time
from collections.abc import AsyncGenerator, Generator
from contextlib import asynccontextmanager, contextmanager
from logging import Logger, LoggerAdapter

from onyx.cache.factory import get_shared_cache_backend
from onyx.cache.interface import CacheLock, CacheLockAcquisitionError

_ASYNC_LOCK_POLL_INTERVAL_S = 0.05


@contextmanager
def cache_shared_lock(
    lock_name: str,
    max_time_lock_held_s: float,
    wait_for_lock_s: float,
    logger: Logger | LoggerAdapter,
) -> Generator[None, None, None]:
    """Acquire a system-wide (cross-tenant) distributed lock via the configured
    cache backend.

    ``max_time_lock_held_s`` is a lease enforced only on Redis, where the lock
    auto-releases after it even if the holder wedges. A Postgres advisory lock
    has no TTL — it is held until the guarded block exits or the holding
    connection drops, so there a wedged holder keeps the lock until it unwinds.
    Callers must therefore bound their own work under the lock; on Postgres that
    is the only limit. (A *crashed* holder frees the lock on both backends: Redis
    lease expiry / Postgres connection close.)

    Raises ``CacheLockAcquisitionError`` if not acquired within ``wait_for_lock_s``.
    """
    lock = get_shared_cache_backend().lock(lock_name, timeout=max_time_lock_held_s)
    acquired = False
    start_time = time.monotonic()
    try:
        acquired = lock.acquire(blocking=True, blocking_timeout=wait_for_lock_s)
        if not acquired:
            raise CacheLockAcquisitionError(
                f"Timed out waiting to acquire cache lock {lock_name} after "
                f"{time.monotonic() - start_time:.3f} seconds."
            )
        yield
    finally:
        if acquired:
            held_s = time.monotonic() - start_time
            _release_cache_lock(lock, lock_name, held_s, max_time_lock_held_s, logger)


def _release_cache_lock(
    lock: CacheLock,
    lock_name: str,
    held_s: float,
    lease_s: float,
    logger: Logger | LoggerAdapter,
) -> None:
    if lock.owned():
        lock.release()
        logger.debug("Cache lock %s released after %.3fs.", lock_name, held_s)
    else:
        # Lease expired before we finished, so a second caller may already
        # hold it. The fix is a larger max_time_lock_held_s.
        logger.warning(
            "Cache lock %s lost before release: held %.3fs, exceeding the "
            "%.3fs lease. Mutual exclusion may have been violated.",
            lock_name,
            held_s,
            lease_s,
        )


@asynccontextmanager
async def async_cache_shared_lock(
    lock_name: str,
    max_time_lock_held_s: float,
    wait_for_lock_s: float,
    logger: Logger | LoggerAdapter,
) -> AsyncGenerator[None, None]:
    """Async variant of ``cache_shared_lock`` for event-loop callers.

    Polls ``acquire(blocking=False)`` with ``asyncio.sleep`` between attempts
    so contention never blocks the loop: a waiter on the same event loop as
    the holder still lets the holder's refresh make progress.

    Raises ``CacheLockAcquisitionError`` if not acquired within ``wait_for_lock_s``.
    """
    lock = get_shared_cache_backend().lock(lock_name, timeout=max_time_lock_held_s)
    acquired = False
    start_time = time.monotonic()
    try:
        while not acquired:
            acquired = lock.acquire(blocking=False)
            if not acquired:
                elapsed_s = time.monotonic() - start_time
                if elapsed_s >= wait_for_lock_s:
                    raise CacheLockAcquisitionError(
                        f"Timed out waiting to acquire cache lock {lock_name} "
                        f"after {elapsed_s:.3f} seconds."
                    )
                await asyncio.sleep(_ASYNC_LOCK_POLL_INTERVAL_S)
        yield
    finally:
        if acquired:
            held_s = time.monotonic() - start_time
            _release_cache_lock(lock, lock_name, held_s, max_time_lock_held_s, logger)
