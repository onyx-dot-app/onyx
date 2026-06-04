import hashlib
from collections.abc import Callable
from typing import List

from fastapi import Depends
from fastapi import params
from fastapi import Request
from fastapi_limiter import FastAPILimiter
from fastapi_limiter.depends import RateLimiter

from onyx.configs.app_configs import AUTH_RATE_LIMITING_ENABLED
from onyx.configs.app_configs import FEEDBACK_RATE_LIMIT_MAX_REQUESTS
from onyx.configs.app_configs import FEEDBACK_RATE_LIMIT_WINDOW_SECONDS
from onyx.configs.app_configs import FEEDBACK_RATE_LIMITING_ENABLED
from onyx.configs.app_configs import RATE_LIMIT_MAX_REQUESTS
from onyx.configs.app_configs import RATE_LIMIT_WINDOW_SECONDS
from onyx.configs.constants import FASTAPI_USERS_AUTH_COOKIE_NAME
from onyx.redis.redis_pool import get_async_redis_connection

RATE_LIMITING_ENABLED = (
    bool(AUTH_RATE_LIMITING_ENABLED) or FEEDBACK_RATE_LIMITING_ENABLED
)


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


async def user_rate_limit_key(request: Request) -> str:
    """Rate-limit key for authenticated endpoints.

    Keys on the caller's credential rather than resolving the user from the
    DB (which would add a query to every request): the session cookie when
    present, else the Authorization header (API keys), else IP + User-Agent.
    Values are hashed so raw session tokens / API keys never appear in Redis
    keys.
    """
    session_cookie = request.cookies.get(FASTAPI_USERS_AUTH_COOKIE_NAME)
    if session_cookie:
        return "sess-" + hashlib.sha256(session_cookie.encode("utf-8")).hexdigest()

    auth_header = request.headers.get("authorization")
    if auth_header:
        return "auth-" + hashlib.sha256(auth_header.encode("utf-8")).hexdigest()

    return await rate_limit_key(request)


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


def get_feedback_rate_limiters() -> list[params.Depends]:
    """Per-credential rate limiters for the chat message feedback endpoints
    (ON-009). Enabled by default; disabled via FEEDBACK_RATE_LIMIT_* env vars
    or automatically when running without Redis."""
    if not FEEDBACK_RATE_LIMITING_ENABLED:
        return []

    return [
        Depends(
            RateLimiter(
                times=FEEDBACK_RATE_LIMIT_MAX_REQUESTS,
                seconds=FEEDBACK_RATE_LIMIT_WINDOW_SECONDS,
                identifier=user_rate_limit_key,
            )
        )
    ]
