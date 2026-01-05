"""Thread-safe rate limiting utilities for external API calls."""

import threading
import time
from collections.abc import Callable
from functools import wraps
from typing import Any
from typing import cast
from typing import TypeVar

from onyx.utils.logger import setup_logger

logger = setup_logger()

F = TypeVar("F", bound=Callable[..., Any])


class ThreadSafeRateLimiter:
    """A thread-safe rate limiter that prevents exceeding a maximum number of
    calls within a given time period.

    Uses a sliding window approach to track call timestamps and enforces
    rate limits across all threads.
    """

    def __init__(
        self,
        max_calls: int,
        period: float,  # in seconds
        name: str = "rate_limiter",
    ):
        """
        Args:
            max_calls: Maximum number of calls allowed within the period
            period: Time window in seconds
            name: Identifier for logging purposes
        """
        self.max_calls = max_calls
        self.period = period
        self.name = name
        self._lock = threading.Lock()
        self._call_timestamps: list[float] = []

    def _cleanup_old_calls(self, current_time: float) -> None:
        """Remove call timestamps that are outside the current window."""
        cutoff = current_time - self.period
        self._call_timestamps = [ts for ts in self._call_timestamps if ts > cutoff]

    def acquire(self, timeout: float | None = None) -> bool:
        """Attempt to acquire a rate limit slot.

        Args:
            timeout: Maximum time to wait for a slot (None = wait forever)

        Returns:
            True if slot was acquired, False if timeout was reached
        """
        start_time = time.monotonic()

        while True:
            with self._lock:
                current_time = time.monotonic()
                self._cleanup_old_calls(current_time)

                if len(self._call_timestamps) < self.max_calls:
                    self._call_timestamps.append(current_time)
                    return True

                # Calculate how long until the oldest call expires
                oldest_call = self._call_timestamps[0]
                wait_time = (oldest_call + self.period) - current_time

            # Check timeout before sleeping
            if timeout is not None:
                elapsed = time.monotonic() - start_time
                if elapsed >= timeout:
                    return False
                wait_time = min(wait_time, timeout - elapsed)

            if wait_time > 0:
                logger.debug(
                    f"Rate limiter '{self.name}': waiting {wait_time:.2f}s "
                    f"(rate limit reached)"
                )
                time.sleep(wait_time + 0.01)  # Small buffer to ensure slot is free

    def __call__(self, func: F) -> F:
        """Decorator to apply rate limiting to a function."""

        @wraps(func)
        def wrapped(*args: Any, **kwargs: Any) -> Any:
            self.acquire()
            return func(*args, **kwargs)

        return cast(F, wrapped)


# Global rate limiter for Exa API calls
# Exa has a 5 req/sec limit, we use 4 to leave some headroom
_exa_rate_limiter = ThreadSafeRateLimiter(
    max_calls=4,
    period=1.0,
    name="exa_api",
)


def get_exa_rate_limiter() -> ThreadSafeRateLimiter:
    """Get the global Exa API rate limiter."""
    return _exa_rate_limiter
