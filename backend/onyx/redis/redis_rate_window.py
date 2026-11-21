"""Sliding-window budgets in Redis, shared by every worker.

A window allows ``limit`` units in any ``period_seconds``. A request has a
cost in units and can take from several windows in one atomic step, for
example a project budget and a user budget. The embedding limiter and the
source-API limiter use this one mechanism.

Callers that wait take turns. A caller that does not fit a full window gets a
place in the window's queue, and a later caller cannot take the room that the
callers before it wait for. Priority callers go before bulk callers, and the
callers of one class go in the order they came. Bulk callers also leave a
small share of each window free for priority callers, so a priority caller
seldom waits at all. So a few listing or sync calls do not starve behind many
conversion threads, and no caller waits for ever behind newer ones.

A window can also adapt. Each request that takes units counts, and the caller
reports each request that the service refused for its rate. When the refused
share of the recent requests passes a threshold, the share of its limit that
the window allows goes down. Each cut starts a new epoch. A refusal of a
request that took its units before the cut does not count toward the next
cut, so one burst of refusals gives one cut.

A cut does not go much below the share that the service accepted: the share
of the window that the recent requests used, less the refused share. That
accepted share is the ceiling, which also keeps most of the last ceiling.
The share grows back fast below SLOW_ZONE of
the ceiling and slowly from there. When the share grows past the ceiling
with no new cut, the ceiling moves up with it, so the window finds a higher
rate when the service allows more.

A window with a start share keeps its share past an idle time. It stores its
share in Redis whenever the share changes, for STORED_SHARE_TTL_SECONDS. A
window with no state, for example in a new run, starts from the stored share
and grows slowly from it. With no stored share, it starts from its start
share, and that share is its ceiling. It also grows slowly, because a fast
growth from a cold start passes the rate of the service in a few minutes.

A pause is a separate key that holds the time when it ends. A service that
answers with a wait time (Retry-After) asks every caller to stop, so each
caller reads the pause before it sends a request.

One try does a small, bounded amount of work, whatever the number of
requests in the window. Each request in the log carries the units of the log
up to it, so a search by rank finds when enough units leave the window. A try
reads at most _MAX_SCAN waiters before its place.
"""

import threading
import time
from collections.abc import Sequence
from enum import Enum

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
# A refused share from this one up is a storm: the cut can be hard.
STORM_SHARE = 0.10
# A cut multiplies the share by GENTLE_CUT, or in a storm by the lower of
# HARD_CUT and the share of requests that the service accepted. The cut does
# not go below (1 - CUT_MARGIN) of the accepted share, and it takes at least
# (1 - SMALLEST_CUT) off the share.
GENTLE_CUT = 0.8
HARD_CUT = 0.5
CUT_MARGIN = 0.1
SMALLEST_CUT = 0.95
# At a cut, the ceiling keeps at least this share of the last ceiling. A
# second cut in a storm can see a low accepted share while the service still
# refuses after the burst; the ceiling then remembers the rate before it.
CEILING_KEEP = 0.8
# The lowest share of its limit that a cut can leave a window.
MIN_BUDGET_FACTOR = 0.1
# After a cut, hold the lower share this long before it grows or a gentle
# cut applies.
CUT_HOLD_SECONDS = 60.0
# In a hold, a storm of refusals for requests sent after the cut can cut
# again after this long.
STORM_RECUT_SECONDS = 10.0
# The share grows by GROW_STEP each interval after the hold, and by
# SLOW_GROW_STEP from SLOW_ZONE times the ceiling up.
GROW_STEP = 0.05
SLOW_GROW_STEP = 0.005
SLOW_ZONE = 0.8
GROW_INTERVAL_SECONDS = 10.0
# Bulk callers leave this share of each window to priority callers.
PRIORITY_RESERVE = 0.05
# A waiter that has not tried again for this long leaves the queue, for
# example when its process died. A waiting caller tries at least every
# WAITER_STALE_SECONDS / 2.
WAITER_STALE_SECONDS = 20.0
# While Redis cannot be reached, log one warning in each interval.
_UNREACHABLE_WARNING_INTERVAL_SECONDS = 60.0
# The adaptive state outlives an idle window by this long.
_META_TTL_SECONDS = 600
# A stored share outlives its last change by this long.
STORED_SHARE_TTL_SECONDS = 7 * 24 * 3600
# Bulk waiters sort after every priority waiter: the place of a waiter is the
# time of its first try in ms, plus this for a bulk waiter.
_BULK_RANK_OFFSET_MS = 10**13
# One try reads at most this many waiters before its place. The calls of one
# process wait behind one waiter (see the source-API limiter), so a queue
# holds about one waiter for each process and class.
_MAX_SCAN = 128


