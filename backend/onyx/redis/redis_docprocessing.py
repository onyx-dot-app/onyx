import redis

# Safety-net TTL against leaked keys if cleanup() fails silently. Long enough
# that no legitimate sync will hit it; keys are normally deleted by cleanup().
_COUNTER_TTL_SECONDS = 15 * 24 * 3600  # 15 days

# Atomically increment pending and set TTL on first dispatch only.
# KEYS[1]=pending, ARGV[1]=ttl_seconds
_INCR_PENDING_SCRIPT = """
local val = redis.call('INCR', KEYS[1])
if val == 1 then
    redis.call('EXPIRE', KEYS[1], ARGV[1])
end
return val
"""

# Atomically move one batch from pending → in_flight.
# Guards against pending underflow and sets TTL on in_flight on first pickup.
# KEYS[1]=pending, KEYS[2]=in_flight, ARGV[1]=ttl_seconds
_PICKUP_SCRIPT = """
if tonumber(redis.call('GET', KEYS[1]) or 0) > 0 then
    redis.call('DECR', KEYS[1])
    local val = redis.call('INCR', KEYS[2])
    if val == 1 then
        redis.call('EXPIRE', KEYS[2], ARGV[1])
    end
    return 1
end
return 0
"""

# Atomically decrement in_flight, guarding against underflow.
# Prevents -1 recreation if task_postrun fires after cleanup() has already
# deleted the key (e.g. the attempt reached a terminal state before postrun).
_DECR_IN_FLIGHT_SCRIPT = """
if tonumber(redis.call('GET', KEYS[1]) or 0) > 0 then
    redis.call('DECR', KEYS[1])
    return 1
end
return 0
"""


class RedisDocprocessing:
    """Manages per-attempt docprocessing batch counters in Redis.

    Two counters track batches as they move through the lifecycle:
      pending   - dispatched to queue, not yet picked up by a worker
      in_flight - picked up by a worker, not yet completed

    Together they let the monitor distinguish worker crashes (in_flight > 0)
    from queue backlogs (in_flight = 0, pending > 0) when the heartbeat stops.
    """

    PENDING_PREFIX = "docprocessing_pending"
    IN_FLIGHT_PREFIX = "docprocessing_in_flight"

    def __init__(self, index_attempt_id: int, r: redis.Redis) -> None:
        self.index_attempt_id = index_attempt_id
        self.redis = r

        self.pending_key: str = f"{self.PENDING_PREFIX}_{index_attempt_id}"
        self.in_flight_key: str = f"{self.IN_FLIGHT_PREFIX}_{index_attempt_id}"

    def incr_pending(self) -> None:
        self.redis.eval(
            _INCR_PENDING_SCRIPT,
            1,
            self.pending_key,
            str(_COUNTER_TTL_SECONDS),
        )

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

    def cleanup(self) -> None:
        self.redis.delete(self.pending_key, self.in_flight_key)
