"""Per-IP rate limit on email/password signup."""

import time

from fastapi import Request

from onyx.configs.app_configs import SIGNUP_RATE_LIMIT_ENABLED
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.redis.redis_pool import get_async_redis_connection
from onyx.utils.client_ip import get_client_ip
from onyx.utils.logger import setup_logger
from shared_configs.configs import MULTI_TENANT

logger = setup_logger()

_PER_IP_PER_HOUR = 5
_BUCKET_SECONDS = 3600
_REDIS_KEY_PREFIX = "signup_rate:"


def _client_ip(request: Request) -> str:
    """Return the rate-limit bucket key for this request.

    Delegates to the shared ``get_client_ip`` helper, which walks
    ``X-Forwarded-For`` right-to-left so attacker-prepended IPs at the
    left of the chain can't carve out their own bucket. Falls back to
    the string ``"unknown"`` when no routable address is available,
    so bucket_key stays deterministic.
    """
    return get_client_ip(request) or "unknown"


def _bucket_key(ip: str) -> str:
    bucket = int(time.time() // _BUCKET_SECONDS)
    return f"{_REDIS_KEY_PREFIX}{ip}:{bucket}"


async def enforce_signup_rate_limit(request: Request) -> None:
    """Raise OnyxError(RATE_LIMITED) when the client exceeds the signup cap."""
    if not (MULTI_TENANT and SIGNUP_RATE_LIMIT_ENABLED):
        return

    ip = _client_ip(request)
    key = _bucket_key(ip)

    try:
        redis = await get_async_redis_connection()
        pipe = redis.pipeline()
        pipe.incr(key)
        pipe.expire(key, _BUCKET_SECONDS)
        incr_result, _ = await pipe.execute()
        count = int(incr_result)
    except Exception as e:
        logger.error(f"Signup rate-limit Redis error: {e}")
        return

    if count > _PER_IP_PER_HOUR:
        logger.warning(f"Signup rate limit exceeded for ip={ip} count={count}")
        raise OnyxError(
            OnyxErrorCode.RATE_LIMITED,
            "Too many signup attempts from this network. Please wait before trying again.",
        )


__all__ = [
    "enforce_signup_rate_limit",
    "_PER_IP_PER_HOUR",
    "_BUCKET_SECONDS",
    "_client_ip",
    "_bucket_key",
]
