"""Sliding-window budgets in Redis, shared by every worker.

A window allows ``limit`` units in any ``period_seconds``. A request has a
cost in units and can take from several windows in one atomic step, for
example a project budget and a user budget. The embedding limiter and the
source-API limiter use this one mechanism.

A window can also adapt. Each request that takes units counts, and the
caller reports each request that the service refused for its rate. When the
refused share of the recent requests passes a threshold, the share of its
limit that the window allows goes down: a little for a small refused share,
and a lot for a storm. The share then grows back in small steps while
requests go on, more slowly near the share of the last cut.
"""

import threading
import time
from collections.abc import Sequence

from pydantic import BaseModel, ConfigDict
from redis.exceptions import RedisError

from onyx.redis.redis_pool import TenantRedisClient
from onyx.utils.logger import setup_logger

logger = setup_logger()

# The refused share is measured over the requests of about this long.
REFUSAL_WINDOW_SECONDS = 30.0
# A cut needs this share of refused requests, and at least this many. One
# stray refusal among many requests does not cut.
CUT_THRESHOLD = 0.02
MIN_REFUSALS_TO_CUT = 10
# A refused share from this one up is a storm: the cut is hard.
STORM_SHARE = 0.10
# A cut multiplies the share by GENTLE_CUT, or in a storm by the lower of
# HARD_CUT and the share of requests that the service accepted.
GENTLE_CUT = 0.8
HARD_CUT = 0.5
# The lowest share of its limit that a cut can leave a window.
MIN_BUDGET_FACTOR = 0.1
# After a cut, hold the lower share this long before it grows or a gentle
# cut applies. This is longer than the time Google keeps refusing after a
# burst, so one burst makes one cut.
CUT_HOLD_SECONDS = 60.0
# In a hold, a storm can cut again after this long. The cut resets the
# refused share, so the next decision sees only answers to the lower rate.
STORM_RECUT_SECONDS = 10.0
# The share grows by GROW_STEP each interval after the hold, and by
# SLOW_GROW_STEP from SLOW_ZONE times the share of the last cut up to it.
GROW_STEP = 0.05
SLOW_GROW_STEP = 0.005
SLOW_ZONE = 0.9
GROW_INTERVAL_SECONDS = 10.0
# While Redis cannot be reached, log one warning in each interval.
_UNREACHABLE_WARNING_INTERVAL_SECONDS = 60.0
# The adaptive state outlives an idle window by this long.
_META_TTL_SECONDS = 600


class AcquireResult(BaseModel):
    # 0 when the request took its units, or the seconds until a full window
    # has room.
    wait_seconds: float
    # The share of its limit that each window allows, in the order of the
    # windows. Empty when Redis cannot be reached.
    shares: list[float]


class RefusalResult(BaseModel):
    # The share of its limit that the window allows, from MIN_BUDGET_FACTOR
    # to 1.
    share: float
    # True when this report cut the share.
    applied: bool
    # True when the cut was a storm cut.
    hard: bool
    # The refused share of the recent requests, with this report.
    refused_share: float


class RateWindow(BaseModel):
    """One budget: ``limit`` units in any ``period_seconds``."""

    model_config = ConfigDict(frozen=True)

    key: str
    limit: int
    period_seconds: float


# Each window has a log (a sorted set of requests by start time, with the cost
# in the member) and a meta hash (the running total and the adaptive state).
# The scripts read the Redis clock, so clock skew between pods has no effect.
#
# The meta hash also counts requests and refusals for the refused share, in
# two buckets of the refusal window: the current one and the one before. The
# estimate weighs the bucket before by the part of it that is still inside
# the window.
_ROLL_FUNCTIONS = """
local function roll(meta, now, window_ms)
  local at = tonumber(redis.call('HGET', meta, 'bucket_at') or '0')
  if now - at >= 2 * window_ms then
    redis.call('HSET', meta, 'bucket_at', now, 'req_prev', 0, 'ref_prev', 0,
               'req_cur', 0, 'ref_cur', 0)
  elseif now - at >= window_ms then
    local req = redis.call('HGET', meta, 'req_cur') or '0'
    local ref = redis.call('HGET', meta, 'ref_cur') or '0'
    redis.call('HSET', meta, 'bucket_at', at + window_ms, 'req_prev', req,
               'ref_prev', ref, 'req_cur', 0, 'ref_cur', 0)
  end
end
local function estimate(meta, now, window_ms, prefix)
  local at = tonumber(redis.call('HGET', meta, 'bucket_at') or '0')
  local weight = math.max(0, 1 - (now - at) / window_ms)
  local prev = tonumber(redis.call('HGET', meta, prefix .. '_prev') or '0')
  local cur = tonumber(redis.call('HGET', meta, prefix .. '_cur') or '0')
  return prev * weight + cur
end
"""

