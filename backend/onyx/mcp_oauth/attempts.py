import hashlib
import time
from collections.abc import Awaitable
from typing import cast

from onyx.redis.redis_pool import get_async_redis_connection
from shared_configs.configs import DEFAULT_REDIS_PREFIX

_RATE_KEY_PREFIX = f"{DEFAULT_REDIS_PREFIX}:mcp_oauth:rate"

_RATE_LIMIT_SCRIPT = """
local count = redis.call("INCR", KEYS[1])
if count == 1 then
  redis.call("EXPIRE", KEYS[1], ARGV[1])
end
return count <= tonumber(ARGV[2])
"""


def _rate_key(bucket: str, window_seconds: int) -> str:
    digest = hashlib.sha256(bucket.encode("utf-8")).hexdigest()
    window_id = int(time.time() // window_seconds)
    return f"{_RATE_KEY_PREFIX}:{{{digest}}}:{window_id}"


async def allow_mcp_oauth_request(
    bucket: str,
    *,
    limit: int,
    window_seconds: int,
) -> bool:
    if limit <= 0:
        raise ValueError("MCP OAuth rate limit must be positive")
    if window_seconds <= 0:
        raise ValueError("MCP OAuth rate-limit window must be positive")

    redis = await get_async_redis_connection()
    allowed = await cast(
        Awaitable[object],
        redis.eval(
            _RATE_LIMIT_SCRIPT,
            1,
            _rate_key(bucket, window_seconds),
            str(window_seconds),
            str(limit),
        ),
    )
    return bool(allowed)
