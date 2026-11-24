"""The Redis store of the values that the workers of one listing run share."""

import hashlib

from redis.exceptions import RedisError

from onyx.connectors.interfaces import RunScopedCache
from onyx.redis.redis_pool import get_redis_client
from onyx.utils.logger import setup_logger

logger = setup_logger()

_KEY_PREFIX = "run_scoped_cache"


class RedisRunScopedCache(RunScopedCache):
    """Keeps each value under the run id and a hash of the connector's key,
    with the tenant prefix of the client. Another run never reads these
    keys, and a key holds no name or URL from the source. It reads the
    client of the current tenant on each call."""

    def __init__(self, run_id: str) -> None:
        self._run_id = run_id

    def _key(self, key: str) -> str:
        digest = hashlib.sha256(key.encode()).hexdigest()
        return f"{_KEY_PREFIX}:{self._run_id}:{digest}"

    def get(self, key: str) -> str | None:
        try:
            # no-direct-redis: allow the workers of a listing run share these values
            raw = get_redis_client().get(self._key(key))
        except RedisError:
            return None
        return raw.decode() if raw is not None else None

    def set(self, key: str, value: str, ttl_seconds: int) -> None:
        try:
            # no-direct-redis: allow the workers of a listing run share these values
            get_redis_client().set(self._key(key), value, ex=ttl_seconds)
        except RedisError as error:
            logger.warning("Could not store a value of a listing run: %s", error)
