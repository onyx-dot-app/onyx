"""Redis helpers for the tenant work-gating feature.

One sorted set `active_tenants` under the cloud Redis tenant tracks the last
time each tenant was observed doing work. The fanout generator reads the set
(filtered to entries within a TTL window) and skips tenants that haven't been
active recently.

All public functions no-op in single-tenant mode (`MULTI_TENANT=False`).
"""

import time
from typing import cast

from redis.client import Redis

from onyx.configs.constants import ONYX_CLOUD_TENANT_ID
from onyx.redis.redis_pool import get_redis_client
from onyx.utils.logger import setup_logger
from shared_configs.configs import MULTI_TENANT

logger = setup_logger()


# Unprefixed key. `TenantRedis._prefixed` prepends `cloud:` at call time so
# the full rendered key is `cloud:active_tenants`.
_SET_KEY = "active_tenants"


def _now_ms() -> int:
    return int(time.time() * 1000)


def _client() -> Redis:
    return get_redis_client(tenant_id=ONYX_CLOUD_TENANT_ID)


def mark_tenant_active(tenant_id: str) -> None:
    """Record that `tenant_id` was just observed doing work (ZADD with the
    current timestamp as the score). Best-effort — a Redis failure is logged
    and swallowed so it never breaks a writer path.

    Raw write; does not check the feature flag. Writer call sites should
    use `maybe_mark_tenant_active` instead so the feature flag gates the
    ZADD.
    """
    if not MULTI_TENANT:
        return

    try:
        # `mapping={member: score}` syntax; ZADD overwrites the score on
        # existing members, which is exactly the refresh semantics we want.
        _client().zadd(_SET_KEY, mapping={tenant_id: _now_ms()})
    except Exception:
        logger.exception(f"mark_tenant_active failed: tenant_id={tenant_id}")


def maybe_mark_tenant_active(tenant_id: str) -> None:
    """Convenience wrapper for writer call sites: records the tenant only
    when the feature flag is on. Fully defensive — never raises, so a Redis
    outage or flag-read failure can't abort the calling task."""
    try:
        # Local import to avoid a module-load cycle: OnyxRuntime imports
        # onyx.redis.redis_pool, so a top-level import here would wedge on
        # certain startup paths.
        from onyx.server.runtime.onyx_runtime import OnyxRuntime

        if not OnyxRuntime.get_tenant_work_gating_enabled():
            return
        mark_tenant_active(tenant_id)
    except Exception:
        logger.exception(f"maybe_mark_tenant_active failed: tenant_id={tenant_id}")


def get_active_tenants(ttl_seconds: int) -> set[str] | None:
    """Return tenants whose last-seen timestamp is within `ttl_seconds` of
    now.

    Return values:
    - `set[str]` (possibly empty) — Redis read succeeded. Empty set means
      no tenants are currently marked active; callers should *skip* all
      tenants if the gate is enforcing.
    - `None` — Redis read failed *or* we are in single-tenant mode. Callers
      should fail open (dispatch to every tenant this cycle). Distinguishing
      failure from "genuinely empty" prevents a Redis outage from silently
      starving every tenant on every enforced cycle.
    """
    if not MULTI_TENANT:
        return None

    cutoff_ms = _now_ms() - (ttl_seconds * 1000)
    try:
        raw = cast(
            list[bytes],
            _client().zrangebyscore(_SET_KEY, min=cutoff_ms, max="+inf"),
        )
    except Exception:
        logger.exception("get_active_tenants failed")
        return None

    return {m.decode() if isinstance(m, bytes) else m for m in raw}


def cleanup_expired(ttl_seconds: int) -> int:
    """Remove members older than `ttl_seconds` from the set. Optional
    memory-hygiene helper — correctness does not depend on calling this, but
    without it the set grows unboundedly as old tenants accumulate. Returns
    the number of members removed."""
    if not MULTI_TENANT:
        return 0

    cutoff_ms = _now_ms() - (ttl_seconds * 1000)
    try:
        removed = cast(
            int,
            _client().zremrangebyscore(_SET_KEY, min="-inf", max=f"({cutoff_ms}"),
        )
        return removed
    except Exception:
        logger.exception("cleanup_expired failed")
        return 0
