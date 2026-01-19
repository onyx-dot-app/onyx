"""Utility functions for Build Mode feature announcements."""

from sqlalchemy.orm import Session

from onyx.configs.constants import NotificationType
from onyx.db.models import User
from onyx.db.notification import create_notification
from onyx.feature_flags.factory import get_default_feature_flag_provider
from onyx.feature_flags.interface import NoOpFeatureFlagProvider
from onyx.utils.logger import setup_logger

logger = setup_logger()

# PostHog feature flag key (inverted: True = disabled, so "not found" defaults to enabled)
BUILD_MODE_INTRO_DISABLED_FLAG = "build-mode-intro-disabled"

# Feature identifier in additional_data
BUILD_MODE_FEATURE_ID = "build_mode"


def is_build_mode_intro_enabled(user: User) -> bool:
    """
    Check if Build Mode intro should be shown.

    Uses inverted flag logic: checks if "build-mode-intro-disabled" is True.
    - Flag = True → disabled (don't show)
    - Flag = False or not found → enabled (show)

    This ensures "not found" defaults to enabled since PostHog returns False for missing flags.
    """
    # NOTE: This is where we should invert the logic to globally disable the intro notification

    feature_flag_provider = get_default_feature_flag_provider()

    # If no PostHog configured (NoOp provider), default to enabled
    if isinstance(feature_flag_provider, NoOpFeatureFlagProvider):
        return True

    is_disabled = feature_flag_provider.feature_enabled(
        BUILD_MODE_INTRO_DISABLED_FLAG,
        user.id,
    )

    if is_disabled:
        logger.debug("Build Mode intro disabled via PostHog feature flag")
        return False

    return True


def ensure_build_mode_intro_notification(user: User, db_session: Session) -> None:
    """
    Create Build Mode intro notification for user if enabled and not already exists.

    Called from /api/notifications endpoint. Uses notification deduplication
    to ensure each user only gets one notification.
    """
    if not is_build_mode_intro_enabled(user):
        return

    # Create notification (will be skipped if already exists due to deduplication)
    create_notification(
        user_id=user.id,
        notif_type=NotificationType.FEATURE_ANNOUNCEMENT,
        db_session=db_session,
        title="Introducing Onyx Build Mode",
        description="Unleash AI agents to create slides, dashboards, documents, and more.",
        additional_data={"feature": BUILD_MODE_FEATURE_ID},
    )
