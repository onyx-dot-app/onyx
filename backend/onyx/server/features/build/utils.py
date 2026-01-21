"""Utility functions for Build Mode feature announcements and file validation."""

import re
from pathlib import Path

from sqlalchemy.orm import Session

from onyx.auth.schemas import UserRole
from onyx.configs.constants import NotificationType
from onyx.db.models import User
from onyx.db.notification import create_notification
from onyx.feature_flags.factory import get_default_feature_flag_provider
from onyx.feature_flags.interface import NoOpFeatureFlagProvider
from onyx.file_processing.file_types import OnyxFileExtensions
from onyx.file_processing.file_types import OnyxMimeTypes
from onyx.server.features.build.configs import MAX_UPLOAD_FILE_SIZE_BYTES
from onyx.utils.logger import setup_logger

logger = setup_logger()

# =============================================================================
# File Upload Validation
# =============================================================================

# Additional extensions for code files (safe to read, not execute)
CODE_FILE_EXTENSIONS: set[str] = {
    ".py",
    ".js",
    ".ts",
    ".tsx",
    ".jsx",
    ".css",
    ".scss",
    ".less",
    ".java",
    ".go",
    ".rs",
    ".cpp",
    ".c",
    ".h",
    ".hpp",
    ".cs",
    ".rb",
    ".php",
    ".swift",
    ".kt",
    ".scala",
    ".sh",
    ".bash",
    ".zsh",
    ".env",
    ".ini",
    ".toml",
    ".cfg",
    ".properties",
}

# Additional MIME types for code files
CODE_MIME_TYPES: set[str] = {
    "text/x-python",
    "text/x-java",
    "text/x-c",
    "text/x-c++",
    "text/x-go",
    "text/x-rust",
    "text/x-shellscript",
    "text/css",
    "text/javascript",
    "application/javascript",
    "application/typescript",
    "application/octet-stream",  # Generic (for code files with unknown type)
}

# Combine base Onyx extensions with code file extensions
ALLOWED_EXTENSIONS: set[str] = (
    OnyxFileExtensions.ALL_ALLOWED_EXTENSIONS | CODE_FILE_EXTENSIONS
)

# Combine base Onyx MIME types with code MIME types
ALLOWED_MIME_TYPES: set[str] = OnyxMimeTypes.ALLOWED_MIME_TYPES | CODE_MIME_TYPES

# Blocked extensions (executable/dangerous files)
BLOCKED_EXTENSIONS: set[str] = {
    # Windows executables
    ".exe",
    ".dll",
    ".msi",
    ".scr",
    ".com",
    ".bat",
    ".cmd",
    ".ps1",
    # macOS
    ".app",
    ".dmg",
    ".pkg",
    # Linux
    ".deb",
    ".rpm",
    ".so",
    # Cross-platform
    ".jar",
    ".war",
    ".ear",
    # Other potentially dangerous
    ".vbs",
    ".vbe",
    ".wsf",
    ".wsh",
    ".hta",
    ".cpl",
    ".reg",
    ".lnk",
    ".pif",
}

# Regex for sanitizing filenames (allow alphanumeric, dash, underscore, period)
SAFE_FILENAME_PATTERN = re.compile(r"[^a-zA-Z0-9._-]")


def validate_file_extension(filename: str) -> tuple[bool, str | None]:
    """Validate file extension against allowlist.

    Args:
        filename: The filename to validate

    Returns:
        Tuple of (is_valid, error_message)
    """
    ext = Path(filename).suffix.lower()

    if not ext:
        return False, "File must have an extension"

    if ext in BLOCKED_EXTENSIONS:
        return False, f"File type '{ext}' is not allowed for security reasons"

    if ext not in ALLOWED_EXTENSIONS:
        return False, f"File type '{ext}' is not supported"

    return True, None


def validate_mime_type(content_type: str | None) -> bool:
    """Validate MIME type against allowlist.

    Args:
        content_type: The Content-Type header value

    Returns:
        True if the MIME type is allowed, False otherwise
    """
    if not content_type:
        # Allow missing content type - we'll validate by extension
        return True

    # Extract base MIME type (ignore charset etc.)
    mime_type = content_type.split(";")[0].strip().lower()

    if mime_type not in ALLOWED_MIME_TYPES:
        return False

    return True


def validate_file_size(size: int) -> bool:
    """Validate file size against limit.

    Args:
        size: File size in bytes

    Returns:
        True if the file size is allowed, False otherwise
    """
    if size <= 0:
        return False

    if size > MAX_UPLOAD_FILE_SIZE_BYTES:
        return False

    return True


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


def validate_file(
    filename: str,
    content_type: str | None,
    size: int,
) -> bool:
    """Validate a file for upload.

    Performs all validation checks:
    - Extension validation
    - MIME type validation
    - Size validation

    Args:
        filename: The filename to validate
        content_type: The Content-Type header value
        size: File size in bytes

    Returns:
        True if the file is valid, False otherwise
    """
    # Validate extension
    is_valid = (
        validate_file_extension(filename)
        and validate_mime_type(content_type)
        and validate_file_size(size)
    )
    return is_valid


# =============================================================================
# Build Mode Feature Announcements
# =============================================================================

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
    # Posthog feature flag check
    if not is_build_mode_intro_enabled(user):
        return

    # Only show to admin users (since only admins can create connectors)
    if user.role != UserRole.ADMIN:
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
