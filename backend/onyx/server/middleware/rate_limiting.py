from fastapi import Depends
from fastapi import params
from fastapi import Request
from fastapi import Response
from fastapi_limiter import FastAPILimiter
from fastapi_limiter.depends import RateLimiter

from onyx.auth.users import current_chat_accessible_user
from onyx.configs.app_configs import AUTH_RATE_LIMITING_ENABLED
from onyx.configs.app_configs import FEEDBACK_RATE_LIMIT_MAX_REQUESTS
from onyx.configs.app_configs import FEEDBACK_RATE_LIMIT_WINDOW_SECONDS
from onyx.configs.app_configs import FEEDBACK_RATE_LIMITING_ENABLED
from onyx.configs.app_configs import RATE_LIMIT_MAX_REQUESTS
from onyx.configs.app_configs import RATE_LIMIT_WINDOW_SECONDS
from onyx.db.enums import AccountType
from onyx.db.models import User
from onyx.redis.redis_pool import get_async_redis_connection

RATE_LIMITING_ENABLED = (
    bool(AUTH_RATE_LIMITING_ENABLED) or FEEDBACK_RATE_LIMITING_ENABLED
)

_RATE_LIMIT_USER_ID_STATE_KEY = "rate_limit_user_id"


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


async def user_scoped_rate_limit_key(request: Request) -> str:
    """Key on the authenticated user id stashed on request.state by the
    user-scoped limiter dependency; falls back to IP + User-Agent when no
    user id was stashed (anonymous access)."""
    user_id: str | None = getattr(request.state, _RATE_LIMIT_USER_ID_STATE_KEY, None)
    if user_id is not None:
        return f"user-{user_id}"
    return await rate_limit_key(request)


def get_auth_rate_limiters() -> list[params.Depends]:
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
    """Per-user rate limiters for the chat message feedback endpoints
    (ON-009). Enabled by default; disabled via FEEDBACK_RATE_LIMIT_* env vars
    or automatically when running without Redis.

    The limiter dependency resolves the authenticated user first, so:
    - unauthenticated floods are rejected with 401 before touching limiter
      state, and callers can't mint rate-limit buckets by rotating cookie or
      Authorization header values,
    - limits are per user id, so they can't be multiplied by creating extra
      sessions or varying credential formatting for the same account.

    The shared anonymous user (when anonymous access is enabled) is keyed by
    IP + User-Agent instead, so one anonymous abuser can't exhaust every
    anonymous caller's budget.
    """
    if not FEEDBACK_RATE_LIMITING_ENABLED:
        return []

    limiter = RateLimiter(
        times=FEEDBACK_RATE_LIMIT_MAX_REQUESTS,
        seconds=FEEDBACK_RATE_LIMIT_WINDOW_SECONDS,
        identifier=user_scoped_rate_limit_key,
    )

    async def user_scoped_feedback_limiter(
        request: Request,
        response: Response,
        user: User = Depends(current_chat_accessible_user),
    ) -> None:
        # FastAPI caches the user dependency per-request, so the endpoint's
        # own auth dependency does not run a second time.
        request.state.rate_limit_user_id = (
            str(user.id) if user.account_type != AccountType.ANONYMOUS else None
        )
        await limiter(request, response)

    return [Depends(user_scoped_feedback_limiter)]
