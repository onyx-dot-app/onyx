"""Per-IP rate limit on email/password signup.

Orthogonal to reCAPTCHA. Even when bots pass a v3 score >= threshold (real
browser automation + residential proxies routinely do) the cost of each
rotated IP still limits throughput. Cloud-only: self-hosted deployments
skip this entirely.

Uses Redis INCR + EXPIRE so counters are cluster-wide. Keys are hour-bucketed
on wall-clock so the "per hour" window is a fixed tumbling window — fine for
this use case since we're not trying to be precise, we're raising cost.
"""

import time

from fastapi import Request

from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.redis.redis_pool import get_async_redis_connection
from onyx.utils.logger import setup_logger
from shared_configs.configs import MULTI_TENANT

logger = setup_logger()

# Hardcoded tunables. Registration is a rare legitimate event — humans sign
# up once. 5/hour/IP still accommodates shared-NAT offices while forcing
# bot farms to rotate IPs (which costs real money on residential proxies).
_PER_IP_PER_HOUR = 5
_BUCKET_SECONDS = 3600
_REDIS_KEY_PREFIX = "signup_rate:"


def _client_ip(request: Request) -> str:
    """Prefer the real client IP from X-Forwarded-For. Nginx and the AWS LB
    both set it; ``request.client.host`` is the proxy hop, which is the same
    for every request and useless as a rate-limit key."""
    xff = request.headers.get("x-forwarded-for")
    if xff:
        # First entry is the originating client per RFC 7239 convention.
        return xff.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def _bucket_key(ip: str) -> str:
    bucket = int(time.time() // _BUCKET_SECONDS)
    return f"{_REDIS_KEY_PREFIX}{ip}:{bucket}"


def is_signup_rate_limit_enabled() -> bool:
    """Only active on multi-tenant cloud deployments. Self-hosted signup is
    typically admin-invite-only and doesn't see the spray-registration
    threat model."""
    return MULTI_TENANT


async def enforce_signup_rate_limit(request: Request) -> None:
    """Raise OnyxError(RATE_LIMITED) if this client has exceeded the hourly
    signup cap. Fails open on Redis errors so a Redis blip cannot block
    legitimate registrations."""
    if not is_signup_rate_limit_enabled():
        return

    ip = _client_ip(request)
    key = _bucket_key(ip)

    try:
        redis = await get_async_redis_connection()
        # INCR returns the post-increment value; if this is the first hit in
        # the bucket we also set TTL so the key self-cleans.
        count = await redis.incr(key)
        if count == 1:
            await redis.expire(key, _BUCKET_SECONDS)
    except Exception as e:
        logger.error(f"Signup rate-limit Redis error (failing open): {e}")
        return

    if count > _PER_IP_PER_HOUR:
        logger.warning(
            f"Signup rate limit exceeded for ip={ip} count={count} limit={_PER_IP_PER_HOUR}"
        )
        raise OnyxError(
            OnyxErrorCode.RATE_LIMITED,
            "Too many signup attempts from this network. Please wait before trying again.",
        )


# Exported for tests that want to reason about the bucket shape without
# re-deriving the constants.
__all__ = [
    "enforce_signup_rate_limit",
    "is_signup_rate_limit_enabled",
    "_PER_IP_PER_HOUR",
    "_BUCKET_SECONDS",
    "_client_ip",
    "_bucket_key",
]
