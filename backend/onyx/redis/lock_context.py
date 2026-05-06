import time
from collections.abc import Generator
from contextlib import contextmanager
from logging import Logger
from logging import LoggerAdapter

from redis.lock import Lock

from onyx.redis.redis_pool import get_shared_redis_client


class RedisSharedLockAcquisitionError(Exception):
    """Raised when a Redis shared lock cannot be acquired."""


@contextmanager
def redis_shared_lock(
    lock_name: str,
    max_time_lock_held_s: float,
    wait_for_lock_s: float,
    logger: Logger | LoggerAdapter,
) -> Generator[str | bytes, None, None]:
    """Context manager to acquire a system-wide shared Redis lock.

    Args:
        lock_name: Name of the lock to acquire.
        max_time_lock_held_s: Maximum time in seconds the lock can be held for.
            Will automatically be released after this time. Application code
            running within the context manager must keep this in mind.
        wait_for_lock_s: Time in seconds to wait to acquire the lock. If the
            lock is not acquired within this time, a
            RedisSharedLockAcquisitionError will be raised.
        logger: Logger to use for logging.

    Raises:
        RedisSharedLockAcquisitionError: The Redis lock was not acquired within
            the given time.

    Yields:
        The token of the acquired lock.
    """
    redis_client = get_shared_redis_client()
    lock: Lock | None = None
    acquired = False
    start_time = time.monotonic()
    try:
        lock = redis_client.lock(
            name=lock_name,
            # The maximum time the lock can be held for. Will automatically be
            # released after this time.
            timeout=max_time_lock_held_s,
            # .acquire will block until the lock is acquired.
            blocking=True,
            # Time to wait to acquire the lock.
            blocking_timeout=wait_for_lock_s,
        )
        if not lock.acquire():
            raise RedisSharedLockAcquisitionError(
                f"Timed out waiting to acquire Redis lock {lock_name} after {time.monotonic() - start_time:.3f} seconds."
            )
        else:
            acquired = True
            yield lock.local.token
    finally:
        if acquired:
            assert (
                lock is not None
            ), "Bug: Redis lock should have been initialized by now."
            if lock.owned():
                lock.release()
                logger.debug(
                    "Redis lock %s released after %s seconds.",
                    lock_name,
                    format(time.monotonic() - start_time, ".3f"),
                )
            else:
                logger.warning(
                    "Redis lock %s was not owned on exit. The lock context manager took %s seconds.",
                    lock_name,
                    format(time.monotonic() - start_time, ".3f"),
                )