# Returns a list: first 0 when the request took its units from every window,
# or, if one window is full, the ms until that window's oldest request leaves
# (it then takes nothing). Then the share of its limit that each window
# allows, in thousandths. A request that took its units counts ``requests``
# toward the refused share of each window.
_ACQUIRE_SCRIPT = (
    _ROLL_FUNCTIONS
    + """
local t = redis.call('TIME')
local now = tonumber(t[1]) * 1000 + math.floor(tonumber(t[2]) / 1000)
local cost = tonumber(ARGV[1])
local requests = tonumber(ARGV[2])
local grow_ms = tonumber(ARGV[3])
local grow_step = tonumber(ARGV[4])
local slow_step = tonumber(ARGV[5])
local slow_zone = tonumber(ARGV[6])
local window_ms = tonumber(ARGV[7])
local meta_ttl = tonumber(ARGV[8])
local n = #KEYS / 2
local wait = 0
local shares = {}
for i = 1, n do
  local log = KEYS[2 * i - 1]
  local meta = KEYS[2 * i]
  local limit = tonumber(ARGV[7 + 2 * i])
  local period = tonumber(ARGV[8 + 2 * i])
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
      local ceiling = tonumber(redis.call('HGET', meta, 'ceiling') or '1')
      local step = grow_step
      if factor >= ceiling * slow_zone and factor < ceiling then
        step = slow_step
      end
      factor = math.min(1, factor + step)
      redis.call('HSET', meta, 'factor', tostring(factor), 'grown_at', now)
      if factor >= ceiling then
        redis.call('HDEL', meta, 'ceiling')
      end
    end
  end
  shares[i] = math.floor(factor * 1000 + 0.5)
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
  return {wait, unpack(shares)}
end
for i = 1, n do
  local log = KEYS[2 * i - 1]
  local meta = KEYS[2 * i]
  local period = tonumber(ARGV[8 + 2 * i])
  local seq = redis.call('HINCRBY', meta, 'seq', 1)
  redis.call('ZADD', log, now, now .. ':' .. seq .. ':' .. cost)
  redis.call('HINCRBY', meta, 'total', cost)
  roll(meta, now, window_ms)
  redis.call('HINCRBY', meta, 'req_cur', requests)
  redis.call('PEXPIRE', log, period)
  redis.call('PEXPIRE', meta, math.max(period, meta_ttl))
end
return {0, unpack(shares)}
"""
)

# Counts ``count`` refused requests, and cuts the window's share when the
# refused share of the recent requests passes the threshold. A gentle cut
# waits for the hold of the last cut; a storm cut waits only for the storm
# re-cut time. A cut resets the counts. Returns the share in thousandths,
# 0 (no cut), 1 (gentle cut) or 2 (storm cut), and the refused share in
# thousandths.
_REPORT_SCRIPT = (
    _ROLL_FUNCTIONS
    + """
local t = redis.call('TIME')
local now = tonumber(t[1]) * 1000 + math.floor(tonumber(t[2]) / 1000)
local meta = KEYS[1]
local count = tonumber(ARGV[1])
local threshold = tonumber(ARGV[2])
local min_refusals = tonumber(ARGV[3])
local storm_share = tonumber(ARGV[4])
local gentle = tonumber(ARGV[5])
local hard = tonumber(ARGV[6])
local min_factor = tonumber(ARGV[7])
local hold_ms = tonumber(ARGV[8])
local recut_ms = tonumber(ARGV[9])
local window_ms = tonumber(ARGV[10])
local meta_ttl = tonumber(ARGV[11])
local period = tonumber(ARGV[12])
roll(meta, now, window_ms)
redis.call('HINCRBY', meta, 'ref_cur', count)
local refused = estimate(meta, now, window_ms, 'ref')
-- A refusal can answer a request counted before the last reset.
local requests = math.max(refused, estimate(meta, now, window_ms, 'req'))
local refused_share = 0
if requests > 0 then
  refused_share = refused / requests
end
local factor = tonumber(redis.call('HGET', meta, 'factor') or '1')
local applied = 0
if refused >= min_refusals and refused_share >= threshold then
  local hold_until = tonumber(redis.call('HGET', meta, 'hold_until') or '0')
  local last_cut = tonumber(redis.call('HGET', meta, 'last_cut') or '0')
  local storm = refused_share >= storm_share
  if now >= hold_until or (storm and now >= last_cut + recut_ms) then
    local multiplier = gentle
    applied = 1
    if storm then
      multiplier = math.min(hard, 1 - refused_share)
      applied = 2
    end
    redis.call('HSET', meta, 'ceiling', tostring(factor))
    factor = math.max(min_factor, factor * multiplier)
    redis.call('HSET', meta, 'factor', tostring(factor),
               'hold_until', now + hold_ms, 'grown_at', now + hold_ms,
               'last_cut', now, 'bucket_at', now, 'req_prev', 0,
               'ref_prev', 0, 'req_cur', 0, 'ref_cur', 0)
  end
end
-- The running total in the meta hash must live as long as the log.
redis.call('PEXPIRE', meta, math.max(period, meta_ttl))
return {math.floor(factor * 1000 + 0.5), applied,
        math.floor(refused_share * 1000 + 0.5)}
"""
)