class WindowStart(int, Enum):
    """Where a window's share came from, when a try found it with no state."""

    # The window had state, or it does not store its share.
    NONE = 0
    # The share that the window stored.
    STORED = 1
    # No share was stored: the window's start share.
    COLD = 2


class AcquireResult(BaseModel):
    # 0 when the request took its units, or the seconds until the window
    # that is full can have room for it.
    wait_seconds: float
    # The share of its limit that each window allows, in the order of the
    # windows. Empty when Redis cannot be reached.
    shares: list[float]
    # The epoch (the number of cuts) of each window, in the order of the
    # windows. Empty when Redis cannot be reached.
    epochs: list[int]
    # For each window, True when the request did not fit it. Empty when Redis
    # cannot be reached.
    blocked: list[bool] = []
    # For each window, where its share came from when this try found it with
    # no state.
    starts: list[WindowStart] = []
    # The number of waiters in the queue of each window after this try.
    queued: list[int] = []


class RefusalResult(BaseModel):
    # The share of its limit that the window allows, from MIN_BUDGET_FACTOR
    # to 1.
    share: float
    # True when this report cut the share.
    applied: bool
    # True when the cut was a storm cut.
    hard: bool
    # The refused share of the requests of this epoch, with this report.
    refused_share: float
    # True when the refused requests took their units before the last cut.
    # Such a report does not count toward a cut.
    late: bool = False
    # At a cut, the share of its limit that the service accepted, and the
    # ceiling from it.
    accepted_share: float = 0.0
    ceiling: float = 0.0


class RateWindow(BaseModel):
    """One budget: ``limit`` units in any ``period_seconds``."""

    model_config = ConfigDict(frozen=True)

    key: str
    limit: int
    period_seconds: float
    # With a start share, the window stores its share, and a window with no
    # state starts from the stored share, or from this share when none is
    # stored. None starts at the full limit and stores nothing.
    start_share: float | None = None


class WaitTurn(BaseModel):
    """A caller's place in the queues of the windows while it waits. Each
    call that can wait has its own token."""

    model_config = ConfigDict(frozen=True)

    token: str
    # A bulk caller goes after every priority caller.
    bulk: bool = False


# Each window has a log (a sorted set of requests by start time; the member
# holds the units of the log up to the request and the request's cost), a
# meta hash (the running total and the adaptive state), a queue (a sorted set
# of waiters by place, with the cost in the member), a seen set (the waiters
# by the time of their last try) and the stored share. The scripts read the
# Redis clock, so clock skew between pods has no effect.
#
# The meta hash counts the requests and the refusals of the current epoch for
# the refused share, in two buckets of the refusal window: the current one and
# the one before. The estimate weighs the bucket before by the part of it that
# is still inside the window.
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
local function member_cost(member)
  return tonumber(string.match(member, ':(%d+)$'))
end
-- The units of the log up to and with this request, or nil for a member of
-- the older form, which has no such count.
local function member_units(member)
  local units = string.match(member, '^%d+:%d+:(%d+):%d+$')
  if units then
    return tonumber(units)
  end
  return nil
end
local function store_share(stored, factor, ttl)
  redis.call('SET', stored, tostring(factor), 'PX', ttl)
