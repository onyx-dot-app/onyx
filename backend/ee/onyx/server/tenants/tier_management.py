"""Per-tenant tier cache (cloud).

Value at TENANT_TIER_KEY is a JSON blob:
    {"customer_tier": "business", "trial_end": "2026-06-01T12:00:00+00:00" | null}
"""

import json
from datetime import datetime
from typing import NamedTuple
from typing import cast

from ee.onyx.configs.app_configs import TENANT_TIER_CACHE_TTL_SECONDS
from ee.onyx.configs.app_configs import TENANT_TIER_KEY
from ee.onyx.server.license.models import CustomerTier
from onyx.redis.redis_pool import get_redis_client
from onyx.redis.redis_pool import get_redis_replica_client
from onyx.utils.logger import setup_logger

logger = setup_logger()


class CachedTier(NamedTuple):
    customer_tier: CustomerTier
    trial_end: datetime | None


def update_tenant_tier(
    tenant_id: str,
    customer_tier: CustomerTier,
    trial_end: datetime | None = None,
) -> None:
    redis_client = get_redis_client(tenant_id=tenant_id)
    payload = json.dumps(
        {
            "customer_tier": customer_tier.value,
            "trial_end": trial_end.isoformat() if trial_end is not None else None,
        }
    )
    redis_client.set(TENANT_TIER_KEY, payload, ex=TENANT_TIER_CACHE_TTL_SECONDS)


def get_cached_tier(tenant_id: str) -> CachedTier | None:
    redis_client = get_redis_replica_client(tenant_id=tenant_id)
    raw = redis_client.get(TENANT_TIER_KEY)
    if raw is None:
        return None

    value = raw.decode("utf-8") if isinstance(raw, bytes) else cast(str, raw)

    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        logger.warning(
            "Tier cache entry for tenant %s is not valid JSON: %r",
            tenant_id,
            value,
        )
        return None

    if not isinstance(parsed, dict):
        logger.warning(
            "Tier cache entry for tenant %s is not a JSON object: %r",
            tenant_id,
            value,
        )
        return None

    raw_tier = parsed.get("customer_tier")
    if not isinstance(raw_tier, str):
        logger.warning(
            "Tier cache entry for tenant %s missing customer_tier: %r",
            tenant_id,
            value,
        )
        return None

    try:
        customer_tier = CustomerTier(raw_tier)
    except ValueError:
        logger.warning(
            "Unrecognized customer_tier in cache for tenant %s: %r",
            tenant_id,
            raw_tier,
        )
        return None

    raw_trial_end = parsed.get("trial_end")
    trial_end: datetime | None = None
    if isinstance(raw_trial_end, str):
        try:
            trial_end = datetime.fromisoformat(raw_trial_end)
        except ValueError:
            logger.warning(
                "Invalid trial_end ISO string for tenant %s: %r",
                tenant_id,
                raw_trial_end,
            )

    return CachedTier(customer_tier=customer_tier, trial_end=trial_end)
