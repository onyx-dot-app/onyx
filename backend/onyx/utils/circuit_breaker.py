import threading
import time


class CircuitBreaker:
    """Stops calling something that keeps failing, backing off exponentially.

    For work that is expensive to fail rather than expensive to do: an
    unreachable host that drops packets costs a full timeout per attempt, so
    the useful thing is to stop asking for a while, not to retry harder.

    Opens after `failures_before_open` consecutive failures and stays open for
    a delay that doubles with each further failure, capped at `max_delay`. Any
    success closes it, so an isolated failure among healthy calls never opens
    it. Callers decide what to do while it is open; the breaker only answers
    whether to try.

    Thread-safe, so one instance can be shared across a worker's threads.
    """

    def __init__(
        self,
        *,
        failures_before_open: int = 3,
        base_delay: float = 60.0,
        max_delay: float = 6 * 60 * 60,
    ) -> None:
        self._failures_before_open = failures_before_open
        self._base_delay = base_delay
        self._max_delay = max_delay
        self._lock = threading.Lock()
        self._consecutive_failures = 0
        self._last_failure_at = 0.0

    @property
    def is_open(self) -> bool:
        """True while the caller should skip the call rather than retry it."""
        with self._lock:
            if self._consecutive_failures < self._failures_before_open:
                return False
            return time.monotonic() - self._last_failure_at < self._delay()

    def record_failure(self) -> int:
        """Count a failure; return how many have happened in a row."""
        with self._lock:
            self._consecutive_failures += 1
            self._last_failure_at = time.monotonic()
            return self._consecutive_failures

    def record_success(self) -> None:
        with self._lock:
            self._consecutive_failures = 0

    def _delay(self) -> float:
        """Backoff for the current failure count. Caller holds the lock."""
        doublings = self._consecutive_failures - self._failures_before_open
        return min(self._base_delay * 2**doublings, self._max_delay)