end
"""

# Returns a list: first 0 when the request took its units from every window,
# or the ms until the window that is full can have room for it (it then takes
# nothing). Then five values for each window: the share of its limit that it
# allows in thousandths, its epoch, 1 when the request did not fit it, its
# WindowStart, and the number of waiters in its queue. A request that took
# its units counts ``requests`` toward the refused share of each window.
#
# A caller fits a window when its cost and the costs of the waiters before it
# fit the room in the window; a bulk caller does not use the reserve of the
# priority callers. A caller with no place yet goes after every waiter of its
# class. A caller that does not fit gets a place in the queue
# of each window that it did not fit. ``force`` takes the units with no
# check.
#
# The wait is until enough units leave the window. The units of the log up
# to each request rise with its rank, so a binary search over the ranks finds
# the request whose exit frees them, in O(log n) reads.
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
local member = ARGV[9]
local rank_offset = tonumber(ARGV[10])
local stale_ms = tonumber(ARGV[11])
local force = ARGV[12] == '1'
local max_scan = tonumber(ARGV[13])
local reserve = tonumber(ARGV[14])
local stored_ttl = tonumber(ARGV[15])
local base = 15
local n = #KEYS / 5
local wait = 0
local shares = {}
local epochs = {}
local blocked = {}
local starts = {}
local places = {}
local function at_rank(log, rank)
  return redis.call('ZRANGE', log, rank, rank, 'WITHSCORES')
end
-- The ms until ``need`` units have left the log, or the period when the log
-- does not hold them.
local function wait_for_units(log, need, period)
  local card = redis.call('ZCARD', log)
  if card == 0 then
    return period
  end
  local first = at_rank(log, 0)
  local first_units = member_units(first[1])
  if not first_units then
    -- A log of the older form: one unit for each request.
    if need > card then
      return period
    end
    return tonumber(at_rank(log, need - 1)[2]) + period - now
  end
  local before = first_units - member_cost(first[1])
  local last_units = member_units(at_rank(log, card - 1)[1])
  if not last_units or last_units - before < need then
    return period
  end
  local lo = 0
  local hi = card - 1
  while lo < hi do
    local mid = math.floor((lo + hi) / 2)
    local units = member_units(at_rank(log, mid)[1])
    if units and units - before >= need then
      hi = mid
    else
      lo = mid + 1
    end
  end
  return tonumber(at_rank(log, lo)[2]) + period - now
end
for i = 1, n do
  local log = KEYS[5 * i - 4]
  local meta = KEYS[5 * i - 3]
  local queue = KEYS[5 * i - 2]
  local seen = KEYS[5 * i - 1]
  local stored = KEYS[5 * i]
  local limit = tonumber(ARGV[base + 3 * i - 2])
  local period = tonumber(ARGV[base + 3 * i - 1])
  local start_share = tonumber(ARGV[base + 3 * i])
  local old = redis.call('ZRANGEBYSCORE', log, '-inf', now - period)
  if #old > 0 then
    local freed = 0
    for _, entry in ipairs(old) do
      freed = freed + member_cost(entry)
    end
    redis.call('ZREMRANGEBYSCORE', log, '-inf', now - period)
    redis.call('HINCRBY', meta, 'total', -freed)
  end
  local total = tonumber(redis.call('HGET', meta, 'total') or '0')
  if redis.call('ZCARD', log) == 0 and total ~= 0 then
    total = 0
    redis.call('HSET', meta, 'total', 0)
  end
  starts[i] = 0
  local factor_value = redis.call('HGET', meta, 'factor')
  local factor = 1
  if factor_value then
    factor = tonumber(factor_value)
  elseif start_share >= 0 then
    -- No state: start from the stored share, or from the start share.
    local stored_share = redis.call('GET', stored)
    if stored_share then
      factor = math.min(1, tonumber(stored_share))
      starts[i] = 1
      redis.call('HSET', meta, 'factor', tostring(factor), 'grown_at', now)
      if factor < 1 then
        -- The service accepted the stored share: grow slowly from it.
        redis.call('HSET', meta, 'ceiling', tostring(factor))
      end
    else
      factor = start_share
      starts[i] = 2
      redis.call('HSET', meta, 'factor', tostring(factor), 'grown_at', now)
      if factor < 1 then
        -- The service accepted no share yet: the start share is the
        -- ceiling, so the window grows slowly from it.
        redis.call('HSET', meta, 'ceiling', tostring(factor))
      end
    end
    redis.call('PEXPIRE', meta, math.max(period, meta_ttl))
  end
  if factor < 1 then
    local hold_until = tonumber(redis.call('HGET', meta, 'hold_until') or '0')
    local grown_at = tonumber(redis.call('HGET', meta, 'grown_at') or '0')
    if now >= hold_until and now - grown_at >= grow_ms then
      local ceiling = tonumber(redis.call('HGET', meta, 'ceiling') or '2')
      local step = grow_step
      if factor >= ceiling * slow_zone then
        step = slow_step
      end
      factor = math.min(1, factor + step)
      redis.call('HSET', meta, 'factor', tostring(factor), 'grown_at', now)
      if factor >= 1 then
        redis.call('HDEL', meta, 'ceiling')
      elseif factor > ceiling then
        -- No cut up to here: the service allows this share, so the
        -- ceiling moves up with it.
        redis.call('HSET', meta, 'ceiling', tostring(factor))
      end
      if start_share >= 0 then
        store_share(stored, factor, stored_ttl)
      end
    end
  end
  shares[i] = math.floor(factor * 1000 + 0.5)
  epochs[i] = tonumber(redis.call('HGET', meta, 'epoch') or '0')
  -- Waiters that stopped trying leave the queue.
  for _, gone in ipairs(redis.call('ZRANGEBYSCORE', seen, '-inf',
                                   now - stale_ms)) do
    redis.call('ZREM', queue, gone)
    redis.call('ZREM', seen, gone)
  end
  local place = nil
  if member ~= '' then
    place = redis.call('ZSCORE', queue, member)
  end
  if place then
    place = tonumber(place)
  else
    place = now + rank_offset
  end
  places[i] = place
  blocked[i] = false
  if not force then
    -- One request always fits an empty window, however large its cost.
    local allowed = math.max(cost, math.floor(limit * factor * (1 - reserve)))
    local ahead = 0
    if redis.call('ZCARD', queue) > 0 then
      for _, before in ipairs(redis.call('ZRANGEBYSCORE', queue, '-inf',
                                         '(' .. place, 'LIMIT', 0, max_scan)) do
        ahead = ahead + member_cost(before)
      end
    end
    if total + cost + ahead > allowed then
      blocked[i] = true
      -- The units that must leave the window before this caller fits. The
      -- wait is until the oldest requests that hold them leave.
      local window_wait = wait_for_units(log, total + cost + ahead - allowed,
                                         period)
      wait = math.max(wait, math.max(1, window_wait))
    end
  end
end
local function result()
  local values = {wait}
  for i = 1, n do
    local is_blocked = 0
    if blocked[i] then
      is_blocked = 1
    end
    values[#values + 1] = shares[i]
    values[#values + 1] = epochs[i]
    values[#values + 1] = is_blocked
    values[#values + 1] = starts[i]
    values[#values + 1] = redis.call('ZCARD', KEYS[5 * i - 2])
  end
  return values
end
if wait > 0 then
  if member ~= '' then
    for i = 1, n do
      local queue = KEYS[5 * i - 2]
      local seen = KEYS[5 * i - 1]
      local period = tonumber(ARGV[base + 3 * i - 1])
      if blocked[i] then
        redis.call('ZADD', queue, 'NX', places[i], member)
      end
      if redis.call('ZSCORE', queue, member) then
        redis.call('ZADD', seen, now, member)
        local ttl = 2 * math.max(period, stale_ms)
        redis.call('PEXPIRE', queue, ttl)
        redis.call('PEXPIRE', seen, ttl)
      end
    end
  end
  return result()
end
for i = 1, n do
  local log = KEYS[5 * i - 4]
  local meta = KEYS[5 * i - 3]
  local period = tonumber(ARGV[base + 3 * i - 1])
  if member ~= '' then
    redis.call('ZREM', KEYS[5 * i - 2], member)
    redis.call('ZREM', KEYS[5 * i - 1], member)
  end
  local seq = redis.call('HINCRBY', meta, 'seq', 1)
  local units = redis.call('HINCRBY', meta, 'units', cost)
  redis.call('ZADD', log, now, now .. ':' .. seq .. ':' .. units .. ':' .. cost)
  redis.call('HINCRBY', meta, 'total', cost)
  roll(meta, now, window_ms)
  redis.call('HINCRBY', meta, 'req_cur', requests)
  redis.call('PEXPIRE', log, period)
  redis.call('PEXPIRE', meta, math.max(period, meta_ttl))
end
return result()
"""
)

