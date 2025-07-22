import redis


class RedisConnectorStop:
    """Manages interactions with redis for stop signaling. Should only be accessed
    through RedisConnector."""

    PREFIX = "connectorstop"
    FENCE_PREFIX = f"{PREFIX}_fence"

    # if this timeout is exceeded, the caller may decide to take more
    # drastic measures
    TIMEOUT_PREFIX = f"{PREFIX}_timeout"
    TIMEOUT_TTL = 300

    def __init__(self, tenant_id: str, id: int, redis: redis.Redis) -> None:
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

        self.redis.set(self.fence_key, 0)

    @property
    def timed_out(self) -> bool:
        return not bool(self.redis.exists(self.timeout_key))

    def set_timeout(self) -> None:
        """After calling this, call timed_out to determine if the timeout has been
        exceeded."""
        self.redis.set(f"{self.timeout_key}", 0, ex=self.TIMEOUT_TTL)

    @staticmethod
    def reset_all(r: redis.Redis) -> None:
        for key in r.scan_iter(RedisConnectorStop.FENCE_PREFIX + "*"):
            r.delete(key)

        for key in r.scan_iter(RedisConnectorStop.TIMEOUT_PREFIX + "*"):
            r.delete(key)
