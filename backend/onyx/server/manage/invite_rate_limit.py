"""Redis-backed rate limits for admin invite + remove-invited-user endpoints.

Defends against compromised-admin invite-spam and email-bomb abuse that
nginx IP-keyed `limit_req` cannot stop (per-pod counters in multi-replica
deployments, trivial IP rotation). Counters live in tenant-prefixed Redis
so multi-pod api-server instances share state and per-admin / per-tenant
quotas are enforced cluster-wide.

Check+increment is performed in a single Redis Lua script so two
concurrent replicas cannot both pass the pre-check and both increment
past the limit. When Redis is unavailable (e.g. Onyx Lite deployments
where Redis is an opt-in `--profile redis` service), the rate limiter
fails open with a logged warning so core invite flows continue to work.
"""

from dataclasses import dataclass
from uuid import UUID

from redis import Redis
from redis.exceptions import ConnectionError as RedisConnectionError
from redis.exceptions import RedisError
from redis.exceptions import TimeoutError as RedisTimeoutError

from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.utils.logger import setup_logger

logger = setup_logger()

_SECONDS_PER_MINUTE = 60
_SECONDS_PER_DAY = 24 * 60 * 60

# Rate limits apply to trial tenants only (enforced at call site). Paid
# tenants bypass entirely — their guardrails are seat limits and the
# per-admin lifetime counter. Self-hosted / Lite deployments fail open
# when Redis is unavailable. Values are sized against the trial lifetime
# cap `NUM_FREE_TRIAL_USER_INVITES=10` and the invite→remove→invite
# bypass attack: per-day caps stay tight so a compromised or scripted
# trial admin cannot exceed the lifetime cap even across window rolls,
# and per-minute caps block burst automation while leaving headroom for
# a human typing emails by hand.
_INVITE_ADMIN_PER_MIN = 3
_INVITE_ADMIN_PER_DAY = 10
_INVITE_TENANT_PER_DAY = 15
_REMOVE_ADMIN_PER_MIN = 3
_REMOVE_ADMIN_PER_DAY = 30

# Per-admin buckets are accidentally safe without an explicit tenant
# prefix because admin UUIDs are globally unique. The tenant/day bucket
# MUST embed the tenant_id directly: TenantRedis.__getattribute__ only
# prefixes commands in an explicit allowlist and `eval` is not on it, so
# keys passed to the Lua script reach Redis bare. A key of
# "ratelimit:invite_put:tenant:day" would be shared across every trial
# tenant, exhausting one global counter for the whole cluster.
_INVITE_PUT_ADMIN_MIN_KEY = "ratelimit:invite_put:admin:{user_id}:min"
_INVITE_PUT_ADMIN_DAY_KEY = "ratelimit:invite_put:admin:{user_id}:day"
_INVITE_PUT_TENANT_DAY_KEY = "ratelimit:invite_put:tenant:{tenant_id}:day"
_INVITE_REMOVE_ADMIN_MIN_KEY = "ratelimit:invite_remove:admin:{user_id}:min"
_INVITE_REMOVE_ADMIN_DAY_KEY = "ratelimit:invite_remove:admin:{user_id}:day"

# Atomic multi-bucket check+increment.
# ARGV[1] = N (bucket count). For each bucket i=1..N, ARGV[2+(i-1)*3..4+(i-1)*3]
# carry increment, limit, ttl. KEYS[i] is the bucket's Redis key.
#
# Buckets with limit <= 0 or increment <= 0 are skipped (a disabled tier).
# On reject, returns the 1-indexed bucket number that failed so the caller
# can report which scope tripped; on success returns 0. TTL is set with NX
# semantics so pre-existing keys without a TTL are still given one, but
# fresh increments do not reset the window (fixed-window, not sliding).
_CHECK_AND_INCREMENT_SCRIPT = """
local n = tonumber(ARGV[1])
for i = 1, n do
    local key = KEYS[i]
    local increment = tonumber(ARGV[2 + (i - 1) * 3])
    local limit = tonumber(ARGV[3 + (i - 1) * 3])
    if limit > 0 and increment > 0 then
        local current = tonumber(redis.call('get', key)) or 0
        if current + increment > limit then
            return i
        end
    end
end
for i = 1, n do
    local key = KEYS[i]
    local increment = tonumber(ARGV[2 + (i - 1) * 3])
    local limit = tonumber(ARGV[3 + (i - 1) * 3])
    local ttl = tonumber(ARGV[4 + (i - 1) * 3])
    if limit > 0 and increment > 0 then
        redis.call('incrby', key, increment)
        redis.call('expire', key, ttl, 'NX')
    end
end
return 0
"""


@dataclass(frozen=True)
class _Bucket:
    key: str
    limit: int
    ttl_seconds: int
    scope: str
    increment: int


def _run_atomic(redis_client: Redis, buckets: list[_Bucket]) -> None:
    """Run the check+increment Lua script. Raise OnyxError on rejection.

    On Redis connection / timeout errors the rate limiter fails open: the
    request is allowed through and the failure is logged. This keeps the
    invite flow usable on Onyx Lite deployments (Redis is opt-in there)
    and during transient Redis outages in full deployments.
    """
    if not buckets:
        return

    keys = [b.key for b in buckets]
    argv: list[str] = [str(len(buckets))]
    for b in buckets:
        argv.extend([str(b.increment), str(b.limit), str(b.ttl_seconds)])

    try:
        result = redis_client.eval(  # type: ignore[no-untyped-call]
            _CHECK_AND_INCREMENT_SCRIPT,
            len(keys),
            *keys,
            *argv,
        )
    except (RedisConnectionError, RedisTimeoutError) as e:
        logger.warning(
            "Invite rate limiter skipped — Redis unavailable: %s. Rate limiting is disabled for this request.",
            e,
        )
        return
    except RedisError as e:
        logger.error(
            "Invite rate limiter Redis error, failing open: %s",
            e,
        )
        return

    failed_index = int(result) if isinstance(result, (int, str, bytes)) else 0
    if failed_index <= 0:
        return

    failed_bucket = buckets[failed_index - 1]
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
    redis_client: Redis,
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
    _run_atomic(redis_client, buckets)


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
    _run_atomic(redis_client, buckets)
