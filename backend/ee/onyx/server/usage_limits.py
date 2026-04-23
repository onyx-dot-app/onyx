"""EE Usage limits - trial detection via billing information."""

from ee.onyx.server.billing.billing_cache import cached_fetch_billing_information
from ee.onyx.server.tenants.models import BillingInformation
from ee.onyx.server.tenants.models import SubscriptionStatusResponse
from onyx.utils.logger import setup_logger
from shared_configs.configs import MULTI_TENANT

logger = setup_logger()


def is_tenant_on_trial(tenant_id: str) -> bool:
    """
    Determine if a tenant is currently on a trial subscription.

    In multi-tenant mode, we fetch billing information from the control plane
    to determine if the tenant has an active trial. The fetch is cached in
    Redis (see ``ee.onyx.server.billing.billing_cache``) so high-frequency
    callers like ``_check_chunk_usage_limit`` don't fan out to the control
    plane once per document batch.
    """
    if not MULTI_TENANT:
        return False

    try:
        billing_info = cached_fetch_billing_information(tenant_id)

        # If not subscribed at all, check if we have trial information
        if isinstance(billing_info, SubscriptionStatusResponse):
            # No subscription means they're likely on trial (new tenant)
            return True

        if isinstance(billing_info, BillingInformation):
            return billing_info.status == "trialing"

        return False

    except Exception as e:
        logger.warning(f"Failed to fetch billing info for trial check: {e}")
        # Default to trial limits on error (more restrictive = safer)
        return True
