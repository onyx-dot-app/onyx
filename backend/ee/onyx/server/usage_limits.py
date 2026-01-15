"""EE Usage limits - trial detection via billing information."""

from datetime import datetime
from datetime import timezone

from ee.onyx.server.tenants.billing import fetch_billing_information
from ee.onyx.server.tenants.models import BillingInformation
from ee.onyx.server.tenants.models import SubscriptionStatusResponse
from onyx.utils.logger import setup_logger
from shared_configs.configs import MULTI_TENANT

logger = setup_logger()


def is_tenant_on_trial(tenant_id: str) -> bool:
    """
    Determine if a tenant is currently on a trial subscription.

    In multi-tenant mode, we fetch billing information from the control plane
    to determine if the tenant has an active trial.
    """
    if not MULTI_TENANT:
        return False

    try:
        billing_info = fetch_billing_information(tenant_id)

        # If not subscribed at all, check if we have trial information
        if isinstance(billing_info, SubscriptionStatusResponse):
            # No subscription means they're likely on trial (new tenant)
            return True

        if isinstance(billing_info, BillingInformation):
            # Check if trial is active
            if billing_info.trial_end is not None:
                now = datetime.now(timezone.utc)
                # Trial active if trial_end is in the future
                # and subscription status indicates trialing
                if billing_info.trial_end > now and billing_info.status == "trialing":
                    return True

        return False

    except Exception as e:
        logger.warning(f"Failed to fetch billing info for trial check: {e}")
        # Default to trial limits on error (more restrictive = safer)
        return True
