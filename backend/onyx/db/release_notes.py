"""Database functions for release notes functionality."""

from urllib.parse import urlencode

from sqlalchemy import select
from sqlalchemy.orm import Session

from onyx.auth.schemas import UserRole
from onyx.configs.app_configs import INSTANCE_TYPE
from onyx.configs.constants import DANSWER_API_KEY_DUMMY_EMAIL_DOMAIN
from onyx.configs.constants import NotificationType
from onyx.configs.constants import ONYX_UTM_SOURCE
from onyx.db.models import User
from onyx.db.notification import batch_create_notifications
from onyx.server.features.release_notes.constants import DOCS_CHANGELOG_BASE_URL
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

    # Get active users and exclude API key users
    user_ids = list(
        db_session.scalars(
            select(User.id).where(  # type: ignore
                User.is_active == True,  # noqa: E712
                User.role.notin_([UserRole.SLACK_USER, UserRole.EXT_PERM_USER]),
                User.email.endswith(DANSWER_API_KEY_DUMMY_EMAIL_DOMAIN).is_(False),  # type: ignore[attr-defined]
            )
        ).all()
    )

    total_created = 0
    for entry in release_note_entries:
        # Convert version to anchor format for external docs links
        # v2.7.0 -> v2-7-0
        version_anchor = entry.version.replace(".", "-")

        # Build UTM parameters for tracking
        utm_params = {
            "utm_source": ONYX_UTM_SOURCE,
            "utm_medium": "notification",
            "utm_campaign": INSTANCE_TYPE,
            "utm_content": f"release_notes-{entry.version}",
        }

        link = f"{DOCS_CHANGELOG_BASE_URL}#{version_anchor}?{urlencode(utm_params)}"

        additional_data: dict[str, str] = {
            "version": entry.version,
            "link": link,
        }

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
