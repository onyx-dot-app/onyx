from collections.abc import Callable
from typing import List

from fastapi import Depends
from fastapi import Request
from fastapi_limiter import FastAPILimiter
from fastapi_limiter.depends import RateLimiter
from redis import asyncio as aioredis

from onyx.configs.app_configs import RATE_LIMIT_MAX_REQUESTS
from onyx.configs.app_configs import RATE_LIMIT_WINDOW_SECONDS
from onyx.configs.app_configs import REDIS_HOST
from onyx.configs.app_configs import REDIS_PASSWORD
from onyx.configs.app_configs import REDIS_PORT


async def setup_limiter() -> None:
    # Sets up the global FastAPILimiter using an async Redis connection.
    # Cannot reuse existing redis_pool functions, because our existing pool is synchronous while we need async here.
    # Without this setup, we wouldn't have a shared store for rate-limit counters.
    redis = await aioredis.from_url(
        f"redis://{REDIS_HOST}:{REDIS_PORT}", password=REDIS_PASSWORD
    )
    await FastAPILimiter.init(redis)


async def close_limiter() -> None:
    await FastAPILimiter.close()


async def rate_limit_key(request: Request) -> str:
    # Uses both IP and User-Agent to make collisions less likely if IP is behind NAT.
    # If request.client is None, a fallback is used to avoid completely unknown keys.
    # This helps ensure we have a unique key for each 'user' in simple scenarios.
    ip_part = request.client.host if request.client else "unknown"
    ua_part = request.headers.get("user-agent", "none").replace(" ", "_")
    return f"{ip_part}-{ua_part}"


def get_auth_rate_limiters() -> List[Callable]:
    if not (RATE_LIMIT_MAX_REQUESTS and RATE_LIMIT_WINDOW_SECONDS):
        return []

    return [
        Depends(
            RateLimiter(
                times=RATE_LIMIT_MAX_REQUESTS,
                seconds=RATE_LIMIT_WINDOW_SECONDS,
                # Use the custom key function to distinguish users
                identifier=rate_limit_key,
            )
        )
    ]
