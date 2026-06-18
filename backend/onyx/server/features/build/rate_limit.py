"""Rate limiting logic for Build Mode."""

from datetime import datetime
from datetime import timedelta
from datetime import timezone
from typing import Literal

from pydantic import BaseModel
from sqlalchemy.orm import Session

from onyx.configs.app_configs import AUTH_TYPE
from onyx.configs.constants import AuthType
from onyx.db.models import User
from onyx.feature_flags.factory import get_default_feature_flag_provider
from onyx.server.features.build.configs import CRAFT_PAID_USER_RATE_LIMIT
from onyx.server.features.build.db.rate_limit import count_user_messages_in_window
from onyx.server.features.build.db.rate_limit import count_user_messages_total
from onyx.server.features.build.db.rate_limit import get_oldest_message_timestamp
from onyx.server.features.build.subscription_check import is_user_subscribed
from onyx.server.features.build.utils import CRAFT_HAS_USAGE_LIMITS
from shared_configs.configs import MULTI_TENANT
from shared_configs.contextvars import get_current_tenant_id

# Default limit for free/non-subscribed users (not configurable)
FREE_USER_RATE_LIMIT = 5


class RateLimitResponse(BaseModel):
    """Rate limit information."""

    is_limited: bool
    limit_type: str  # "weekly" or "total"
    messages_used: int
    limit: int
    reset_timestamp: str | None = None


def _should_skip_rate_limiting(user: User) -> bool:
    """
    Check if rate limiting should be skipped for this user.

    Grants unlimited usage to tenants/users whose `craft-has-usage-limits`
    PostHog flag is off (e.g. tenant_dev). Only reached on Onyx Cloud, where
    PostHog is configured.

    Returns:
        True to skip rate limiting (unlimited), False to apply normal limits
    """
    # NOTE: We can modify the posthog flag to return more detail about a limit
    # i.e. can set variable limits per user and tenant via PostHog instead of env vars
    # to avoid re-deploying on every limit change

    feature_flag_provider = get_default_feature_flag_provider()
    # Flag returns True for users who SHOULD be rate limited
    # We negate to get: True = skip rate limiting
    has_rate_limit = feature_flag_provider.feature_enabled_for_user_tenant(
        CRAFT_HAS_USAGE_LIMITS,
        user,
        get_current_tenant_id(),
    )
    return not has_rate_limit


def get_user_rate_limit_status(
    user: User,
    db_session: Session,
) -> RateLimitResponse:
    """
    Get the rate limit status for a user.

    Rate limits apply on Onyx Cloud only:
        - Subscribed users: CRAFT_PAID_USER_RATE_LIMIT messages per week
          (configurable, default 25)
        - Non-subscribed users: 5 messages (lifetime total)
        - Per-tenant/user overrides via the `craft-has-usage-limits` PostHog flag

    All non-cloud deployments (self-hosted, managed) are unlimited.

    Args:
        user: The authenticated user
        db_session: Database session

    Returns:
        RateLimitResponse with current limit status
    """
    # Rate limits apply only on Onyx Cloud (multi-tenant); all other deployments
    # are unlimited.
    if not MULTI_TENANT or AUTH_TYPE != AuthType.CLOUD:
        return RateLimitResponse(
            is_limited=False,
            limit_type="weekly",
            messages_used=0,
            limit=0,  # 0 indicates unlimited
            reset_timestamp=None,
        )

    # Check if user should skip rate limiting (e.g., dev tenant users)
    if _should_skip_rate_limiting(user):
        return RateLimitResponse(
            is_limited=False,
            limit_type="weekly",
            messages_used=-1,
            limit=0,  # 0 indicates unlimited
            reset_timestamp=None,
        )

    # Determine subscription status
    is_subscribed = is_user_subscribed(user)

    # Get limit based on subscription status
    limit = CRAFT_PAID_USER_RATE_LIMIT if is_subscribed else FREE_USER_RATE_LIMIT

    # Limit type: weekly for subscribed users, total for free
    limit_type: Literal["weekly", "total"] = "weekly" if is_subscribed else "total"

    # Count messages
    if limit_type == "weekly":
        # Subscribed: rolling 7-day window
        cutoff_time = datetime.now(tz=timezone.utc) - timedelta(days=7)
        messages_used = count_user_messages_in_window(user.id, cutoff_time, db_session)

        # Calculate reset timestamp (when oldest message ages out)
        # Only show reset time if user is at or over the limit
        if messages_used >= limit:
            oldest_msg = get_oldest_message_timestamp(user.id, cutoff_time, db_session)
            if oldest_msg:
                reset_time = oldest_msg + timedelta(days=7)
                reset_timestamp = reset_time.isoformat()
            else:
                reset_timestamp = None
        else:
            reset_timestamp = None
    else:
        # Non-subscribed: lifetime total
        messages_used = count_user_messages_total(user.id, db_session)
        reset_timestamp = None

    return RateLimitResponse(
        is_limited=messages_used >= limit,
        limit_type=limit_type,
        messages_used=messages_used,
        limit=limit,
        reset_timestamp=reset_timestamp,
    )
