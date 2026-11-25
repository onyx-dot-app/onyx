import asyncio
import threading
import time
from collections import deque


class AdaptiveSemaphore:
    """An AIMD-sized semaphore shared by event loops on any thread. Slow start
    until the first rate limit, then +1 per round trip. A rate limit cuts at
    most once per cooldown: the requests in flight at a cut fail together.
    For thread pools, use threadpool_concurrency.AdaptiveTaskPool."""

    def __init__(
        self,
        *,
        initial: int,
        minimum: int,
        maximum: int,
        decrease_factor: float = 0.7,
        decrease_cooldown_seconds: float = 2.0,
    ) -> None:
        if not 1 <= minimum <= maximum:
            raise ValueError("Need 1 <= minimum <= maximum.")
        self._lock = threading.Lock()
        self._minimum = float(minimum)
        self._maximum = float(maximum)
        self._limit = float(min(max(initial, minimum), maximum))
        self._decrease_factor = decrease_factor
        self._decrease_cooldown = decrease_cooldown_seconds
        self._in_flight = 0
        self._in_slow_start = True
        # The clock can start below the cooldown, so 0 could hide the first cut.
        self._last_decrease = float("-inf")
        self._waiters: deque[tuple[asyncio.AbstractEventLoop, asyncio.Future[None]]] = (
            deque()
        )

    @property
    def limit(self) -> int:
        return int(self._limit)

    @property
    def in_flight(self) -> int:
        return self._in_flight

    async def acquire(self) -> None:
        loop = asyncio.get_running_loop()
        with self._lock:
            if not self._waiters and self._in_flight < int(self._limit):
                self._in_flight += 1
                return
            future: asyncio.Future[None] = loop.create_future()
            self._waiters.append((loop, future))
        try:
            await future
        except asyncio.CancelledError:
            with self._lock:
                try:
                    self._waiters.remove((loop, future))
                except ValueError:  # already granted
                    if future.done() and not future.cancelled():
                        self._release_locked()
            raise

    def release(self) -> None:
        with self._lock:
            self._release_locked()

    def record_success(self) -> None:
        with self._lock:
            step = 1.0 if self._in_slow_start else 1.0 / self._limit
            self._limit = min(self._maximum, self._limit + step)
            self._grant_locked()

    def record_rate_limit(self) -> None:
        now = time.monotonic()
        with self._lock:
            self._in_slow_start = False
            if now - self._last_decrease < self._decrease_cooldown:
                return
            self._last_decrease = now
            self._limit = max(self._minimum, self._limit * self._decrease_factor)

    def _release_locked(self) -> None:
        self._in_flight -= 1
        self._grant_locked()

    def _grant_locked(self) -> None:
        while self._waiters and self._in_flight < int(self._limit):
            loop, future = self._waiters.popleft()
            self._in_flight += 1
            try:
                loop.call_soon_threadsafe(self._grant_on_waiter_loop, future)
            except RuntimeError:  # the waiter's loop is closed
                self._in_flight -= 1

    def _grant_on_waiter_loop(self, future: asyncio.Future[None]) -> None:
        if future.cancelled():
            self.release()
        else:
            future.set_result(None)
