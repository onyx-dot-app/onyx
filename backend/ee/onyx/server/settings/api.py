"""EE Settings API - provides license-aware settings override."""

from redis.exceptions import RedisError

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


def apply_license_status_to_settings(settings: Settings) -> Settings:
    """EE version: checks license status for self-hosted deployments.

    For self-hosted, looks up license metadata and overrides application_status
    if the license is missing or indicates a problem (expired, grace period, etc.).

    For multi-tenant (cloud), the settings already have the correct status
    from the control plane, so no override is needed.
    """
    if MULTI_TENANT:
        return settings

    tenant_id = get_current_tenant_id()
    try:
        metadata = get_cached_license_metadata(tenant_id)
        if metadata and metadata.status in _GATED_STATUSES:
            settings.application_status = metadata.status
        elif not metadata:
            # No license = gated access for self-hosted EE
            settings.application_status = ApplicationStatus.GATED_ACCESS
    except RedisError as e:
        logger.warning(f"Failed to check license metadata for settings: {e}")

    return settings
