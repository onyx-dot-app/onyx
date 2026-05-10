"""Per-tenant tier resolution.

Cloud: Redis HGET → CP lazy-refresh on miss → BUSINESS fallback.
Self-hosted: ENTERPRISE if EE compiled in, else COMMUNITY (binary; step 2
will replace with license-payload customer_tier).
"""

from __future__ import annotations

import requests
from redis.exceptions import RedisError

from ee.onyx.server.license.models import CustomerTier
from ee.onyx.server.tenants.billing import fetch_billing_information
from ee.onyx.server.tenants.models import BillingInformation
from ee.onyx.server.tenants.models import SubscriptionStatusResponse
from ee.onyx.server.tenants.tier_management import get_cached_tier
from ee.onyx.server.tenants.tier_management import update_tenant_tier
from onyx.server.settings.models import Tier
from onyx.utils.logger import setup_logger
from onyx.utils.variable_functionality import global_version
from shared_configs.configs import MULTI_TENANT
from shared_configs.contextvars import get_current_tenant_id

logger = setup_logger()


_CUSTOMER_TIER_TO_TIER: dict[CustomerTier, Tier] = {
    CustomerTier.BUSINESS: Tier.BUSINESS,
    CustomerTier.ENTERPRISE: Tier.ENTERPRISE,
}


def _self_hosted_tier() -> Tier:
    return Tier.ENTERPRISE if global_version.is_ee_version() else Tier.COMMUNITY


def _extract_customer_tier(
    billing: BillingInformation | SubscriptionStatusResponse,
) -> CustomerTier | None:
    return getattr(billing, "customer_tier", None)


def _lazy_refresh_from_cp(tenant_id: str) -> CustomerTier | None:
    try:
        billing = fetch_billing_information(tenant_id)
    except (requests.RequestException, ValueError) as e:
        logger.warning(
            "Tier lazy-refresh failed for tenant %s; CP unreachable: %s",
            tenant_id,
            e,
        )
        return None

    return _extract_customer_tier(billing)


def get_tier(tenant_id: str | None = None) -> Tier:
    if not MULTI_TENANT:
        return _self_hosted_tier()

    tid = tenant_id or get_current_tenant_id()

    try:
        cached = get_cached_tier(tid)
    except RedisError as e:
        # Don't try CP either — likely a wider outage; keep failures cheap.
        logger.warning(
            "Tier Redis read failed for tenant %s; falling back to BUSINESS: %s",
            tid,
            e,
        )
        return Tier.BUSINESS

    if cached is not None:
        return _CUSTOMER_TIER_TO_TIER[cached]

    fresh = _lazy_refresh_from_cp(tid)
    if fresh is not None:
        try:
            update_tenant_tier(tid, fresh)
        except RedisError as e:
            logger.warning(
                "Tier Redis write failed for tenant %s after CP refresh: %s",
                tid,
                e,
            )
        return _CUSTOMER_TIER_TO_TIER[fresh]

    # Don't cache the fallback — next call retries the refresh.
    return Tier.BUSINESS
