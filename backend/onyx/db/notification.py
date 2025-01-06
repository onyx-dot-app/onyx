from uuid import UUID

from sqlalchemy import select
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
    additional_data: dict | None = None,
) -> Notification:
    # Check if an undismissed notification of the same type and data exists
    existing_notification = (
        db_session.query(Notification)
        .filter_by(
            user_id=user_id,
            notif_type=notif_type,
            dismissed=False,
        )
        .filter(Notification.additional_data == additional_data)
        .first()
    )

    if existing_notification:
        # Update the last_shown timestamp
        existing_notification.last_shown = func.now()
        db_session.commit()
        return existing_notification

    # Create a new notification if none exists
    notification = Notification(
        user_id=user_id,
        notif_type=notif_type,
        dismissed=False,
        last_shown=func.now(),
        first_shown=func.now(),
        additional_data=additional_data,
    )
    db_session.add(notification)
    db_session.commit()
    return notification


def get_notification_by_id(
    notification_id: int, user: User | None, db_session: Session
) -> Notification:
    user_id = user.id if user else None
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


def update_notification_last_shown(
    notification: Notification, db_session: Session
) -> None:
    notification.last_shown = func.now()
    db_session.commit()
