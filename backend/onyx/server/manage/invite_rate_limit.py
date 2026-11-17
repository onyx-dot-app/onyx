"""Rate limits for admin invite + remove-invited-user endpoints.

Defends against compromised-admin invite-spam and email-bomb abuse that
nginx IP-keyed `limit_req` cannot stop (per-pod counters in multi-replica
deployments, trivial IP rotation). Counters live in the tenant's cache
so multi-pod api-server instances share state and per-admin / per-tenant
quotas are enforced cluster-wide.

Check+increment runs under one cache lock per tenant, so two concurrent
replicas cannot both pass the pre-check and both increment past the limit.
When the cache is unavailable, or the lock is busy for too long, the rate
limiter fails open with a logged warning so core invite flows continue to
work.
"""

from dataclasses import dataclass
from uuid import UUID

from onyx.cache.interface import (
    CACHE_TRANSIENT_ERRORS,
    TTL_KEY_NOT_FOUND,
    TTL_NO_EXPIRY,
    CacheBackend,
    CacheLock,
    CacheLockLostError,
)
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.utils.logger import setup_logger

logger = setup_logger()

_SECONDS_PER_MINUTE = 60
_SECONDS_PER_DAY = 24 * 60 * 60

# Rate limits apply to trial tenants only (enforced at call site). Paid tenants
# bypass entirely — their guardrails are seat limits and the per-admin lifetime
# counter. The limiter fails open when the cache is unavailable.
# Values are sized against the trial lifetime cap
# `NUM_FREE_TRIAL_USER_INVITES=10` and the invite -> remove -> invite bypass
# attack: per-day caps stay tight so a compromised or scripted trial admin
# cannot exceed the lifetime cap even across window rolls, and per-minute caps
# block burst automation while leaving headroom for a human typing emails by
# hand.
_INVITE_ADMIN_PER_MIN = 3
_INVITE_ADMIN_PER_DAY = 10
_INVITE_TENANT_PER_DAY = 15
_REMOVE_ADMIN_PER_MIN = 3
_REMOVE_ADMIN_PER_DAY = 30

# Per-admin buckets are scoped by globally unique admin UUIDs. The tenant/day
# bucket also embeds the tenant_id directly so two tenants never share a bucket
# even when the keys collide post-prefixing — defence in depth alongside
# the per-tenant prefix the cache backend applies.
_INVITE_PUT_ADMIN_MIN_KEY = "ratelimit:invite_put:admin:{user_id}:min"
_INVITE_PUT_ADMIN_DAY_KEY = "ratelimit:invite_put:admin:{user_id}:day"
_INVITE_PUT_TENANT_DAY_KEY = "ratelimit:invite_put:tenant:{tenant_id}:day"
_INVITE_REMOVE_ADMIN_MIN_KEY = "ratelimit:invite_remove:admin:{user_id}:min"
_INVITE_REMOVE_ADMIN_DAY_KEY = "ratelimit:invite_remove:admin:{user_id}:day"

# Serializes check+increment for one tenant. The lease covers a few cache
# round trips; the wait bounds how long a request queues behind another.
_LOCK_KEY = "ratelimit:invite:lock"
_LOCK_LEASE_SECONDS = 10
_LOCK_WAIT_SECONDS = 5


@dataclass(frozen=True)
class _Bucket:
    key: str
    limit: int
    ttl_seconds: int
    scope: str
    increment: int


def _check_and_increment(
    cache: CacheBackend, buckets: list[_Bucket], lock: CacheLock
) -> _Bucket | None:
    """Return the first bucket the request would exceed, or record the request.

    Checks every bucket before it increments any, so a rejected request does
    not consume budget. Buckets with limit <= 0 or increment <= 0 are skipped
    (a disabled tier). The TTL is set when a counter is created and kept on
    later increments (fixed window, not sliding). The caller holds ``lock``.
    Raises CacheLockLostError if the lease ended during the check, or if a
    counter changed after it was read. Counters written before that point stay,
    so the limiter can count high but never low.
    """
    active = [b for b in buckets if b.limit > 0 and b.increment > 0]
    raws: list[bytes | None] = []
    for bucket in active:
        raw = cache.get(bucket.key)
        if int(raw or 0) + bucket.increment > bucket.limit:
            return bucket
        raws.append(raw)
    if not lock.owned():
        raise CacheLockLostError("Invite rate limiter lock expired before the write")
    for bucket, raw in zip(active, raws, strict=True):
        remaining = cache.ttl(bucket.key) if raw is not None else TTL_KEY_NOT_FOUND
        # Each write is a compare-and-swap on the value read above. If the lease
        # ends here and another request counts first, the write fails and
        # cannot erase that request's increment.
        if raw is None or remaining == TTL_KEY_NOT_FOUND:
            # No counter, or its window ended after the read: start a new window.
            stored = cache.set_if_absent(
                bucket.key, bucket.increment, ex=bucket.ttl_seconds
            )
        else:
            # Keep the window. A TTL of 0 is a window with under a second left.
            stored = cache.replace_if_value(
                bucket.key,
                raw,
                int(raw) + bucket.increment,
                ex=(
                    bucket.ttl_seconds
                    if remaining == TTL_NO_EXPIRY
                    else max(1, remaining)
                ),
            )
        if not stored:
            raise CacheLockLostError(
                "Another request changed an invite counter during the write"
            )
    return None


