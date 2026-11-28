"""EE usage limits: trial detection from billing, and each playground
tenant's trial start and overrides from the control plane."""

from datetime import datetime

from ee.onyx.server.billing.billing_cache import cached_is_tenant_on_trial
from ee.onyx.server.tenants.usage_limit_cache import (
    cached_tenant_limit_override,
    cached_tenant_trial_start,
)
from onyx.db.usage import UsageType
from onyx.utils.logger import setup_logger
from shared_configs.configs import MULTI_TENANT

logger = setup_logger()


def is_tenant_on_trial(tenant_id: str) -> bool:
    """
    Determine if a tenant is currently on a trial subscription.

    Delegates to ``cached_is_tenant_on_trial`` so the billing fetch is cached
    in Redis (see ``ee.onyx.server.billing.billing_cache``) and the trial
    status set lives in exactly one place. High-frequency callers like
    ``_check_chunk_usage_limit`` therefore don't fan out to the control plane
    once per document batch.
    """
    if not MULTI_TENANT:
        return False

    try:
        return cached_is_tenant_on_trial(tenant_id)
    except Exception as e:
        logger.warning("Failed to fetch billing info for trial check: %s", e)
        # Default to trial limits on error (more restrictive = safer)
        return True


def tenant_trial_start(tenant_id: str) -> datetime | None:
    """When the playground tenant's trial started, from the control plane.
    None if it is not known."""
    if not MULTI_TENANT:
        return None
    try:
        return cached_tenant_trial_start(tenant_id)
    except Exception as e:
        logger.warning("Failed to read the trial start of tenant %s: %s", tenant_id, e)
        return None


def tenant_limit_override(tenant_id: str, usage_type: UsageType) -> int | None:
    """The playground tenant's override for one usage type, from the control
    plane. None if it has none or it cannot be read: the plan's amount applies."""
    if not MULTI_TENANT:
        return None
    try:
        return cached_tenant_limit_override(tenant_id, usage_type)
    except Exception as e:
        logger.warning("Failed to read the overrides of tenant %s: %s", tenant_id, e)
        return None
