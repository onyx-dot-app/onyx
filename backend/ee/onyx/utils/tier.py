"""Per-tenant tier resolution.

Cloud: Redis HGET → CP lazy-refresh on miss → BUSINESS fallback.
Self-hosted: license_payload.customer_tier (legacy licenses lacking the
field default to ENTERPRISE).

Trial state never changes the resolved tier: a trialing tenant gets exactly
the feature set it will hold when the trial expires. `trial_end` stays in
the CP push and the cache entry for contract stability, not for resolution.
"""

from __future__ import annotations

from datetime import datetime

import requests
from redis.exceptions import RedisError
from sqlalchemy.exc import ProgrammingError, SQLAlchemyError

from ee.onyx.configs.app_configs import LICENSE_ENFORCEMENT_ENABLED
from ee.onyx.db.license import get_cached_license_metadata, refresh_license_cache
from ee.onyx.server.license.models import CustomerTier
from ee.onyx.server.tenants.billing import fetch_billing_information
from ee.onyx.server.tenants.models import BillingInformation, SubscriptionStatusResponse
from ee.onyx.server.tenants.tier_management import get_cached_tier, update_tenant_tier
from onyx.db.engine.sql_engine import get_session_with_current_tenant
from onyx.db.enums import AccessType
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.server.settings.models import ApplicationStatus, Tier
from onyx.server.settings.tier_order import tier_at_least
from onyx.utils.logger import setup_logger
from onyx.utils.variable_functionality import global_version
from shared_configs.configs import MULTI_TENANT
from shared_configs.contextvars import get_current_tenant_id

logger = setup_logger()


_CUSTOMER_TIER_TO_TIER: dict[CustomerTier, Tier] = {
    CustomerTier.BUSINESS: Tier.BUSINESS,
    CustomerTier.ENTERPRISE: Tier.ENTERPRISE,
}


def _effective_tier(customer_tier: CustomerTier) -> Tier:
    # Use the BUSINESS floor for an unknown cloud tier.
    return _CUSTOMER_TIER_TO_TIER.get(customer_tier, Tier.BUSINESS)


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
        # Mirrors apply_license_status_to_settings (settings/api.py:87-92):
        # legacy / dev-mode self-host where EE code is loaded via
        # ENABLE_PAID_ENTERPRISE_EDITION_FEATURES but no license is required.
        # Treat as ENTERPRISE so tier_gate doesn't 402 EE endpoints.
        return Tier.ENTERPRISE if global_version.is_ee_version() else Tier.COMMUNITY

    try:
        metadata = get_cached_license_metadata()
    except RedisError as e:
        # Treat cache failure as a miss so the existing DB-fallback path
        # below still has a chance to resolve the correct tier.
        logger.warning("Self-hosted tier: license cache read failed: %s", e)
        metadata = None

    if metadata is None:
        try:
            with get_session_with_current_tenant() as db_session:
                metadata = refresh_license_cache(db_session)
        except ProgrammingError as e:
            # Missing table in incomplete schema (e.g. missing license table)
            logger.warning("Self-hosted tier: license table missing: %s", e)
            return Tier.COMMUNITY
        except SQLAlchemyError as e:
            logger.warning("Self-hosted tier: license DB read failed: %s", e)
            return Tier.COMMUNITY

    return tier_from_license_metadata(metadata)


def _extract_billing_state(
    billing: BillingInformation | SubscriptionStatusResponse,
) -> tuple[CustomerTier, datetime | None] | None:
    customer_tier = getattr(billing, "customer_tier", None)
    if customer_tier is None:
        return None
    trial_end = getattr(billing, "trial_end", None)
    if not isinstance(trial_end, datetime):
        trial_end = None
    elif trial_end.tzinfo is None or trial_end.tzinfo.utcoffset(trial_end) is None:
        logger.warning("CP returned naive trial_end; dropping: %r", trial_end)
        trial_end = None
    return customer_tier, trial_end


def _lazy_refresh_from_cp(
    tenant_id: str,
) -> tuple[CustomerTier, datetime | None] | None:
    try:
        billing = fetch_billing_information(tenant_id)
    except (requests.RequestException, ValueError) as e:
        logger.warning(
            "Tier lazy-refresh failed for tenant %s; CP unreachable: %s",
            tenant_id,
            e,
        )
        return None

    return _extract_billing_state(billing)


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
        return _effective_tier(cached.customer_tier)

    fresh = _lazy_refresh_from_cp(tid)
    if fresh is not None:
        fresh_tier, fresh_trial_end = fresh
        try:
            update_tenant_tier(tid, fresh_tier, fresh_trial_end)
        except RedisError as e:
            logger.warning(
                "Tier Redis write failed for tenant %s after CP refresh: %s",
                tid,
                e,
            )
        return _effective_tier(fresh_tier)

    # Don't cache the fallback — next call retries the refresh.
    return Tier.BUSINESS


def require_business_tier_for_sync_access(access_type: AccessType) -> None:
    """Raise FEATURE_NOT_AVAILABLE if SYNC access is requested below BUSINESS.

    Auto-permission-sync requires connector-side permission tracking, which
    is a Business+ feature. Failing at create/edit time means cc-pairs with
    SYNC access only exist on tenants that can actually run the sync —
    instead of letting the row land and silently never sync.

    Mirrors `apply_license_status_to_settings`: with
    LICENSE_ENFORCEMENT_ENABLED=False, treat the tenant as ENTERPRISE so
    legacy EE deployments without a license aren't broken.
    """
    if access_type != AccessType.SYNC:
        return
    if not LICENSE_ENFORCEMENT_ENABLED:
        return
    if not tier_at_least(get_tier(), Tier.BUSINESS):
        raise OnyxError(
            OnyxErrorCode.FEATURE_NOT_AVAILABLE,
            "Auto-sync access requires the Business or Enterprise plan.",
        )


def require_business_tier_for_multi_sso() -> None:
    """Gate a second simultaneously enabled SSO provider to Business or
    above. A single enabled provider works at every tier.
    LICENSE_ENFORCEMENT_ENABLED=False passes, matching the sync-access
    guard."""
    if not LICENSE_ENFORCEMENT_ENABLED:
        return
    if not tier_at_least(get_tier(), Tier.BUSINESS):
        raise OnyxError(
            OnyxErrorCode.FEATURE_NOT_AVAILABLE,
            "Multiple enabled SSO providers require the Business or Enterprise plan.",
        )
