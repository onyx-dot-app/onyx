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
    redis = await aioredis.from_url(
        f"redis://{REDIS_HOST}:{REDIS_PORT}", password=REDIS_PASSWORD
    )
    await FastAPILimiter.init(redis)


async def close_limiter() -> None:
    await FastAPILimiter.close()


def rate_limit_key(request: Request) -> str:
    return (
        request.client.host if request.client else "unknown"
    )  # Use IP address for rate limiting


# Custom rate limiter that uses the client's IP address
def get_auth_rate_limiters() -> List[Callable]:
    if not (RATE_LIMIT_MAX_REQUESTS and RATE_LIMIT_WINDOW_SECONDS):
        return []

    return [
        Depends(
            RateLimiter(
                times=RATE_LIMIT_MAX_REQUESTS,
                seconds=RATE_LIMIT_WINDOW_SECONDS,
            )
        )
    ]
