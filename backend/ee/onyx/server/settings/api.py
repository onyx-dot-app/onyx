"""EE Settings API - provides license-aware settings override."""

from sqlalchemy.exc import SQLAlchemyError

from ee.onyx.configs.app_configs import LICENSE_ENFORCEMENT_ENABLED
from ee.onyx.db.license import get_cached_license_metadata, refresh_license_cache
from ee.onyx.utils.tier import get_tier, tier_from_license_metadata
from onyx.cache.interface import CACHE_TRANSIENT_ERRORS
from onyx.configs.app_configs import ENTERPRISE_EDITION_ENABLED
from onyx.db.engine.sql_engine import get_session_with_current_tenant
from onyx.server.settings.models import ApplicationStatus, Settings, Tier
from onyx.utils.logger import setup_logger
from onyx.utils.variable_functionality import global_version
from shared_configs.configs import MULTI_TENANT
from shared_configs.contextvars import get_current_tenant_id

logger = setup_logger()

# Only GATED_ACCESS actually blocks access - other statuses are for notifications
_BLOCKING_STATUS = ApplicationStatus.GATED_ACCESS


def apply_license_status_to_settings(settings: Settings) -> Settings:
    """EE version: checks license status for self-hosted deployments.

    For self-hosted, looks up license metadata and overrides application_status
    if the license indicates GATED_ACCESS (fully expired).

    Also sets ee_features_enabled based on license status to control
    visibility of EE features in the UI.

    For multi-tenant (cloud), the settings already have the correct status
    from the control plane, so no override is needed.

    If LICENSE_ENFORCEMENT_ENABLED is false, ee_features_enabled is set to True
    (since EE code was loaded via ENABLE_PAID_ENTERPRISE_EDITION_FEATURES).
    """
    if not LICENSE_ENFORCEMENT_ENABLED:
        # License enforcement disabled - EE code is loaded via
        # ENABLE_PAID_ENTERPRISE_EDITION_FEATURES, so EE features are on
        settings.tier = (
            Tier.ENTERPRISE if global_version.is_ee_version() else Tier.COMMUNITY
        )
        settings.ee_features_enabled = True
        return settings

    if MULTI_TENANT:
        # Cloud mode - EE features always available (gating handled by is_tenant_gated)
        # Cloud tier lives in a separate Redis hash, fetched via get_tier().
        settings.tier = get_tier()
        settings.ee_features_enabled = True
        return settings

    tenant_id = get_current_tenant_id()
    try:
        metadata = get_cached_license_metadata(tenant_id)
        if not metadata:
            # Cache miss (e.g. after TTL expiry). Fall back to DB so
            # the /settings request doesn't falsely return GATED_ACCESS
            # while the cache is cold.
            try:
                with get_session_with_current_tenant() as db_session:
                    metadata = refresh_license_cache(db_session, tenant_id)
            except SQLAlchemyError as db_error:
                logger.warning(
                    "Failed to load license from DB for settings: %s", db_error
                )

        if metadata:
            if metadata.status == _BLOCKING_STATUS:
                settings.application_status = metadata.status
                settings.ee_features_enabled = False
            elif metadata.used_seats > metadata.seats:
                # License is valid but seat limit exceeded
                settings.application_status = ApplicationStatus.SEAT_LIMIT_EXCEEDED
                settings.seat_count = metadata.seats
                settings.used_seats = metadata.used_seats
                settings.ee_features_enabled = True
            else:
                # Has a valid license (GRACE_PERIOD/PAYMENT_REMINDER still allow EE features)
                settings.ee_features_enabled = True
        else:
            # No license found in cache or DB.
            if ENTERPRISE_EDITION_ENABLED:
                # Legacy EE flag is set → prior EE usage (e.g. permission
                # syncing) means indexed data may need protection.
                settings.application_status = _BLOCKING_STATUS
            settings.ee_features_enabled = False
        settings.tier = tier_from_license_metadata(metadata)
    except CACHE_TRANSIENT_ERRORS as e:
        logger.warning("Failed to check license metadata for settings: %s", e)
        # Fail closed - disable EE features if we can't verify license
        settings.ee_features_enabled = False
        settings.tier = Tier.COMMUNITY

    return settings
