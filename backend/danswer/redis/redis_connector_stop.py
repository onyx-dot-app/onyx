import redis


class RedisConnectorStop:
    """Manages interactions with redis for stop signaling. Should only be accessed
    through RedisConnector."""

    FENCE_PREFIX = "connectorstop_fence"

    def __init__(self, tenant_id: str | None, id: int, redis: redis.Redis) -> None:
        self.tenant_id: str | None = tenant_id
        self.id: int = id
        self.redis = redis

        self.fence_key: str = f"{self.FENCE_PREFIX}_{id}"

    @property
    def fenced(self) -> bool:
        if self.redis.exists(self.fence_key):
            return True

        return False

    def set_fence(self, value: bool) -> None:
        if not value:
            self.redis.delete(self.fence_key)
            return

        self.redis.set(self.fence_key, 0)

    @staticmethod
    def reset_all(r: redis.Redis) -> None:
        for key in r.scan_iter(RedisConnectorStop.FENCE_PREFIX + "*"):
            r.delete(key)