# Removes a waiter from the queue and the seen set of each window.
_LEAVE_SCRIPT = """
for i = 1, #KEYS, 2 do
  redis.call('ZREM', KEYS[i], ARGV[1])
  redis.call('ZREM', KEYS[i + 1], ARGV[1])
end
return 0
"""

# Counts ``count`` refused requests, and cuts the window's share when the
# refused share of the requests of this epoch passes the threshold. A refusal
# of a request from an earlier epoch is late: it does not count. A gentle cut
# waits for the hold of the last cut; a storm cut waits only for the storm
# re-cut time. A cut starts a new epoch and resets the counts. Returns the
# share in thousandths, 0 (no cut), 1 (gentle cut) or 2 (storm cut), the
# refused share in thousandths, 1 when the report was late, and the accepted
# share and the ceiling in thousandths (0 with no cut). A window that stores
# its share stores the share after a cut.
_REPORT_SCRIPT = (
    _ROLL_FUNCTIONS
    + """
local t = redis.call('TIME')
local now = tonumber(t[1]) * 1000 + math.floor(tonumber(t[2]) / 1000)
local meta = KEYS[1]
local stored = KEYS[2]
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
local limit = tonumber(ARGV[13])
local sent_epoch = tonumber(ARGV[14])
local margin = tonumber(ARGV[15])
local smallest = tonumber(ARGV[16])
local keep = tonumber(ARGV[17])
local stored_ttl = tonumber(ARGV[18])
local stores = ARGV[19] == '1'
local factor = tonumber(redis.call('HGET', meta, 'factor') or '1')
local epoch = tonumber(redis.call('HGET', meta, 'epoch') or '0')
-- The running total in the meta hash must live as long as the log.
redis.call('PEXPIRE', meta, math.max(period, meta_ttl))
if sent_epoch >= 0 and sent_epoch < epoch then
  return {math.floor(factor * 1000 + 0.5), 0, 0, 1, 0, 0}
end
roll(meta, now, window_ms)
redis.call('HINCRBY', meta, 'ref_cur', count)
local refused = estimate(meta, now, window_ms, 'ref')
-- A refusal can answer a request whose epoch the caller did not know.
local requests = math.max(refused, estimate(meta, now, window_ms, 'req'))
local refused_share = 0
if requests > 0 then
  refused_share = refused / requests
end
local applied = 0
local accepted = 0
local ceiling = 0
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
    -- The share that the service accepted: the share of the window that the
    -- recent requests used, less the refused share.
    local total = tonumber(redis.call('HGET', meta, 'total') or '0')
    accepted = math.min(1, total / math.max(1, limit)) * (1 - refused_share)
    local cut = math.max(factor * multiplier, accepted * (1 - margin))
    cut = math.max(min_factor, math.min(cut, factor * smallest))
    local last_ceiling = tonumber(redis.call('HGET', meta, 'ceiling') or '0')
    ceiling = math.max(accepted, cut, last_ceiling * keep)
    factor = cut
    redis.call('HSET', meta, 'factor', tostring(factor),
               'ceiling', tostring(ceiling),
               'epoch', epoch + 1, 'hold_until', now + hold_ms,
               'grown_at', now + hold_ms, 'last_cut', now, 'bucket_at', now,
               'req_prev', 0, 'ref_prev', 0, 'req_cur', 0, 'ref_cur', 0)
    if stores then
      store_share(stored, factor, stored_ttl)
    end
  end
end
return {math.floor(factor * 1000 + 0.5), applied,
        math.floor(refused_share * 1000 + 0.5), 0,
        math.floor(accepted * 1000 + 0.5), math.floor(ceiling * 1000 + 0.5)}
"""
)

