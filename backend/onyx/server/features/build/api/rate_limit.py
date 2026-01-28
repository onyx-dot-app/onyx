"""Rate limiting logic for Build Mode."""

from datetime import datetime
from datetime import timedelta
from datetime import timezone
from typing import Literal

from sqlalchemy.orm import Session

from onyx.db.models import User
from onyx.server.features.build.api.models import RateLimitResponse
from onyx.server.features.build.api.subscription_check import is_user_subscribed
from onyx.server.features.build.configs import CRAFT_PAID_USER_RATE_LIMIT
from onyx.server.features.build.configs import CRAFT_USER_RATE_LIMIT_OVERRIDES
from onyx.server.features.build.db.rate_limit import count_user_messages_in_window
from onyx.server.features.build.db.rate_limit import count_user_messages_total
from onyx.server.features.build.db.rate_limit import get_oldest_message_timestamp
from shared_configs.configs import MULTI_TENANT

# Default limit for free/non-subscribed users (not configurable)
FREE_USER_RATE_LIMIT = 5


def _get_user_rate_limit(user: User | None, is_subscribed: bool) -> int:
    """
    Get the rate limit for a user.

    Priority:
    1. Per-user override (from CRAFT_USER_RATE_LIMIT_OVERRIDES env var)
    2. Paid user limit (from CRAFT_PAID_USER_RATE_LIMIT env var, default 25)
    3. Free user limit (5, not configurable)

    Args:
        user: The user object (None for unauthenticated users)
        is_subscribed: Whether the user has a paid subscription

    Returns:
        The rate limit for this user
    """
    # Check for per-user override first
    if user and user.email and user.email in CRAFT_USER_RATE_LIMIT_OVERRIDES:
        return CRAFT_USER_RATE_LIMIT_OVERRIDES[user.email]

    # Use subscription-based limit
    if is_subscribed:
        return CRAFT_PAID_USER_RATE_LIMIT
    return FREE_USER_RATE_LIMIT


def get_user_rate_limit_status(
    user: User,
    db_session: Session,
) -> RateLimitResponse:
    """
    Get the rate limit status for a user.

    Rate limits:
        - Cloud (MULTI_TENANT=true):
            - Subscribed users: CRAFT_PAID_USER_RATE_LIMIT messages per week
              (configurable, default 25)
            - Non-subscribed users: 5 messages (lifetime total)
            - Per-user overrides via CRAFT_USER_RATE_LIMIT_OVERRIDES
        - Self-hosted (MULTI_TENANT=false):
            - Unlimited (no rate limiting)

    Args:
        user: The user object (None for unauthenticated users)
        db_session: Database session

    Returns:
        RateLimitResponse with current limit status
    """
    # Self-hosted deployments have no rate limits
    if not MULTI_TENANT:
        return RateLimitResponse(
            is_limited=False,
            limit_type="weekly",
            messages_used=0,
            limit=0,  # 0 indicates unlimited
            reset_timestamp=None,
        )

    # Determine subscription status
    is_subscribed = is_user_subscribed(user, db_session)

    # Get limit (considers per-user overrides and subscription status)
    limit = _get_user_rate_limit(user, is_subscribed)

    # Limit type: weekly for subscribed users (or users with overrides), total for free
    # Users with overrides are treated as subscribed for limit type purposes
    has_override = user and user.email and user.email in CRAFT_USER_RATE_LIMIT_OVERRIDES
    limit_type: Literal["weekly", "total"] = (
        "weekly" if is_subscribed or has_override else "total"
    )

    # Count messages
    user_id = user.id if user else None
    if user_id is None:
        # Unauthenticated users have no usage
        messages_used = 0
        reset_timestamp = None
    elif limit_type == "weekly":
        # Subscribed: rolling 7-day window
        cutoff_time = datetime.now(tz=timezone.utc) - timedelta(days=7)
        messages_used = count_user_messages_in_window(user_id, cutoff_time, db_session)

        # Calculate reset timestamp (when oldest message ages out)
        # Only show reset time if user is at or over the limit
        if messages_used >= limit:
            oldest_msg = get_oldest_message_timestamp(user_id, cutoff_time, db_session)
            if oldest_msg:
                reset_time = oldest_msg + timedelta(days=7)
                reset_timestamp = reset_time.isoformat()
            else:
                reset_timestamp = None
        else:
            reset_timestamp = None
    else:
        # Non-subscribed: lifetime total
        messages_used = count_user_messages_total(user_id, db_session)
        reset_timestamp = None

    return RateLimitResponse(
        is_limited=messages_used >= limit,
        limit_type=limit_type,
        messages_used=messages_used,
        limit=limit,
        reset_timestamp=reset_timestamp,
    )
