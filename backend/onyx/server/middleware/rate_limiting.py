from collections.abc import Callable
from typing import List

from fastapi import Depends
from fastapi import Request
from fastapi_limiter import FastAPILimiter
from fastapi_limiter.depends import RateLimiter

from onyx.configs.app_configs import AUTH_RATE_LIMITING_ENABLED
from onyx.configs.app_configs import RATE_LIMIT_MAX_REQUESTS
from onyx.configs.app_configs import RATE_LIMIT_WINDOW_SECONDS
from onyx.redis.redis_pool import get_async_redis_connection


async def setup_auth_limiter() -> None:
    # Use the centralized async Redis connection
    redis = await get_async_redis_connection()
    await FastAPILimiter.init(redis)


async def close_auth_limiter() -> None:
    # This closes the FastAPILimiter connection so we don't leave open connections to Redis.
    await FastAPILimiter.close()


async def rate_limit_key(request: Request) -> str:
    # Uses both IP and User-Agent to make collisions less likely if IP is behind NAT.
    # If request.client is None, a fallback is used to avoid completely unknown keys.
    # This helps ensure we have a unique key for each 'user' in simple scenarios.
    ip_part = request.client.host if request.client else "unknown"
    ua_part = request.headers.get("user-agent", "none").replace(" ", "_")
    return f"{ip_part}-{ua_part}"


def get_auth_rate_limiters() -> List[Callable]:
    if not AUTH_RATE_LIMITING_ENABLED:
        return []

    return [
        Depends(
            RateLimiter(
                times=RATE_LIMIT_MAX_REQUESTS or 100,
                seconds=RATE_LIMIT_WINDOW_SECONDS or 60,
                # Use the custom key function to distinguish users
                identifier=rate_limit_key,
            )
        )
    ]