# Sets a pause that ends ``ARGV[1]`` ms from now, unless the stored pause ends
# later. Returns the ms until the pause ends.
_PAUSE_SCRIPT = """
local t = redis.call('TIME')
local now = tonumber(t[1]) * 1000 + math.floor(tonumber(t[2]) / 1000)
local until_ms = now + tonumber(ARGV[1])
local current = tonumber(redis.call('GET', KEYS[1]) or '0')
if until_ms > current then
  redis.call('SET', KEYS[1], tostring(until_ms), 'PX', tonumber(ARGV[1]))
  current = until_ms
end
return math.max(0, current - now)
"""

# Returns the ms until the pause ends, or 0 with no pause.
_PAUSE_LEFT_SCRIPT = """
local t = redis.call('TIME')
local now = tonumber(t[1]) * 1000 + math.floor(tonumber(t[2]) / 1000)
local current = tonumber(redis.call('GET', KEYS[1]) or '0')
return math.max(0, current - now)
"""

# Takes ``ARGV[1]`` units from a budget of ``ARGV[2]`` units for 24 hours and
# returns 0, or takes nothing and returns the seconds until the next hour.
# The key is a hash of the units of each hour, so its size does not grow with
# the number of requests. The day counts the current hour and the 24 hours
# before it, so no unit leaves before it is 24 hours old. One request always
# fits an empty day.
_DAY_SCRIPT = """
local t = redis.call('TIME')
local now = tonumber(t[1])
local hour = math.floor(now / 3600)
local cost = tonumber(ARGV[1])
local limit = tonumber(ARGV[2])
local total = 0
local hours = redis.call('HGETALL', KEYS[1])
for i = 1, #hours, 2 do
  if tonumber(hours[i]) < hour - 24 then
    redis.call('HDEL', KEYS[1], hours[i])
  else
    total = total + tonumber(hours[i + 1])
  end
end
if total > 0 and total + cost > limit then
  return (hour + 1) * 3600 - now
end
redis.call('HINCRBY', KEYS[1], tostring(hour), cost)
redis.call('EXPIRE', KEYS[1], 26 * 3600)
return 0
"""


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


