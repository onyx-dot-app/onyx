from fastapi import APIRouter
from fastapi import Depends
from fastapi import Query
from sqlalchemy.orm import Session

from onyx.auth.permissions import require_permission
from onyx.configs.constants import NotificationType
from onyx.db.engine.sql_engine import get_session
from onyx.db.enums import Permission
from onyx.db.models import User
from onyx.db.notification import count_notifications
from onyx.db.notification import dismiss_notification
from onyx.db.notification import dismiss_user_notifications
from onyx.db.notification import get_notification_by_id
from onyx.db.notification import get_notifications
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.server.features.build.utils import ensure_build_mode_intro_notification
from onyx.server.features.notifications.models import NotificationResponse
from onyx.server.features.notifications.models import NotificationSummary
from onyx.server.features.notifications.models import PaginatedNotifications
from onyx.server.features.notifications.utils import (
    ensure_permissions_migration_notification,
)
from onyx.server.features.release_notes.utils import (
    ensure_release_notes_fresh_and_notify,
)
from onyx.utils.logger import setup_logger

logger = setup_logger()
router = APIRouter(prefix="/notifications")

DEFAULT_NOTIFICATIONS_PAGE_SIZE = 10
MAX_NOTIFICATIONS_PAGE_SIZE = 50


def _ensure_feature_announcement_notifications(
    user: User,
    db_session: Session,
) -> None:
    try:
        ensure_build_mode_intro_notification(user, db_session)
    except Exception:
        logger.exception(
            "Failed to check for build mode intro in notifications endpoint"
        )

    try:
        ensure_permissions_migration_notification(user, db_session)
    except Exception:
        logger.exception(
            "Failed to create permissions_migration_v1 announcement in notifications endpoint"
        )


def _ensure_release_note_notifications(db_session: Session) -> None:
    try:
        ensure_release_notes_fresh_and_notify(db_session)
    except Exception:
        logger.exception("Failed to check for release notes in notifications endpoint")


def _ensure_app_load_notifications(user: User, db_session: Session) -> None:
    _ensure_feature_announcement_notifications(user, db_session)
    _ensure_release_note_notifications(db_session)


@router.get("")
def get_notifications_api(
    page_num: int = Query(0, ge=0),
    page_size: int = Query(
        DEFAULT_NOTIFICATIONS_PAGE_SIZE, ge=1, le=MAX_NOTIFICATIONS_PAGE_SIZE
    ),
    notif_type: NotificationType | None = Query(default=None),
    user: User = Depends(require_permission(Permission.BASIC_ACCESS)),
    db_session: Session = Depends(get_session),
) -> PaginatedNotifications:
    """
    Get a page of notifications for the current user.

    Note: the first page also executes checks that should create notifications.

    Examples of checks that create new notifications:
    - Checking for new release notes the user hasn't seen
    - Checking for misconfigurations due to version changes
    - Explicitly announcing breaking changes
    """
    if page_num == 0:
        if notif_type is None:
            _ensure_app_load_notifications(user, db_session)
        elif notif_type == NotificationType.FEATURE_ANNOUNCEMENT:
            _ensure_feature_announcement_notifications(user, db_session)
        elif notif_type == NotificationType.RELEASE_NOTES:
            _ensure_release_note_notifications(db_session)

    total_items, undismissed_count = count_notifications(
        user=user,
        db_session=db_session,
        notif_type=notif_type,
    )
    offset = page_num * page_size
    notifications = [
        NotificationResponse.model_validate(notif)
        for notif in get_notifications(
            user=user,
            db_session=db_session,
            notif_type=notif_type,
            include_dismissed=True,
            limit=page_size,
            offset=offset,
        )
    ]
    return PaginatedNotifications(
        notifications=notifications,
        total_items=total_items,
        undismissed_count=undismissed_count,
        page_num=page_num,
        page_size=page_size,
        has_more=offset + page_size < total_items,
    )


@router.get("/summary")
def get_notifications_summary_api(
    user: User = Depends(require_permission(Permission.BASIC_ACCESS)),
    db_session: Session = Depends(get_session),
) -> NotificationSummary:
    # Preserve app-load notification bootstrap behavior: notifications that are
    # lazily created on read should exist before we compute badge counts.
    _ensure_app_load_notifications(user, db_session)
    total_items, undismissed_count = count_notifications(
        user=user,
        db_session=db_session,
    )
    return NotificationSummary(
        total_items=total_items,
        undismissed_count=undismissed_count,
    )


@router.post("/dismiss-all")
def dismiss_all_notifications_endpoint(
    user: User = Depends(require_permission(Permission.BASIC_ACCESS)),
    db_session: Session = Depends(get_session),
) -> None:
    dismiss_user_notifications(user=user, db_session=db_session)


@router.post("/{notification_id}/dismiss")
def dismiss_notification_endpoint(
    notification_id: int,
    user: User = Depends(require_permission(Permission.BASIC_ACCESS)),
    db_session: Session = Depends(get_session),
) -> None:
    try:
        notification = get_notification_by_id(notification_id, user, db_session)
    except PermissionError as e:
        raise OnyxError(
            OnyxErrorCode.UNAUTHORIZED,
            "Not authorized to dismiss this notification",
        ) from e
    except ValueError as e:
        raise OnyxError(
            OnyxErrorCode.NOT_FOUND,
            "Notification not found",
        ) from e

    dismiss_notification(notification, db_session)
