"""A global limit on indexing embedding requests.

All docprocessing workers of a tenant share one window in Redis, so the limit
holds across pods. A worker that finds the window full does not fail: it
blocks with exponential backoff. With `worker_prefetch_multiplier = 1` and late
acks, a blocked worker thread takes no new Celery task, which pushes back on
the queue.
"""

import asyncio
import random
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

_BACKOFF_SCALE_SECONDS = 1.0
_BACKOFF_MAX_SECONDS = 30 * 60
_BACKOFF_JITTER_RATIO = 0.1
# The longest single sleep, so that a blocked worker sees a stop signal soon.
_STOP_CHECK_INTERVAL_SECONDS = 5.0


class EmbeddingRateLimiter:
    """Allows at most `max_requests` embedding requests in any window of
    `period_seconds`, across all workers of the tenant."""

    def __init__(
        self, tenant_id: str, max_requests: int, period_seconds: float
    ) -> None:
        self.max_requests = max_requests
        self.period_seconds = period_seconds
        self._redis = get_redis_client(tenant_id=tenant_id)

    def acquire(self, should_stop: Callable[[], bool] | None = None) -> None:
        """Blocks until this request takes a slot in the window."""
        for sleep_seconds in self._sleeps(should_stop):
            time.sleep(sleep_seconds)

    async def acquire_async(
        self, should_stop: Callable[[], bool] | None = None
    ) -> None:
        """Blocks until this request takes a slot in the window."""
        for sleep_seconds in self._sleeps(should_stop):
            await asyncio.sleep(sleep_seconds)

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

    def _sleeps(self, should_stop: Callable[[], bool] | None) -> Iterator[float]:
        """Yields the sleeps until this request takes a slot. Each wait is the
        longer of the exponential backoff and the time until a slot frees."""
        attempt = 0
        while (slot_wait := self._try_acquire()) > 0:
            backoff = min(_BACKOFF_SCALE_SECONDS * 2**attempt, _BACKOFF_MAX_SECONDS)
            wait = max(slot_wait, backoff) * random.uniform(
                1, 1 + _BACKOFF_JITTER_RATIO
            )
            logger.info(
                "Embedding rate limit of %s requests per %ss is full; waiting %.1fs.",
                self.max_requests,
                self.period_seconds,
                wait,
            )
            deadline = time.monotonic() + wait
            while (remaining := deadline - time.monotonic()) > 0:
                if should_stop is not None and should_stop():
                    raise ConnectorStopSignal(
                        "Stop signal while waiting for the embedding rate limit"
                    )
                yield min(remaining, _STOP_CHECK_INTERVAL_SECONDS)
            attempt += 1


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
