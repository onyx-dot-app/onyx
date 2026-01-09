"""Database functions for release notes functionality."""

from sqlalchemy import select
from sqlalchemy.orm import Session

from onyx.auth.schemas import UserRole
from onyx.configs.constants import NotificationType
from onyx.db.models import User
from onyx.db.notification import batch_create_notifications
from onyx.server.features.release_notes.models import ReleaseNoteEntry
from onyx.utils.logger import setup_logger

logger = setup_logger()


def create_release_notifications_for_versions(
    db_session: Session,
    release_note_entries: list[ReleaseNoteEntry],
) -> int:
    """
    Create release notes notifications for each release note entry.
    Uses batch_create_notifications for efficient bulk insertion.

    If a user already has a notification for a specific version (dismissed or not),
    no new one is created (handled by unique constraint on additional_data).

    Note: Entries should already be filtered by app_version before calling this
    function. The filtering happens in _parse_mdx_to_release_note_entries().

    Args:
        db_session: Database session
        release_note_entries: List of release note entries to notify about (pre-filtered)

    Returns:
        Total number of notifications created across all versions.
    """
    if not release_note_entries:
        logger.debug("No release note entries to notify about")
        return 0

    # Get active users
    # NOTE: This also sends notifications to API key "users"
    # There's no quick way to filter out API keys
    # because the only difference is an email string prefix.
    user_ids = list(
        db_session.scalars(
            select(User.id).where(  # type: ignore[call-overload]
                User.is_active == True,  # noqa: E712
                User.role.in_(
                    [
                        UserRole.BASIC,
                        UserRole.ADMIN,
                        UserRole.CURATOR,
                        UserRole.GLOBAL_CURATOR,
                    ]
                ),
            )
        ).all()
    )

    total_created = 0
    for entry in release_note_entries:
        # Only store version - full content is fetched from /api/release-notes
        additional_data: dict[str, str] = {"version": entry.version}

        created_count = batch_create_notifications(
            user_ids,
            NotificationType.RELEASE_NOTES,
            db_session,
            title=entry.title,
            description=f"Check out what's new in {entry.version}",
            additional_data=additional_data,
        )
        total_created += created_count

        logger.debug(
            f"Created {created_count} release notes notifications "
            f"(version {entry.version}, {len(user_ids)} eligible users)"
        )

    return total_created
