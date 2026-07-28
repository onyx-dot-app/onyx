"""EE Usage limits - trial detection via billing information."""

from ee.onyx.server.billing.billing_cache import cached_is_tenant_on_trial
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
