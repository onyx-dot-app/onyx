"""EE Settings API - provides license-aware settings override."""

from redis.exceptions import RedisError
from sqlalchemy.exc import SQLAlchemyError

from ee.onyx.configs.app_configs import LICENSE_ENFORCEMENT_ENABLED
from ee.onyx.db.license import get_cached_license_metadata
from ee.onyx.db.license import refresh_license_cache
from onyx.configs.app_configs import ENTERPRISE_EDITION_ENABLED
from onyx.db.engine.sql_engine import get_session_with_current_tenant
from onyx.server.settings.models import ApplicationStatus
from onyx.server.settings.models import Settings
from onyx.utils.logger import setup_logger
from shared_configs.configs import MULTI_TENANT
from shared_configs.contextvars import get_current_tenant_id

logger = setup_logger()

# Only GATED_ACCESS actually blocks access - other statuses are for notifications
_BLOCKING_STATUS = ApplicationStatus.GATED_ACCESS


def check_ee_features_enabled() -> bool:
    """EE version: checks if EE features should be available.

    Returns True if:
    - LICENSE_ENFORCEMENT_ENABLED is False (legacy/rollout mode)
    - Cloud mode (MULTI_TENANT) - cloud handles its own gating
    - Self-hosted with a valid (non-expired) license

    Returns False if:
    - Self-hosted with no license (never subscribed)
    - Self-hosted with expired license
    """
    if not LICENSE_ENFORCEMENT_ENABLED:
        # License enforcement disabled - allow EE features (legacy behavior)
        return True

    if MULTI_TENANT:
        # Cloud mode - EE features always available (gating handled by is_tenant_gated)
        return True

    # Self-hosted with enforcement - check for valid license
    tenant_id = get_current_tenant_id()
    try:
        metadata = get_cached_license_metadata(tenant_id)
        if not metadata:
            # Cache miss — warm from DB so cold-start doesn't block EE features
            try:
                with get_session_with_current_tenant() as db_session:
                    metadata = refresh_license_cache(db_session, tenant_id)
            except SQLAlchemyError as db_error:
                logger.warning(f"Failed to load license from DB: {db_error}")

        if metadata and metadata.status != _BLOCKING_STATUS:
            # Has a valid license (GRACE_PERIOD/PAYMENT_REMINDER still allow EE features)
            return True
    except RedisError as e:
        logger.warning(f"Failed to check license for EE features: {e}")
        # Fail closed - if Redis is down, other things will break anyway
        return False

    # No license or GATED_ACCESS - no EE features
    return False


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
        settings.ee_features_enabled = True
        return settings

    if MULTI_TENANT:
        # Cloud mode - EE features always available (gating handled by is_tenant_gated)
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
                    f"Failed to load license from DB for settings: {db_error}"
                )

        if metadata:
            if metadata.status == _BLOCKING_STATUS:
                settings.application_status = metadata.status
                settings.ee_features_enabled = False
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
    except RedisError as e:
        logger.warning(f"Failed to check license metadata for settings: {e}")
        # Fail closed - disable EE features if we can't verify license
        settings.ee_features_enabled = False

    return settings
