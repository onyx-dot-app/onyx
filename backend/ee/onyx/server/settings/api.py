"""EE Settings API - provides license-aware settings override."""

from ee.onyx.db.license import get_cached_license_metadata
from onyx.server.settings.models import ApplicationStatus
from onyx.server.settings.models import Settings
from onyx.utils.logger import setup_logger
from shared_configs.configs import MULTI_TENANT
from shared_configs.contextvars import get_current_tenant_id

logger = setup_logger()


def apply_license_status_to_settings(settings: Settings) -> Settings:
    """EE version: checks license status for self-hosted deployments."""
    if MULTI_TENANT:
        return settings

    tenant_id = get_current_tenant_id()
    try:
        metadata = get_cached_license_metadata(tenant_id)
        if metadata:
            if metadata.status == ApplicationStatus.GATED_ACCESS:
                settings.application_status = ApplicationStatus.GATED_ACCESS
            elif metadata.status == ApplicationStatus.GRACE_PERIOD:
                settings.application_status = ApplicationStatus.GRACE_PERIOD
            elif metadata.status == ApplicationStatus.PAYMENT_REMINDER:
                settings.application_status = ApplicationStatus.PAYMENT_REMINDER
        else:
            settings.application_status = ApplicationStatus.GATED_ACCESS
    except Exception as e:
        logger.warning(f"Failed to check license metadata for settings: {e}")

    return settings
