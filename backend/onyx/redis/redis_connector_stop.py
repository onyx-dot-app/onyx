import time

from onyx.redis.tenant_redis_client import TenantRedisClient


class RedisConnectorStop:
    """Manages interactions with redis for stop signaling. Should only be accessed
    through RedisConnector."""

    PREFIX = "connectorstop"
    FENCE_PREFIX = f"{PREFIX}_fence"
    FENCE_TTL = 7 * 24 * 60 * 60  # 7 days - defensive TTL to prevent memory leaks

    # if this timeout is exceeded, the caller may decide to take more
    # drastic measures. The key holds the deadline (epoch seconds).
    TIMEOUT_PREFIX = f"{PREFIX}_timeout"
    TIMEOUT_TTL = 300

    def __init__(self, tenant_id: str, id: int, redis: TenantRedisClient) -> None:
        self.tenant_id: str = tenant_id
        self.id: int = id
        self.redis = redis

        self.fence_key: str = f"{self.FENCE_PREFIX}_{id}"
        self.timeout_key: str = f"{self.TIMEOUT_PREFIX}_{id}"

    @property
    def fenced(self) -> bool:
        return bool(self.redis.exists(self.fence_key))

    def set_fence(self, value: bool) -> None:
        if not value:
            self.redis.delete(self.fence_key)
            return

        self.redis.set(self.fence_key, 0, ex=self.FENCE_TTL)

    @property
    def timeout_set(self) -> bool:
        """Whether a caller started waiting on the stop signal (see
        ``set_timeout``). A pause sets the fence alone, so the fence cannot
        tell this."""
        return bool(self.redis.exists(self.timeout_key))

    @property
    def timed_out(self) -> bool:
        """Whether the wait started by ``set_timeout`` passed its deadline. A
        key without a deadline (written before deadlines were stored) never
        times out; it expires instead."""
        raw = self.redis.get(self.timeout_key)
        if raw is None:
            return False
        deadline = float(raw)
        return deadline > 0 and time.time() > deadline

    def set_timeout(self) -> None:
        """Starts the wait: ``timed_out`` turns true ``TIMEOUT_TTL`` seconds
        from now."""
        self.redis.set(
            self.timeout_key, time.time() + self.TIMEOUT_TTL, ex=self.FENCE_TTL
        )

    def clear_timeout(self) -> None:
        self.redis.delete(self.timeout_key)

    @staticmethod
    def reset_all(r: TenantRedisClient) -> None:
        for key in r.scan_iter(RedisConnectorStop.FENCE_PREFIX + "*"):
            r.delete(key)

        for key in r.scan_iter(RedisConnectorStop.TIMEOUT_PREFIX + "*"):
            r.delete(key)
