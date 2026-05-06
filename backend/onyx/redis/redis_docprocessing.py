from typing import cast

import redis

# Safety-net TTL against leaked keys if cleanup() fails silently. Long enough
# that no legitimate sync will hit it; keys are normally deleted by cleanup().
_COUNTER_TTL_SECONDS = 15 * 24 * 3600  # 15 days

# Why Lua scripts for decrements:
#
# Redis executes each individual command atomically, but two separate commands
# (e.g. GET then DECR) from different clients can interleave. With multiple
# concurrent docprocessing workers, two workers finishing batches at the same
# time could both read the same counter value and both decrement, causing one
# decrement to be silently lost. Lost decrements leave in_flight overcounted,
# which would cause the monitor to incorrectly detect a worker crash.
#
# Lua scripts run single-threaded on the Redis server — no other client command
# can interleave while a script is executing. This serializes the GET+DECR into
# one uninterruptible unit, preventing lost decrements. Note that Lua does NOT
# provide rollback (unlike a DB transaction); if the script errors mid-way,
# partial writes persist. That is acceptable here since counters are soft
# signals and the monitor tolerates minor imprecision.
#
# Plain Python INCR is used for incr_pending since concurrent increments cannot
# lose updates — each adds 1 regardless of ordering.

# Atomically move one batch from pending → in_flight.
# The if-guard prevents pending from going negative if cleanup() races with a
# late task_prerun signal. Serialized execution on the Redis server prevents
# lost decrements when multiple workers pick up batches concurrently.
# KEYS[1]=pending, KEYS[2]=in_flight, ARGV[1]=ttl_seconds
_PICKUP_SCRIPT = """
if tonumber(redis.call('GET', KEYS[1]) or 0) > 0 then
    redis.call('DECR', KEYS[1])
end
local inflight = redis.call('INCR', KEYS[2])
if inflight == 1 then
    redis.call('EXPIRE', KEYS[2], ARGV[1])
end
"""

# Atomically decrement in_flight, guarding against underflow.
# The if-guard prevents in_flight from going negative if cleanup() races with
# a late task_postrun signal. Serialized execution on the Redis server prevents
# lost decrements when multiple workers complete batches concurrently.
# KEYS[1]=in_flight
_DECR_IN_FLIGHT_SCRIPT = """
if tonumber(redis.call('GET', KEYS[1]) or 0) > 0 then
    redis.call('DECR', KEYS[1])
end
"""


class RedisDocprocessing:
    """Manages per-attempt docprocessing batch counters in Redis.

    Two counters track batches as they move through the lifecycle:
      pending   - dispatched to queue, not yet picked up by a worker
      in_flight - picked up by a worker, not yet completed

    Together they let the monitor distinguish worker crashes (in_flight > 0)
    from queue backlogs (in_flight = 0, pending > 0) when the heartbeat stops.

    Counter keys are namespaced by IndexAttempt.id.
    """

    PENDING_PREFIX = "docprocessing_pending"
    IN_FLIGHT_PREFIX = "docprocessing_in_flight"

    def __init__(self, index_attempt_id: int, r: redis.Redis) -> None:
        self.index_attempt_id = index_attempt_id
        self.redis = r

        self.pending_key: str = f"{self.PENDING_PREFIX}_{index_attempt_id}"
        self.in_flight_key: str = f"{self.IN_FLIGHT_PREFIX}_{index_attempt_id}"

    def incr_pending(self) -> None:
        val = self.redis.incr(self.pending_key)
        if val == 1:
            # Set TTL on first dispatch — safety net against leaked keys.
            self.redis.expire(self.pending_key, _COUNTER_TTL_SECONDS)

    def decr_pending_incr_in_flight(self) -> None:
        self.redis.eval(
            _PICKUP_SCRIPT,
            2,
            self.pending_key,
            self.in_flight_key,
            str(_COUNTER_TTL_SECONDS),
        )

    def decr_in_flight(self) -> None:
        self.redis.eval(_DECR_IN_FLIGHT_SCRIPT, 1, self.in_flight_key)

    def pending(self) -> int:
        return max(0, int(cast(bytes, self.redis.get(self.pending_key)) or 0))

    def in_flight(self) -> int:
        return max(0, int(cast(bytes, self.redis.get(self.in_flight_key)) or 0))

    def cleanup(self) -> None:
        self.redis.delete(self.pending_key, self.in_flight_key)
