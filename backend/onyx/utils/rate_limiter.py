from types import TracebackType

from redis import Redis


class OnyxRateLimiter:
    def __init__(self, prefix: str, r: Redis):
        self._prefix: str = prefix
        self._redis: Redis = r

    def __enter__(self) -> "OnyxRateLimiter":
        retry_after = self._redis.get("retry-after")
        if retry_after is None:
            return self

        # self._lock
        # acquired = self._lock.acquire(blocking_timeout=self.LOCK_TTL)
        # if not acquired:
        #     raise RuntimeError(f"Could not acquire lock for key: {self.lock_key}")

        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        """Release the lock when exiting the context."""
        # if self._lock and self._lock.owned():
        #     self._lock.release()
