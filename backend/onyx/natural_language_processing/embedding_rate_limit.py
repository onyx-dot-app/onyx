"""A global limit on indexing embedding requests.

All docprocessing workers of a tenant share one window in Redis, so the limit
holds across pods. A worker that finds the window full, or that a provider
rate-limits, does not fail: it blocks and tries again about once a minute, for
up to six hours. With `worker_prefetch_multiplier = 1` and late acks, a blocked
worker thread takes no new Celery task, which pushes back on the queue.
"""

import asyncio
import random
import threading
import time
from collections.abc import Callable, Iterator

from redis.exceptions import RedisError

from onyx.connectors.models import ConnectorStopSignal
from onyx.redis.redis_pool import get_redis_client
from onyx.server.settings.store import load_settings
from onyx.utils.logger import setup_logger
from shared_configs.contextvars import get_current_tenant_id

logger = setup_logger()

_WINDOW_KEY = "embedding_rate_limit:request_times"

# The window is a list of request start times in ms, newest first, trimmed to
# the limit, so it works as a ring buffer. The script reads the Redis clock, so
# clock skew between pods has no effect. It returns 0 when the request took a
# slot, else the ms until the oldest request leaves the window.
_ACQUIRE_SCRIPT = """
local t = redis.call('TIME')
local now = tonumber(t[1]) * 1000 + math.floor(tonumber(t[2]) / 1000)
local limit = tonumber(ARGV[1])
local period = tonumber(ARGV[2])
if redis.call('LLEN', KEYS[1]) >= limit then
  local oldest = tonumber(redis.call('LINDEX', KEYS[1], limit - 1))
  if oldest and oldest > now - period then
    return oldest + period - now
  end
end
redis.call('LPUSH', KEYS[1], now)
redis.call('LTRIM', KEYS[1], 0, limit - 1)
redis.call('PEXPIRE', KEYS[1], period)
return 0
"""

# A blocked request tries again about once a minute, for up to six hours.
_RETRY_INTERVAL_SECONDS = 60.0
_RETRY_INTERVAL_JITTER_SECONDS = 10.0
_MAX_TOTAL_WAIT_SECONDS = 6 * 60 * 60
# The longest single sleep, so that a blocked worker sees a stop signal soon.
_STOP_CHECK_INTERVAL_SECONDS = 5.0


class EmbeddingWaitTimeoutError(Exception):
    """An embedding request waited the full time limit for a rate limit."""


def wait_sleeps(
    reason: str,
    started_at: float,
    should_stop: Callable[[], bool] | None,
) -> Iterator[float]:
    """Yields the sleeps of one jittered retry interval for a request that
    started waiting at `started_at` (monotonic). Raises
    EmbeddingWaitTimeoutError once the request has waited the time limit, and
    ConnectorStopSignal when `should_stop` turns true."""
    waited = time.monotonic() - started_at
    if waited >= _MAX_TOTAL_WAIT_SECONDS:
        raise EmbeddingWaitTimeoutError(
            f"{reason}; gave up after waiting {waited / 3600:.1f} hours"
        )
    wait = _RETRY_INTERVAL_SECONDS + random.uniform(
        -_RETRY_INTERVAL_JITTER_SECONDS, _RETRY_INTERVAL_JITTER_SECONDS
    )
    logger.info("%s; waiting %.1fs.", reason, wait)
    deadline = time.monotonic() + wait
    while (remaining := deadline - time.monotonic()) > 0:
        if should_stop is not None and should_stop():
            raise ConnectorStopSignal("Stop signal while waiting to embed")
        yield min(remaining, _STOP_CHECK_INTERVAL_SECONDS)


class EmbeddingWaitTotals:
    """Thread-safe running totals of the time embedding requests spent
    waiting, summed over all threads."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._rate_limit_seconds = 0.0
        self._provider_throttle_seconds = 0.0

    def add_rate_limit_wait(self, seconds: float) -> None:
        with self._lock:
            self._rate_limit_seconds += seconds

    def add_provider_throttle_wait(self, seconds: float) -> None:
        with self._lock:
            self._provider_throttle_seconds += seconds

    def snapshot(self) -> tuple[float, float]:
        """(rate limit wait, provider throttle wait), in seconds."""
        with self._lock:
            return self._rate_limit_seconds, self._provider_throttle_seconds


class EmbeddingRateLimiter:
    """Allows at most `max_requests` embedding requests in any window of
    `period_seconds`, across all workers of the tenant."""

    def __init__(
        self, tenant_id: str, max_requests: int, period_seconds: float
    ) -> None:
        self.max_requests = max_requests
        self.period_seconds = period_seconds
        self._redis = get_redis_client(tenant_id=tenant_id)

    def acquire(
        self,
        should_stop: Callable[[], bool] | None = None,
        started_at: float | None = None,
    ) -> float:
        """Blocks until this request takes a slot in the window. The time limit
        counts from `started_at` (monotonic), or from now. Returns the seconds
        spent waiting."""
        start = time.monotonic()
        for sleep_seconds in self._sleeps(should_stop, started_at or start):
            time.sleep(sleep_seconds)
        return time.monotonic() - start

    async def acquire_async(
        self,
        should_stop: Callable[[], bool] | None = None,
        started_at: float | None = None,
    ) -> float:
        """Blocks until this request takes a slot in the window. The time limit
        counts from `started_at` (monotonic), or from now. Returns the seconds
        spent waiting."""
        start = time.monotonic()
        for sleep_seconds in self._sleeps(should_stop, started_at or start):
            await asyncio.sleep(sleep_seconds)
        return time.monotonic() - start

    def _try_acquire(self) -> float:
        """Takes a slot and returns 0, or returns the seconds until a slot frees."""
        try:
            wait_ms = self._redis.eval(
                _ACQUIRE_SCRIPT,
                keys=[_WINDOW_KEY],
                args=[self.max_requests, int(self.period_seconds * 1000)],
            )
        except RedisError:
            logger.warning(
                "The embedding rate limiter cannot reach Redis; the request is not limited.",
                exc_info=True,
            )
            return 0
        return int(wait_ms) / 1000

    def _sleeps(
        self, should_stop: Callable[[], bool] | None, started_at: float
    ) -> Iterator[float]:
        """Yields the sleeps until this request takes a slot."""
        while self._try_acquire() > 0:
            yield from wait_sleeps(
                f"Embedding rate limit of {self.max_requests} requests per "
                f"{self.period_seconds}s is full",
                started_at,
                should_stop,
            )


def load_embedding_rate_limiter() -> EmbeddingRateLimiter | None:
    """The current tenant's limiter, or None when the admin set no limit."""
    settings = load_settings()
    if settings.embedding_rate_limit_requests is None:
        return None
    return EmbeddingRateLimiter(
        tenant_id=get_current_tenant_id(),
        max_requests=settings.embedding_rate_limit_requests,
        period_seconds=settings.embedding_rate_limit_period_seconds,
    )
