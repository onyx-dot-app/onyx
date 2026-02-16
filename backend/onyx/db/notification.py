from datetime import datetime
from datetime import timezone
from uuid import UUID

from sqlalchemy import cast
from sqlalchemy import select
from sqlalchemy.dialects import postgresql
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session
from sqlalchemy.sql import func

from onyx.auth.schemas import UserRole
from onyx.configs.constants import NotificationType
from onyx.db.models import Notification
from onyx.db.models import User


def create_notification(
    user_id: UUID | None,
    notif_type: NotificationType,
    db_session: Session,
    title: str,
    description: str | None = None,
    additional_data: dict | None = None,
    autocommit: bool = True,
) -> Notification:
    # Previously, we only matched the first identical, undismissed notification
    # Now, we assume some uniqueness to notifications
    # If we previously issued a notification that was dismissed, we no longer issue a new one

    # Normalize additional_data to match the unique index behavior
    # The index uses COALESCE(additional_data, '{}'::jsonb)
    # We need to match this logic in our query
    additional_data_normalized = additional_data if additional_data is not None else {}

    existing_notification = (
        db_session.query(Notification)
        .filter_by(user_id=user_id, notif_type=notif_type)
        .filter(
            func.coalesce(Notification.additional_data, cast({}, postgresql.JSONB))
            == additional_data_normalized
        )
        .first()
    )

    if existing_notification:
        # Update the last_shown timestamp if the notification is not dismissed
        if not existing_notification.dismissed:
            existing_notification.last_shown = func.now()
            if autocommit:
                db_session.commit()
        return existing_notification

    # Create a new notification if none exists
    notification = Notification(
        user_id=user_id,
        notif_type=notif_type,
        title=title,
        description=description,
        dismissed=False,
        last_shown=func.now(),
        first_shown=func.now(),
        additional_data=additional_data,
    )
    db_session.add(notification)
    if autocommit:
        db_session.commit()
    return notification


def get_notification_by_id(
    notification_id: int, user: User, db_session: Session
) -> Notification:
    user_id = user.id
    notif = db_session.get(Notification, notification_id)
    if not notif:
        raise ValueError(f"No notification found with id {notification_id}")
    if notif.user_id != user_id and not (
        notif.user_id is None and user is not None and user.role == UserRole.ADMIN
    ):
        raise PermissionError(
            f"User {user_id} is not authorized to access notification {notification_id}"
        )
    return notif


def get_notifications(
    user: User | None,
    db_session: Session,
    notif_type: NotificationType | None = None,
    include_dismissed: bool = True,
) -> list[Notification]:
    query = select(Notification).where(
        Notification.user_id == user.id if user else Notification.user_id.is_(None)
    )
    if not include_dismissed:
        query = query.where(Notification.dismissed.is_(False))
    if notif_type:
        query = query.where(Notification.notif_type == notif_type)
    # Sort: undismissed first, then by date (newest first)
    query = query.order_by(
        Notification.dismissed.asc(),
        Notification.first_shown.desc(),
    )
    return list(db_session.execute(query).scalars().all())


def dismiss_all_notifications(
    notif_type: NotificationType,
    db_session: Session,
) -> None:
    db_session.query(Notification).filter(Notification.notif_type == notif_type).update(
        {"dismissed": True}
    )
    db_session.commit()


def dismiss_notification(notification: Notification, db_session: Session) -> None:
    notification.dismissed = True
    db_session.commit()


def batch_dismiss_notifications(
    notifications: list[Notification],
    db_session: Session,
) -> None:
    for notification in notifications:
        notification.dismissed = True
    db_session.commit()


def batch_create_notifications(
    user_ids: list[UUID],
    notif_type: NotificationType,
    db_session: Session,
    title: str,
    description: str | None = None,
    additional_data: dict | None = None,
) -> int:
    """
    Create notifications for multiple users in a single batch operation.
    Uses ON CONFLICT DO NOTHING for atomic idempotent inserts - if a user already
    has a notification with the same (user_id, notif_type, additional_data), the
    insert is silently skipped.

    Returns the number of notifications created.

    Relies on unique index on (user_id, notif_type, COALESCE(additional_data, '{}'))
    """
    if not user_ids:
        return 0

    now = datetime.now(timezone.utc)
    # Use empty dict instead of None to match COALESCE behavior in the unique index
    additional_data_normalized = additional_data if additional_data is not None else {}

    values = [
        {
            "user_id": uid,
            "notif_type": notif_type.value,
            "title": title,
            "description": description,
            "dismissed": False,
            "last_shown": now,
            "first_shown": now,
            "additional_data": additional_data_normalized,
        }
        for uid in user_ids
    ]

    stmt = insert(Notification).values(values).on_conflict_do_nothing()
    result = db_session.execute(stmt)
    db_session.commit()

    # rowcount returns number of rows inserted (excludes conflicts)
    # CursorResult has rowcount but session.execute type hints are too broad
    return result.rowcount if result.rowcount >= 0 else 0  # type: ignore[attr-defined]


def update_notification_last_shown(
    notification: Notification, db_session: Session
) -> None:
    notification.last_shown = func.now()
    db_session.commit()
