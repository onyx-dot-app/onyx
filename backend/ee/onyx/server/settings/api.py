"""EE Settings API - provides license-aware settings override."""

from ee.onyx.db.license import get_cached_license_metadata
from onyx.server.settings.models import ApplicationStatus
from onyx.server.settings.models import Settings
from onyx.utils.logger import setup_logger
from shared_configs.configs import MULTI_TENANT
from shared_configs.contextvars import get_current_tenant_id

logger = setup_logger()


def apply_license_status_to_settings(settings: Settings) -> Settings:
    """EE version: checks license status for self-hosted deployments.

    For self-hosted, looks up license metadata and overrides application_status
    if the license is missing or expired.

    For multi-tenant (cloud), the settings already have the correct status
    from the control plane, so no override is needed.
    """
    # Multi-tenant uses the status from settings (set by control plane)
    if MULTI_TENANT:
        return settings

    # For self-hosted, check license metadata
    tenant_id = get_current_tenant_id()
    try:
        metadata = get_cached_license_metadata(tenant_id)
        if metadata:
            # Use the license status if it indicates a problem
            if metadata.status == ApplicationStatus.GATED_ACCESS:
                settings.application_status = ApplicationStatus.GATED_ACCESS
            elif metadata.status == ApplicationStatus.GRACE_PERIOD:
                settings.application_status = ApplicationStatus.GRACE_PERIOD
            elif metadata.status == ApplicationStatus.PAYMENT_REMINDER:
                settings.application_status = ApplicationStatus.PAYMENT_REMINDER
            # If metadata.status is ACTIVE, keep whatever was in settings
        else:
            # No license = gated access for self-hosted EE
            logger.debug(
                f"No license metadata found for tenant {tenant_id}, "
                "setting status to GATED_ACCESS"
            )
            settings.application_status = ApplicationStatus.GATED_ACCESS
    except Exception as e:
        logger.warning(f"Failed to check license metadata for settings: {e}")
        # On error, keep existing settings (fail open for settings display)

    return settings
