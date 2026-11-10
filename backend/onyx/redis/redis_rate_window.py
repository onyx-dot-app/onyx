"""Sliding-window budgets in Redis, shared by every worker.

A window allows ``limit`` units in any ``period_seconds``. A request has a
cost in units and can take from several windows in one atomic step, for
example a project budget and a user budget. The embedding limiter and the
source-API limiter use this one mechanism.

A window can also adapt (AIMD). ``cut`` halves the share of the limit that
the window allows, when the service pushed back. The share then grows back
in small steps while requests go on.
"""

from collections.abc import Sequence

from pydantic import BaseModel, ConfigDict
from redis.exceptions import RedisError

from onyx.redis.redis_pool import TenantRedisClient
from onyx.utils.logger import setup_logger

logger = setup_logger()

# The lowest share of its limit that a cut can leave a window.
MIN_BUDGET_FACTOR = 0.1
# After a cut, hold the lower share this long before it grows. One burst of
# pushback then makes one cut.
CUT_HOLD_SECONDS = 30.0
# The share grows by this much each interval after the hold.
GROW_STEP = 0.05
GROW_INTERVAL_SECONDS = 10.0
# The adaptive state outlives an idle window by this long.
_META_TTL_SECONDS = 600


class RateWindow(BaseModel):
    """One budget: ``limit`` units in any ``period_seconds``."""

    model_config = ConfigDict(frozen=True)

    key: str
    limit: int
    period_seconds: float


# Each window has a log (a sorted set of requests by start time, with the cost
# in the member) and a meta hash (the running total and the adaptive state).
# The script reads the Redis clock, so clock skew between pods has no effect.
# It returns 0 when the request took its units from every window. If one
# window is full, it takes nothing and returns the ms until that window's
# oldest request leaves.
_ACQUIRE_SCRIPT = """
local t = redis.call('TIME')
local now = tonumber(t[1]) * 1000 + math.floor(tonumber(t[2]) / 1000)
local cost = tonumber(ARGV[1])
local grow_ms = tonumber(ARGV[2])
local grow_step = tonumber(ARGV[3])
local meta_ttl = tonumber(ARGV[4])
local n = #KEYS / 2
local wait = 0
for i = 1, n do
  local log = KEYS[2 * i - 1]
  local meta = KEYS[2 * i]
  local limit = tonumber(ARGV[3 + 2 * i])
  local period = tonumber(ARGV[4 + 2 * i])
  local old = redis.call('ZRANGEBYSCORE', log, '-inf', now - period)
  if #old > 0 then
    local freed = 0
    for _, member in ipairs(old) do
      freed = freed + tonumber(string.match(member, ':(%d+)$'))
    end
    redis.call('ZREMRANGEBYSCORE', log, '-inf', now - period)
    redis.call('HINCRBY', meta, 'total', -freed)
  end
  local total = tonumber(redis.call('HGET', meta, 'total') or '0')
  if redis.call('ZCARD', log) == 0 and total ~= 0 then
    total = 0
    redis.call('HSET', meta, 'total', 0)
  end
  local factor = tonumber(redis.call('HGET', meta, 'factor') or '1')
  if factor < 1 then
    local hold_until = tonumber(redis.call('HGET', meta, 'hold_until') or '0')
    local grown_at = tonumber(redis.call('HGET', meta, 'grown_at') or '0')
    if now >= hold_until and now - grown_at >= grow_ms then
      factor = math.min(1, factor + grow_step)
      redis.call('HSET', meta, 'factor', tostring(factor), 'grown_at', now)
    end
  end
  -- One request always fits an empty window, however large its cost.
  local allowed = math.max(cost, math.floor(limit * factor))
  if total + cost > allowed then
    local oldest = redis.call('ZRANGE', log, 0, 0, 'WITHSCORES')
    local window_wait = 1
    if oldest[2] then
      window_wait = math.max(1, tonumber(oldest[2]) + period - now)
    end
    wait = math.max(wait, window_wait)
  end
end
if wait > 0 then
  return wait
end
for i = 1, n do
  local log = KEYS[2 * i - 1]
  local meta = KEYS[2 * i]
  local period = tonumber(ARGV[4 + 2 * i])
  local seq = redis.call('HINCRBY', meta, 'seq', 1)
  redis.call('ZADD', log, now, now .. ':' .. seq .. ':' .. cost)
  redis.call('HINCRBY', meta, 'total', cost)
  redis.call('PEXPIRE', log, period)
  redis.call('PEXPIRE', meta, math.max(period, meta_ttl))
end
return 0
"""

# Halves the window's share of its limit, at most once in each hold. Returns
# the share in thousandths.
_CUT_SCRIPT = """
local t = redis.call('TIME')
local now = tonumber(t[1]) * 1000 + math.floor(tonumber(t[2]) / 1000)
local min_factor = tonumber(ARGV[1])
local hold_ms = tonumber(ARGV[2])
local meta_ttl = tonumber(ARGV[3])
local factor = tonumber(redis.call('HGET', KEYS[1], 'factor') or '1')
local hold_until = tonumber(redis.call('HGET', KEYS[1], 'hold_until') or '0')
if now >= hold_until then
  factor = math.max(min_factor, factor / 2)
  redis.call('HSET', KEYS[1], 'factor', tostring(factor),
             'hold_until', now + hold_ms, 'grown_at', now + hold_ms)
end
redis.call('PEXPIRE', KEYS[1], meta_ttl)
return math.floor(factor * 1000)
"""


def _log_key(window: RateWindow) -> str:
    return f"{window.key}:log"


def _meta_key(window: RateWindow) -> str:
    return f"{window.key}:meta"


class RedisRateWindows:
    """Takes units from windows in Redis. It does not wait: a caller that
    gets a wait decides how to sleep and when to stop."""

    def __init__(self, redis_client: TenantRedisClient) -> None:
        self._redis = redis_client

    def try_acquire(self, windows: Sequence[RateWindow], cost: int = 1) -> float:
        """Takes ``cost`` units from every window and returns 0, or takes
        nothing and returns the seconds until a full window has room. When
        Redis cannot be reached, the request is not limited."""
        if not windows:
            return 0
        keys: list[str] = []
        args: list[int | float] = [
            cost,
            int(GROW_INTERVAL_SECONDS * 1000),
            GROW_STEP,
            _META_TTL_SECONDS * 1000,
        ]
        for window in windows:
            keys.extend([_log_key(window), _meta_key(window)])
            args.extend([window.limit, int(window.period_seconds * 1000)])
        try:
            wait_ms = self._redis.eval(_ACQUIRE_SCRIPT, keys=keys, args=args)
        except RedisError:
            logger.warning(
                "The rate limiter cannot reach Redis; the request is not limited.",
                exc_info=True,
            )
            return 0
        return int(wait_ms) / 1000

    def cut(self, window: RateWindow) -> float:
        """Halves the share of its limit that the window allows, after the
        service pushed back. Returns the share, from MIN_BUDGET_FACTOR to 1."""
        try:
            thousandths = self._redis.eval(
                _CUT_SCRIPT,
                keys=[_meta_key(window)],
                args=[
                    MIN_BUDGET_FACTOR,
                    int(CUT_HOLD_SECONDS * 1000),
                    _META_TTL_SECONDS * 1000,
                ],
            )
        except RedisError:
            logger.warning("The rate limiter cannot reach Redis.", exc_info=True)
            return 1.0
        return int(thousandths) / 1000

    def delete(self, window: RateWindow) -> None:
        """Removes the window's state. For tests."""
        self._redis.delete(_log_key(window), _meta_key(window))
