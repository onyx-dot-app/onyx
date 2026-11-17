import asyncio
import time
from collections.abc import AsyncGenerator, Generator
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager, contextmanager
from logging import Logger, LoggerAdapter

from onyx.cache.factory import get_shared_cache_backend
from onyx.cache.interface import CacheLock, CacheLockAcquisitionError


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
    """Async variant of ``cache_shared_lock``.

    Backend lock ops are synchronous I/O, and a Postgres advisory lock binds
    its session for the lock's lifetime, so acquire and release must run on
    the same thread — hence a dedicated single-worker executor rather than
    ``asyncio.to_thread``.
    """

    def acquire_in_worker() -> tuple[CacheLock, bool]:
        lock = get_shared_cache_backend().lock(lock_name, timeout=max_time_lock_held_s)
        return lock, lock.acquire(blocking=True, blocking_timeout=wait_for_lock_s)

    executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="cache-lock")
    acquire_fut = executor.submit(acquire_in_worker)
    start_time = time.monotonic()
    try:
        try:
            lock, acquired = await asyncio.shield(asyncio.wrap_future(acquire_fut))
        except asyncio.CancelledError:
            # Queue cleanup on the acquiring thread. The event loop may close
            # before acquisition completes, so a loop callback cannot own cleanup.
            def release_late_acquire() -> None:
                try:
                    late_lock, late_acquired = acquire_fut.result()
                except Exception:
                    return
                if late_acquired:
                    _release_cache_lock(
                        late_lock,
                        lock_name,
                        time.monotonic() - start_time,
                        max_time_lock_held_s,
                        logger,
                    )

            executor.submit(release_late_acquire)
            raise
        if not acquired:
            raise CacheLockAcquisitionError(
                f"Timed out waiting to acquire cache lock {lock_name} after "
                f"{time.monotonic() - start_time:.3f} seconds."
            )
        try:
            yield
        finally:
            held_s = time.monotonic() - start_time
            release_fut = executor.submit(
                _release_cache_lock,
                lock,
                lock_name,
                held_s,
                max_time_lock_held_s,
                logger,
            )
            await asyncio.shield(asyncio.wrap_future(release_fut))
    finally:
        executor.shutdown(wait=False)