def _queue_key(window: RateWindow) -> str:
    return f"{window.key}:queue"


def _seen_key(window: RateWindow) -> str:
    return f"{window.key}:seen"


def stored_share_key(window: RateWindow) -> str:
    """The key of the share that a window with a start share stores."""
    return f"{window.key}:learned"


def _member(turn: WaitTurn, cost: int) -> str:
    # The member carries the cost, so that the callers after it know the
    # units that it waits for.
    return f"{turn.token}:{max(1, cost)}"


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
        self,
        windows: Sequence[RateWindow],
        cost: int = 1,
        requests: int = 1,
        turn: WaitTurn | None = None,
        force: bool = False,
    ) -> AcquireResult:
        """``try_acquire``, which also returns the state of each window: its
        share of its limit, its epoch, whether the request fit it, where its
        share came from, and its waiters. ``requests`` is the number of
        requests that the units pay for, which the refused share counts.
        With ``turn``, a caller that does not fit keeps a place in the queue
        of each full window until it fits or calls ``leave``. With no turn,
        the caller goes after every waiter. ``force`` takes the units even
        when they do not fit."""
        if not windows:
            return AcquireResult(wait_seconds=0, shares=[], epochs=[])
        keys: list[str] = []
        args: list[str] = [
            str(cost),
            str(requests),
            str(int(GROW_INTERVAL_SECONDS * 1000)),
            str(GROW_STEP),
            str(SLOW_GROW_STEP),
            str(SLOW_ZONE),
            str(int(REFUSAL_WINDOW_SECONDS * 1000)),
            str(_META_TTL_SECONDS * 1000),
            _member(turn, cost) if turn is not None else "",
            str(0 if turn is not None and not turn.bulk else _BULK_RANK_OFFSET_MS),
            str(int(WAITER_STALE_SECONDS * 1000)),
            "1" if force else "0",
            str(_MAX_SCAN),
            str(PRIORITY_RESERVE if turn is not None and turn.bulk else 0),
            str(STORED_SHARE_TTL_SECONDS * 1000),
        ]
        for window in windows:
            keys.extend(
                [
                    _log_key(window),
                    _meta_key(window),
                    _queue_key(window),
                    _seen_key(window),
                    stored_share_key(window),
                ]
            )
            args.extend(
                [
                    str(window.limit),
                    str(int(window.period_seconds * 1000)),
                    str(-1 if window.start_share is None else window.start_share),
                ]
            )
        try:
            result = self._redis.eval(_ACQUIRE_SCRIPT, keys=keys, args=args)
        except RedisError as error:
            _warn_redis_unreachable(error)
            return AcquireResult(wait_seconds=0, shares=[], epochs=[])
        values = [int(value) for value in result]
        per_window = [values[1 + 5 * i : 6 + 5 * i] for i in range(len(windows))]
        return AcquireResult(
            wait_seconds=values[0] / 1000,
            shares=[state[0] / 1000 for state in per_window],
            epochs=[state[1] for state in per_window],
            blocked=[state[2] == 1 for state in per_window],
            starts=[WindowStart(state[3]) for state in per_window],
            queued=[state[4] for state in per_window],
        )

    def leave(self, windows: Sequence[RateWindow], turn: WaitTurn, cost: int) -> None:
        """Gives up the caller's place in the queue of each window, for a
        caller that stops waiting. A place that is not given up expires."""
        if not windows:
            return
        keys: list[str] = []
        for window in windows:
            keys.extend([_queue_key(window), _seen_key(window)])
        try:
            self._redis.eval(_LEAVE_SCRIPT, keys=keys, args=[_member(turn, cost)])
        except RedisError as error:
            _warn_redis_unreachable(error)

    def report_refusals(
        self, window: RateWindow, count: int = 1, epoch: int | None = None
    ) -> RefusalResult:
        """Counts ``count`` requests that the service refused for its rate,
        and cuts the window's share when the refused share of the recent
        requests passes the threshold. ``epoch`` is the window's epoch when
        the refused requests took their units; refusals from an earlier epoch
        do not count. None counts them in the current epoch."""
        try:
            result = self._redis.eval(
                _REPORT_SCRIPT,
                keys=[_meta_key(window), stored_share_key(window)],
                args=[
                    str(count),
                    str(CUT_THRESHOLD),
                    str(MIN_REFUSALS_TO_CUT),
                    str(STORM_SHARE),
                    str(GENTLE_CUT),
                    str(HARD_CUT),
                    str(MIN_BUDGET_FACTOR),
                    str(int(CUT_HOLD_SECONDS * 1000)),
                    str(int(STORM_RECUT_SECONDS * 1000)),
                    str(int(REFUSAL_WINDOW_SECONDS * 1000)),
                    str(_META_TTL_SECONDS * 1000),
                    str(int(window.period_seconds * 1000)),
                    str(window.limit),
                    str(-1 if epoch is None else epoch),
                    str(CUT_MARGIN),
                    str(SMALLEST_CUT),
                    str(CEILING_KEEP),
                    str(STORED_SHARE_TTL_SECONDS * 1000),
                    "0" if window.start_share is None else "1",
                ],
            )
        except RedisError as error:
            _warn_redis_unreachable(error)
            return RefusalResult(
                share=1.0, applied=False, hard=False, refused_share=0.0
            )
        thousandths, applied, refused_thousandths, late, accepted, ceiling = (
            int(value) for value in result
        )
        return RefusalResult(
            share=thousandths / 1000,
            applied=applied > 0,
            hard=applied == 2,
            refused_share=refused_thousandths / 1000,
            late=late == 1,
            accepted_share=accepted / 1000,
            ceiling=ceiling / 1000,
        )

    def pause(self, key: str, seconds: float) -> float:
        """Pauses every caller that reads ``key`` for ``seconds`` from now. A
        pause that ends later stays. Returns the seconds until the pause
        ends. The Redis clock times the pause, so clock skew between pods has
        no effect."""
        if seconds <= 0:
            return self.pause_left(key)
        try:
            # no-direct-redis: allow the pause is shared by every indexing and sync worker
            result = self._redis.eval(
                _PAUSE_SCRIPT, keys=[key], args=[str(max(1, int(seconds * 1000)))]
            )
        except RedisError as error:
            _warn_redis_unreachable(error)
            return 0.0
        return int(result) / 1000

    def pause_left(self, key: str) -> float:
        """The seconds until the pause of ``key`` ends, or 0 with no pause.
        When Redis cannot be reached, there is no pause."""
        try:
            # no-direct-redis: allow the pause is shared by every indexing and sync worker
            result = self._redis.eval(_PAUSE_LEFT_SCRIPT, keys=[key], args=[])
        except RedisError as error:
            _warn_redis_unreachable(error)
            return 0.0
        return int(result) / 1000

    def try_take_from_day(self, key: str, cost: int, limit: int) -> float:
        """Takes ``cost`` units from a budget of ``limit`` units in any 24
        hours and returns 0, or takes nothing and returns the seconds until
        the budget can have room. The budget counts by the hour. When Redis
        cannot be reached, the request is not limited."""
        try:
            # no-direct-redis: allow the budget is shared by every indexing and sync worker
            result = self._redis.eval(
                _DAY_SCRIPT, keys=[key], args=[str(cost), str(limit)]
            )
        except RedisError as error:
            _warn_redis_unreachable(error)
            return 0.0
        return float(int(result))

    def delete(self, window: RateWindow) -> None:
        """Removes the window's state. For tests."""
        self._redis.delete(
            _log_key(window),
            _meta_key(window),
            _queue_key(window),
            _seen_key(window),
            stored_share_key(window),
        )
