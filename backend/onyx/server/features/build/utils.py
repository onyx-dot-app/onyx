"""Utility functions for Build Mode feature announcements and file validation."""

import re
from pathlib import Path

from sqlalchemy.orm import Session

from onyx.configs.constants import NotificationType
from onyx.db.enums import AccountType
from onyx.db.models import User
from onyx.db.notification import create_notification
from onyx.feature_flags.factory import get_default_feature_flag_provider
from onyx.feature_flags.interface import NoOpFeatureFlagProvider
from onyx.server.features.build.configs import ENABLE_CRAFT, MAX_UPLOAD_FILE_SIZE_BYTES
from onyx.server.settings.store import load_settings
from onyx.utils.logger import setup_logger
from shared_configs.contextvars import get_current_tenant_id

logger = setup_logger()

# =============================================================================
# File Upload Validation
# =============================================================================
#
# Craft does NOT restrict uploads by file extension or MIME type. Uploaded
# files only ever execute inside the isolated per-user sandbox (locked-down
# pod: non-root, dropped caps, egress-gated), which is the real security
# boundary, and downloads are served as attachments. Only size is enforced.

# Regex for sanitizing filenames (allow alphanumeric, dash, underscore, period)
SAFE_FILENAME_PATTERN = re.compile(r"[^a-zA-Z0-9._-]")


def sanitize_filename(filename: str) -> str:
    """Sanitize filename to prevent path traversal and other issues.

    Args:
        filename: The original filename

    Returns:
        Sanitized filename safe for filesystem use
    """
    # Remove any path components (prevent path traversal)
    filename = Path(filename).name

    # Remove null bytes
    filename = filename.replace("\x00", "")

    # Replace unsafe characters with underscore
    filename = SAFE_FILENAME_PATTERN.sub("_", filename)

    # Remove leading/trailing dots and spaces
    filename = filename.strip(". ")

    # Ensure filename is not empty
    if not filename:
        filename = "unnamed_file"

    # Ensure filename doesn't start with a dot (hidden file)
    if filename.startswith("."):
        filename = "_" + filename[1:]

    # Limit length (preserve extension)
    max_length = 255
    if len(filename) > max_length:
        stem = Path(filename).stem
        ext = Path(filename).suffix
        max_stem_length = max_length - len(ext)
        filename = stem[:max_stem_length] + ext

    return filename


def validate_file(size: int) -> tuple[bool, str | None]:
    """Validate a file for upload.

    Only size is enforced; extension and MIME type are intentionally not
    restricted (see the File Upload Validation note above).

    Args:
        size: File size in bytes

    Returns:
        Tuple of (is_valid, error_message). error_message is None if valid.
    """
    if size <= 0:
        return False, "File is empty"

    if size > MAX_UPLOAD_FILE_SIZE_BYTES:
        return (
            False,
            f"File size exceeds maximum allowed size of {MAX_UPLOAD_FILE_SIZE_BYTES} bytes",
        )

    return True, None


# =============================================================================
# Build Mode Feature Announcements
# =============================================================================

# PostHog feature flag key for enabling Onyx Craft (cloud rollout control)
# Flag logic: True = enabled, False/null/not found = disabled
ONYX_CRAFT_ENABLED_FLAG = "onyx-craft-enabled"

# PostHog feature flag key for controlling whether a user has usage limits
# Flag logic: True = user has usage limits (rate limits apply), False/null/not found = no limits (unlimited usage)
CRAFT_HAS_USAGE_LIMITS = "craft-has-usage-limits"

# Feature identifier in additional_data
BUILD_MODE_FEATURE_ID = "build_mode"


def is_craft_available_for_deployment(user: User) -> bool:
    """
    Check whether Onyx Craft (Build Mode) is available at the deployment level.

    Flag logic for "onyx-craft-enabled":
    - Flag = True → enabled (Onyx Craft is available)
    - Flag = False → disabled (Onyx Craft is not available)
    - Flag = null/not found → disabled (Onyx Craft is not available)

    Only explicit True enables the feature.

    On the PostHog path the flag is evaluated for the requesting user, so
    "deployment-level" assumes tenant-scoped flag targeting; per-user cohort
    rollouts would make this reflect the requester's own bucket.
    """
    feature_flag_provider = get_default_feature_flag_provider()

    # If no PostHog configured (NoOp provider), use ENABLE_CRAFT env var
    if isinstance(feature_flag_provider, NoOpFeatureFlagProvider):
        return ENABLE_CRAFT

    is_enabled = feature_flag_provider.feature_enabled_for_user_tenant(
        ONYX_CRAFT_ENABLED_FLAG,
        user,
        get_current_tenant_id(),
    )

    if is_enabled:
        logger.debug("Onyx Craft enabled via PostHog feature flag")
        return True
    else:
        logger.debug("Onyx Craft disabled via PostHog feature flag")
        return False


def is_craft_enabled_for_user(
    user: User,
    deployment_available: bool | None = None,
    workspace_default: bool | None = None,
) -> bool:
    """
    Check if Onyx Craft (Build Mode) is enabled for the user: the deployment
    must have Craft available AND the workspace policy must grant it — the
    per-user override (User.craft_enabled) when set, else the workspace
    default (Settings.craft_default_enabled).

    Pass ``deployment_available`` / ``workspace_default`` when already
    evaluated, to avoid redundant flag-provider / KV-store reads.
    """
    # Craft is identity-bound (per-user sandbox, library, scheduled tasks);
    # all anonymous visitors share one identity, so they never get it.
    if user.account_type == AccountType.ANONYMOUS:
        return False

    override = user.craft_enabled
    if override is False:
        return False
    if override is None:
        if workspace_default is None:
            workspace_default = load_settings().craft_default_enabled
        if not workspace_default:
            return False

    if deployment_available is None:
        deployment_available = is_craft_available_for_deployment(user)
    return deployment_available


def ensure_build_mode_intro_notification(user: User, db_session: Session) -> None:
    """
    Create Build Mode intro notification for user if enabled and not already exists.

    Called from /api/notifications endpoint. Uses notification deduplication
    to ensure each user only gets one notification.
    """
    # PostHog feature flag check - only show notification if Onyx Craft is enabled
    if not is_craft_enabled_for_user(user):
        return

    # Create notification (will be skipped if already exists due to deduplication)
    create_notification(
        user_id=user.id,
        notif_type=NotificationType.FEATURE_ANNOUNCEMENT,
        db_session=db_session,
        title="Introducing Onyx Craft",
        description="Unleash Onyx to create dashboards, slides, documents, and more with your connected data.",
        additional_data={"feature": BUILD_MODE_FEATURE_ID},
        refresh_existing=False,
    )
