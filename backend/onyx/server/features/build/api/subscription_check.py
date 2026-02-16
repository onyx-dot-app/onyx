"""Subscription detection for Build Mode rate limiting."""

from sqlalchemy.orm import Session

from onyx.configs.app_configs import DEV_MODE
from onyx.db.models import User
from onyx.server.usage_limits import is_tenant_on_trial_fn
from onyx.utils.logger import setup_logger
from shared_configs.configs import MULTI_TENANT
from shared_configs.contextvars import get_current_tenant_id

logger = setup_logger()


def is_user_subscribed(user: User, db_session: Session) -> bool:  # noqa: ARG001
    """
    Check if a user has an active subscription.

    For cloud (MULTI_TENANT=true):
        - Checks Stripe billing via control plane
        - Returns True if tenant is NOT on trial (subscribed = NOT on trial)

    For self-hosted (MULTI_TENANT=false):
        - Checks license metadata
        - Returns True if license status is ACTIVE

    Args:
        user: The user object (None for unauthenticated users)
        db_session: Database session

    Returns:
        True if user has active subscription, False otherwise
    """
    if DEV_MODE:
        return True

    if user is None:
        return False

    if MULTI_TENANT:
        # Cloud: check Stripe billing via control plane
        tenant_id = get_current_tenant_id()
        try:
            on_trial = is_tenant_on_trial_fn(tenant_id)
            # Subscribed = NOT on trial
            return not on_trial
        except Exception as e:
            logger.warning(f"Subscription check failed for tenant {tenant_id}: {e}")
            # Default to non-subscribed (safer/more restrictive)
            return False

    return True
