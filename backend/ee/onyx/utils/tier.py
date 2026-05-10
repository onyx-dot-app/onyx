"""Per-tenant tier resolution.

Cloud: Redis HGET → CP lazy-refresh on miss → BUSINESS fallback.
Self-hosted: license_payload.customer_tier (legacy licenses lacking the
field default to ENTERPRISE).
"""

from __future__ import annotations

import requests
from redis.exceptions import RedisError
from sqlalchemy.exc import SQLAlchemyError

from ee.onyx.configs.app_configs import LICENSE_ENFORCEMENT_ENABLED
from ee.onyx.db.license import get_cached_license_metadata
from ee.onyx.db.license import refresh_license_cache
from ee.onyx.server.license.models import CustomerTier
from ee.onyx.server.tenants.billing import fetch_billing_information
from ee.onyx.server.tenants.models import BillingInformation
from ee.onyx.server.tenants.models import SubscriptionStatusResponse
from ee.onyx.server.tenants.tier_management import get_cached_tier
from ee.onyx.server.tenants.tier_management import update_tenant_tier
from onyx.db.engine.sql_engine import get_session_with_current_tenant
from onyx.server.settings.models import ApplicationStatus
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


def tier_from_license_metadata(metadata: object | None) -> Tier:
    """Map a cached LicenseMetadata to a Tier.

    Shared by `_self_hosted_tier()` and `apply_license_status_to_settings`
    so they don't both have to read Redis when one already has the metadata
    in hand.
    """
    if metadata is None:
        return Tier.COMMUNITY
    status = getattr(metadata, "status", None)
    if status == ApplicationStatus.GATED_ACCESS:
        return Tier.COMMUNITY
    customer_tier = getattr(metadata, "customer_tier", None)
    if not isinstance(customer_tier, CustomerTier):
        # None (legacy license) or unrecognized -> ENTERPRISE for back-compat.
        return Tier.ENTERPRISE
    return _CUSTOMER_TIER_TO_TIER[customer_tier]


def _self_hosted_tier() -> Tier:
    if not LICENSE_ENFORCEMENT_ENABLED:
        # Legacy mode: no per-tier resolution; preserve binary.
        return Tier.ENTERPRISE if global_version.is_ee_version() else Tier.COMMUNITY

    metadata = get_cached_license_metadata()
    if metadata is None:
        try:
            with get_session_with_current_tenant() as db_session:
                metadata = refresh_license_cache(db_session)
        except SQLAlchemyError as e:
            logger.warning("Self-hosted tier: license DB read failed: %s", e)
            return Tier.COMMUNITY

    return tier_from_license_metadata(metadata)


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
