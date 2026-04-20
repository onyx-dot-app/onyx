"""Redis-backed rate limits for admin invite + remove-invited-user endpoints.

Defends against compromised-admin invite-spam and email-bomb abuse that
nginx IP-keyed `limit_req` cannot stop (per-pod counters in multi-replica
deployments, trivial IP rotation). Counters live in tenant-prefixed Redis
so multi-pod api-server instances share state and per-admin / per-tenant
quotas are enforced cluster-wide.
"""

from dataclasses import dataclass
from typing import cast
from uuid import UUID

from redis import Redis

from onyx.configs.app_configs import INVITE_RATE_LIMIT_ADMIN_PER_DAY
from onyx.configs.app_configs import INVITE_RATE_LIMIT_ADMIN_PER_MIN
from onyx.configs.app_configs import INVITE_RATE_LIMIT_TENANT_PER_DAY
from onyx.configs.app_configs import INVITE_REMOVE_RATE_LIMIT_ADMIN_PER_DAY
from onyx.configs.app_configs import INVITE_REMOVE_RATE_LIMIT_ADMIN_PER_MIN
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.utils.logger import setup_logger

logger = setup_logger()

_SECONDS_PER_MINUTE = 60
_SECONDS_PER_DAY = 24 * 60 * 60

_INVITE_PUT_ADMIN_MIN_KEY = "ratelimit:invite_put:admin:{user_id}:min"
_INVITE_PUT_ADMIN_DAY_KEY = "ratelimit:invite_put:admin:{user_id}:day"
_INVITE_PUT_TENANT_DAY_KEY = "ratelimit:invite_put:tenant:day"
_INVITE_REMOVE_ADMIN_MIN_KEY = "ratelimit:invite_remove:admin:{user_id}:min"
_INVITE_REMOVE_ADMIN_DAY_KEY = "ratelimit:invite_remove:admin:{user_id}:day"


@dataclass(frozen=True)
class _Bucket:
    key: str
    limit: int
    ttl_seconds: int
    scope: str
    increment: int


def _raise_if_exceeded(redis_client: Redis, bucket: _Bucket) -> None:
    if bucket.limit <= 0 or bucket.increment <= 0:
        return

    raw_current = cast(bytes | None, redis_client.get(bucket.key))
    current = int(raw_current) if raw_current is not None else 0
    if current + bucket.increment > bucket.limit:
        logger.warning(
            "Invite rate limit hit: scope=%s key=%s current=%d adding=%d limit=%d",
            bucket.scope,
            bucket.key,
            current,
            bucket.increment,
            bucket.limit,
        )
        raise OnyxError(
            OnyxErrorCode.RATE_LIMITED,
            f"Invite rate limit exceeded ({bucket.scope}). Try again later.",
        )


def _record(redis_client: Redis, bucket: _Bucket) -> None:
    if bucket.limit <= 0 or bucket.increment <= 0:
        return
    new_value = redis_client.incrby(bucket.key, bucket.increment)
    if new_value == bucket.increment:
        redis_client.expire(bucket.key, bucket.ttl_seconds)


def enforce_invite_rate_limit(
    redis_client: Redis,
    admin_user_id: UUID | str,
    num_invites: int,
) -> None:
    """Check+record invite quotas for an admin user within their tenant.

    Three tiers. Daily tiers track invite volume (so bulk invite of 20
    users counts as 20); the minute tier tracks request cadence (so a
    single legitimate bulk call does not trip the burst guard while an
    attacker spamming single-email requests does).

    Raises OnyxError(RATE_LIMITED) without recording if any tier would be
    exceeded, so repeated rejected attempts do not consume budget.
    `num_invites` MUST be the count of new invites the request will send
    (not total emails in the body — deduplicate already-invited first).
    Zero-invite calls still tick the minute bucket so probe-floods of
    already-invited emails cannot bypass the burst guard.
    """
    user_key = str(admin_user_id)
    daily_increment = max(0, num_invites)
    buckets = [
        _Bucket(
            key=_INVITE_PUT_TENANT_DAY_KEY,
            limit=INVITE_RATE_LIMIT_TENANT_PER_DAY,
            ttl_seconds=_SECONDS_PER_DAY,
            scope="tenant/day",
            increment=daily_increment,
        ),
        _Bucket(
            key=_INVITE_PUT_ADMIN_DAY_KEY.format(user_id=user_key),
            limit=INVITE_RATE_LIMIT_ADMIN_PER_DAY,
            ttl_seconds=_SECONDS_PER_DAY,
            scope="admin/day",
            increment=daily_increment,
        ),
        _Bucket(
            key=_INVITE_PUT_ADMIN_MIN_KEY.format(user_id=user_key),
            limit=INVITE_RATE_LIMIT_ADMIN_PER_MIN,
            ttl_seconds=_SECONDS_PER_MINUTE,
            scope="admin/minute",
            increment=1,
        ),
    ]

    for bucket in buckets:
        _raise_if_exceeded(redis_client, bucket)
    for bucket in buckets:
        _record(redis_client, bucket)


def enforce_remove_invited_rate_limit(
    redis_client: Redis,
    admin_user_id: UUID | str,
) -> None:
    """Check+record remove-invited-user quotas for an admin user.

    Two tiers: per-admin per-day and per-admin per-minute. Removal itself
    does not send email, so there is no tenant-wide cap — the goal is to
    detect the PUT→PATCH abuse pattern by throttling PATCHes to roughly
    the cadence of legitimate administrative mistake correction.
    """
    user_key = str(admin_user_id)
    buckets = [
        _Bucket(
            key=_INVITE_REMOVE_ADMIN_DAY_KEY.format(user_id=user_key),
            limit=INVITE_REMOVE_RATE_LIMIT_ADMIN_PER_DAY,
            ttl_seconds=_SECONDS_PER_DAY,
            scope="admin/day",
            increment=1,
        ),
        _Bucket(
            key=_INVITE_REMOVE_ADMIN_MIN_KEY.format(user_id=user_key),
            limit=INVITE_REMOVE_RATE_LIMIT_ADMIN_PER_MIN,
            ttl_seconds=_SECONDS_PER_MINUTE,
            scope="admin/minute",
            increment=1,
        ),
    ]

    for bucket in buckets:
        _raise_if_exceeded(redis_client, bucket)
    for bucket in buckets:
        _record(redis_client, bucket)
