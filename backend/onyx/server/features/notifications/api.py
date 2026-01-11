from fastapi import APIRouter
from fastapi import Depends
from fastapi import HTTPException
from sqlalchemy.orm import Session

from onyx.auth.users import current_user
from onyx.db.engine.sql_engine import get_session
from onyx.db.models import User
from onyx.db.notification import dismiss_notification
from onyx.db.notification import get_notification_by_id
from onyx.db.notification import get_notifications
from onyx.server.features.release_notes.utils import (
    ensure_release_notes_fresh_and_notify,
)
from onyx.server.settings.models import Notification as NotificationModel
from onyx.utils.logger import setup_logger

logger = setup_logger()
router = APIRouter(prefix="/notifications")


@router.get("")
def get_notifications_api(
    user: User = Depends(current_user),
    db_session: Session = Depends(get_session),
) -> list[NotificationModel]:
    """
    Get all undismissed notifications for the current user.

    Note: also executes background checks that should create notifications.

    Examples of checks that create new notifications:
    - Checking for new release notes the user hasn't seen
    - Checking for misconfigurations due to version changes
    - Explicitly announcing breaking changes
    """
    # If more background checks are added, this should be moved to a helper function
    try:
        ensure_release_notes_fresh_and_notify(db_session)
    except Exception:
        # Log exception but don't fail the entire endpoint
        # Users can still see their existing notifications
        logger.exception("Failed to check for release notes in notifications endpoint")

    notifications = [
        NotificationModel.from_model(notif)
        for notif in get_notifications(user, db_session, include_dismissed=True)
    ]
    return notifications


@router.post("/{notification_id}/dismiss")
def dismiss_notification_endpoint(
    notification_id: int,
    user: User | None = Depends(current_user),
    db_session: Session = Depends(get_session),
) -> None:
    try:
        notification = get_notification_by_id(notification_id, user, db_session)
    except PermissionError:
        raise HTTPException(
            status_code=403, detail="Not authorized to dismiss this notification"
        )
    except ValueError:
        raise HTTPException(status_code=404, detail="Notification not found")

    dismiss_notification(notification, db_session)
