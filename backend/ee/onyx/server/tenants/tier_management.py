"""Per-tenant tier cache (cloud)."""

from typing import cast

from ee.onyx.configs.app_configs import TENANT_TIER_CACHE_TTL_SECONDS
from ee.onyx.configs.app_configs import TENANT_TIER_KEY
from ee.onyx.server.license.models import CustomerTier
from onyx.redis.redis_pool import get_redis_client
from onyx.redis.redis_pool import get_redis_replica_client
from onyx.utils.logger import setup_logger

logger = setup_logger()


def update_tenant_tier(tenant_id: str, customer_tier: CustomerTier) -> None:
    redis_client = get_redis_client(tenant_id=tenant_id)
    redis_client.set(
        TENANT_TIER_KEY, customer_tier.value, ex=TENANT_TIER_CACHE_TTL_SECONDS
    )


def get_cached_tier(tenant_id: str) -> CustomerTier | None:
    redis_client = get_redis_replica_client(tenant_id=tenant_id)
    raw = redis_client.get(TENANT_TIER_KEY)
    if raw is None:
        return None

    value = raw.decode("utf-8") if isinstance(raw, bytes) else cast(str, raw)
    try:
        return CustomerTier(value)
    except ValueError:
        # Defensive: corrupted entry shouldn't poison the reader.
        logger.warning(
            "Unrecognized tier value in Redis for tenant %s: %r", tenant_id, value
        )
        return None
