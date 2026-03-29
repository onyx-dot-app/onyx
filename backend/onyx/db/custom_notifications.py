"""Database operations for custom broadcast notifications."""

from sqlalchemy import select
from sqlalchemy.orm import Session

from onyx.auth.schemas import UserRole
from onyx.configs.constants import DANSWER_API_KEY_DUMMY_EMAIL_DOMAIN
from onyx.configs.constants import NotificationType
from onyx.db.models import User
from onyx.db.notification import batch_create_notifications
from onyx.utils.logger import setup_logger

logger = setup_logger()


def create_broadcast_notifications(
    notif_type: NotificationType,
    db_session: Session,
    title: str,
    description: str | None = None,
    additional_data: dict | None = None,
) -> int:
    """
    Create a notification for all active users.
    Uses batch_create_notifications for deduplication via the unique constraint
    on (user_id, notif_type, additional_data).
    """
    user_ids = list(
        db_session.scalars(
            select(User.id).where(  # type: ignore
                User.is_active == True,  # noqa: E712
                User.role.notin_([UserRole.SLACK_USER, UserRole.EXT_PERM_USER]),
                User.email.endswith(DANSWER_API_KEY_DUMMY_EMAIL_DOMAIN).is_(False),  # type: ignore[attr-defined]
            )
        ).all()
    )

    if not user_ids:
        return 0

    return batch_create_notifications(
        user_ids=user_ids,
        notif_type=notif_type,
        db_session=db_session,
        title=title,
        description=description,
        additional_data=additional_data,
    )
