"""EE Settings API - provides license-aware settings override."""

from redis.exceptions import RedisError

from ee.onyx.configs.app_configs import LICENSE_ENFORCEMENT_ENABLED
from ee.onyx.db.license import get_cached_license_metadata
from onyx.server.settings.models import ApplicationStatus
from onyx.server.settings.models import Settings
from onyx.utils.logger import setup_logger
from shared_configs.configs import MULTI_TENANT
from shared_configs.contextvars import get_current_tenant_id

logger = setup_logger()

# Statuses that indicate a billing/license problem - propagate these to settings
_GATED_STATUSES = frozenset(
    {
        ApplicationStatus.GATED_ACCESS,
        ApplicationStatus.GRACE_PERIOD,
        ApplicationStatus.PAYMENT_REMINDER,
    }
)


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
        if metadata and metadata.status != ApplicationStatus.GATED_ACCESS:
            # Has a valid (non-expired) license
            return True
    except RedisError as e:
        logger.warning(f"Failed to check license for EE features: {e}")
        # Fail open - don't break the UI if Redis is down
        return True

    # No license or expired license - no EE features
    return False


def apply_license_status_to_settings(settings: Settings) -> Settings:
    """EE version: checks license status for self-hosted deployments.

    For self-hosted, looks up license metadata and overrides application_status
    if the license is missing or indicates a problem (expired, grace period, etc.).

    For multi-tenant (cloud), the settings already have the correct status
    from the control plane, so no override is needed.

    If LICENSE_ENFORCEMENT_ENABLED is false, settings are returned unchanged,
    allowing the product to function normally without license checks.
    """
    if not LICENSE_ENFORCEMENT_ENABLED:
        return settings

    if MULTI_TENANT:
        return settings

    tenant_id = get_current_tenant_id()
    try:
        metadata = get_cached_license_metadata(tenant_id)
        if metadata and metadata.status in _GATED_STATUSES:
            settings.application_status = metadata.status
        # No license = user hasn't purchased yet, allow access for upgrade flow
        # This is different from an expired license - community features should work
    except RedisError as e:
        logger.warning(f"Failed to check license metadata for settings: {e}")

    return settings