_last_unreachable_warning = 0.0
_unreachable_warning_lock = threading.Lock()


def _warn_redis_unreachable(error: RedisError) -> None:
    """Every call fails while Redis is down, so log at most once in each
    interval."""
    global _last_unreachable_warning
    now = time.monotonic()
    with _unreachable_warning_lock:
        if now - _last_unreachable_warning < _UNREACHABLE_WARNING_INTERVAL_SECONDS:
            return
        _last_unreachable_warning = now
    logger.warning(
        "The rate limiter cannot reach Redis; requests are not limited: %s", error
    )


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
        return self.try_acquire_with_shares(windows, cost).wait_seconds

    def try_acquire_with_shares(
        self, windows: Sequence[RateWindow], cost: int = 1, requests: int = 1
    ) -> AcquireResult:
        """``try_acquire``, which also returns the share of its limit that
        each window allows now. ``requests`` is the number of requests that
        the units pay for, which the refused share counts."""
        if not windows:
            return AcquireResult(wait_seconds=0, shares=[])
        keys: list[str] = []
        args: list[int | float] = [
            cost,
            requests,
            int(GROW_INTERVAL_SECONDS * 1000),
            GROW_STEP,
            SLOW_GROW_STEP,
            SLOW_ZONE,
            int(REFUSAL_WINDOW_SECONDS * 1000),
            _META_TTL_SECONDS * 1000,
        ]
        for window in windows:
            keys.extend([_log_key(window), _meta_key(window)])
            args.extend([window.limit, int(window.period_seconds * 1000)])
        try:
            result = self._redis.eval(_ACQUIRE_SCRIPT, keys=keys, args=args)
        except RedisError as error:
            _warn_redis_unreachable(error)
            return AcquireResult(wait_seconds=0, shares=[])
        wait_ms, *thousandths = (int(value) for value in result)
        return AcquireResult(
            wait_seconds=wait_ms / 1000,
            shares=[value / 1000 for value in thousandths],
        )

    def report_refusals(self, window: RateWindow, count: int = 1) -> RefusalResult:
        """Counts ``count`` requests that the service refused for its rate,
        and cuts the window's share when the refused share of the recent
        requests passes the threshold."""
        try:
            thousandths, applied, refused_thousandths = self._redis.eval(
                _REPORT_SCRIPT,
                keys=[_meta_key(window)],
                args=[
                    count,
                    CUT_THRESHOLD,
                    MIN_REFUSALS_TO_CUT,
                    STORM_SHARE,
                    GENTLE_CUT,
                    HARD_CUT,
                    MIN_BUDGET_FACTOR,
                    int(CUT_HOLD_SECONDS * 1000),
                    int(STORM_RECUT_SECONDS * 1000),
                    int(REFUSAL_WINDOW_SECONDS * 1000),
                    _META_TTL_SECONDS * 1000,
                    int(window.period_seconds * 1000),
                ],
            )
        except RedisError as error:
            _warn_redis_unreachable(error)
            return RefusalResult(
                share=1.0, applied=False, hard=False, refused_share=0.0
            )
        return RefusalResult(
            share=int(thousandths) / 1000,
            applied=int(applied) > 0,
            hard=int(applied) == 2,
            refused_share=int(refused_thousandths) / 1000,
        )

    def delete(self, window: RateWindow) -> None:
        """Removes the window's state. For tests."""
        self._redis.delete(_log_key(window), _meta_key(window))