def _run_atomic(cache: CacheBackend, buckets: list[_Bucket]) -> None:
    """Check and record the request under the tenant lock. Raise OnyxError on rejection.

    On cache errors, or when the lock stays busy, the rate limiter fails open:
    the request is allowed through and the failure is logged. This keeps the
    invite flow usable during a cache outage.
    """
    if not buckets:
        return

    try:
        lock = cache.lock(_LOCK_KEY, timeout=_LOCK_LEASE_SECONDS)
        if not lock.acquire(blocking=True, blocking_timeout=_LOCK_WAIT_SECONDS):
            logger.warning(
                "Invite rate limiter skipped — lock busy. Rate limiting is disabled for this request."
            )
            return
        try:
            failed_bucket = _check_and_increment(cache, buckets, lock)
        finally:
            try:
                lock.release()
            except CacheLockLostError:
                logger.warning("Invite rate limiter lock expired before release.")
    except CACHE_TRANSIENT_ERRORS as e:
        logger.warning(
            "Invite rate limiter skipped — cache unavailable: %s. Rate limiting is disabled for this request.",
            e,
        )
        return
    except CacheLockLostError:
        logger.warning(
            "Invite rate limiter skipped — lock lost during the check. Rate limiting is disabled for this request."
        )
        return

    if failed_bucket is None:
        return

    logger.warning(
        "Invite rate limit hit: scope=%s key=%s adding=%d limit=%d",
        failed_bucket.scope,
        failed_bucket.key,
        failed_bucket.increment,
        failed_bucket.limit,
    )
    raise OnyxError(
        OnyxErrorCode.RATE_LIMITED,
        f"Invite rate limit exceeded ({failed_bucket.scope}). Try again later.",
    )


def enforce_invite_rate_limit(
    cache: CacheBackend,
    admin_user_id: UUID | str,
    num_invites: int,
    tenant_id: str,
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
            key=_INVITE_PUT_TENANT_DAY_KEY.format(tenant_id=tenant_id),
            limit=_INVITE_TENANT_PER_DAY,
            ttl_seconds=_SECONDS_PER_DAY,
            scope="tenant/day",
            increment=daily_increment,
        ),
        _Bucket(
            key=_INVITE_PUT_ADMIN_DAY_KEY.format(user_id=user_key),
            limit=_INVITE_ADMIN_PER_DAY,
            ttl_seconds=_SECONDS_PER_DAY,
            scope="admin/day",
            increment=daily_increment,
        ),
        _Bucket(
            key=_INVITE_PUT_ADMIN_MIN_KEY.format(user_id=user_key),
            limit=_INVITE_ADMIN_PER_MIN,
            ttl_seconds=_SECONDS_PER_MINUTE,
            scope="admin/minute",
            increment=1,
        ),
    ]
    _run_atomic(cache, buckets)


def enforce_remove_invited_rate_limit(
    cache: CacheBackend,
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
            limit=_REMOVE_ADMIN_PER_DAY,
            ttl_seconds=_SECONDS_PER_DAY,
            scope="admin/day",
            increment=1,
        ),
        _Bucket(
            key=_INVITE_REMOVE_ADMIN_MIN_KEY.format(user_id=user_key),
            limit=_REMOVE_ADMIN_PER_MIN,
            ttl_seconds=_SECONDS_PER_MINUTE,
            scope="admin/minute",
            increment=1,
        ),
    ]
    _run_atomic(cache, buckets)
