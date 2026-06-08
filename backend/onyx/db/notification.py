from datetime import datetime
from datetime import timezone
from typing import Any
from typing import cast as type_cast
from uuid import UUID

from sqlalchemy import cast
from sqlalchemy import select
from sqlalchemy import update
from sqlalchemy.dialects import postgresql
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.engine import CursorResult
from sqlalchemy.orm import Session
from sqlalchemy.sql import func
from sqlalchemy.sql.elements import ColumnElement

from onyx.auth.schemas import UserRole
from onyx.configs.constants import NotificationType
from onyx.db.models import Notification
from onyx.db.models import User


def _notification_filters(
    user: User | None,
    notif_type: NotificationType | None = None,
    include_dismissed: bool = True,
) -> list[ColumnElement[bool]]:
    filters = [
        Notification.user_id == user.id if user else Notification.user_id.is_(None)
    ]
    if not include_dismissed:
        filters.append(Notification.dismissed.is_(False))
    if notif_type:
        filters.append(Notification.notif_type == notif_type)
    return filters


def create_notification(
    user_id: UUID | None,
    notif_type: NotificationType,
    db_session: Session,
    title: str,
    description: str | None = None,
    additional_data: dict[str, Any] | None = None,
) -> Notification:
    """Create a notification if this user/type/data identity does not exist.

    The identity matches ix_notification_user_type_data: user, type, and
    additional_data with NULL treated as '{}'. Existing rows are returned
    without mutation.
    """
    additional_data_normalized = additional_data if additional_data is not None else {}
    user_filter = (
        Notification.user_id == user_id
        if user_id is not None
        else Notification.user_id.is_(None)
    )

    existing_notification = db_session.execute(
        select(Notification)
        .where(
            user_filter,
            Notification.notif_type == notif_type,
            func.coalesce(Notification.additional_data, cast({}, postgresql.JSONB))
            == additional_data_normalized,
        )
        .limit(1)
    ).scalar_one_or_none()

    if existing_notification is not None:
        return existing_notification

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
    return notification


def create_or_resurface_notification(
    user_id: UUID | None,
    notif_type: NotificationType,
    db_session: Session,
    title: str,
    description: str | None = None,
    additional_data: dict[str, Any] | None = None,
    identity_data: dict[str, Any] | None = None,
) -> Notification:
    """Create a notification or make an existing matching notification visible again.

    `identity_data` is the stable lookup identity for a notification whose
    display payload can change between events.
    """
    if identity_data is not None and (not identity_data or additional_data is None):
        raise ValueError("identity_data requires non-empty additional_data")

    if identity_data is None:
        notification = create_notification(
            user_id=user_id,
            notif_type=notif_type,
            db_session=db_session,
            title=title,
            description=description,
            additional_data=additional_data,
        )
    else:
        user_filter = (
            Notification.user_id == user_id
            if user_id is not None
            else Notification.user_id.is_(None)
        )

        matching_notifications = db_session.scalars(
            select(Notification)
            .where(
                user_filter,
                Notification.notif_type == notif_type,
                Notification.additional_data.contains(identity_data),
            )
            .order_by(Notification.first_shown.desc(), Notification.id.desc())
        ).all()

        if matching_notifications:
            notification = next(
                (
                    matching_notification
                    for matching_notification in matching_notifications
                    if (matching_notification.additional_data or {})
                    == (additional_data or {})
                ),
                matching_notifications[0],
            )
            for duplicate_notification in matching_notifications:
                if duplicate_notification.id != notification.id:
                    db_session.delete(duplicate_notification)
            if len(matching_notifications) > 1:
                db_session.flush()
        else:
            notification = create_notification(
                user_id=user_id,
                notif_type=notif_type,
                db_session=db_session,
                title=title,
                description=description,
                additional_data=additional_data,
            )

    was_dismissed = notification.dismissed
    notification.title = title
    notification.description = description
    notification.additional_data = additional_data
    notification.dismissed = False
    shown_at = func.now()
    if was_dismissed:
        notification.first_shown = shown_at
    notification.last_shown = shown_at
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
    limit: int | None = None,
    offset: int = 0,
) -> list[Notification]:
    query = select(Notification).where(
        *_notification_filters(
            user=user,
            notif_type=notif_type,
            include_dismissed=include_dismissed,
        )
    )
    # Sort: undismissed first, then by date (newest first)
    query = query.order_by(
        Notification.dismissed.asc(),
        Notification.first_shown.desc(),
        Notification.id.desc(),
    )
    if limit is not None:
        query = query.limit(limit).offset(offset)
    return list(db_session.execute(query).scalars().all())


def count_notifications(
    user: User | None,
    db_session: Session,
    notif_type: NotificationType | None = None,
) -> tuple[int, int]:
    query = select(
        func.count(Notification.id),
        func.count(Notification.id).filter(Notification.dismissed.is_(False)),
    ).where(
        *_notification_filters(
            user=user,
            notif_type=notif_type,
        )
    )
    total_items, undismissed_count = db_session.execute(query).one()
    return total_items or 0, undismissed_count or 0


def dismiss_all_notifications(
    notif_type: NotificationType,
    db_session: Session,
) -> None:
    stmt = (
        update(Notification)
        .where(Notification.notif_type == notif_type)
        .values(dismissed=True)
        .execution_options(synchronize_session=False)
    )
    db_session.execute(stmt)
    db_session.commit()


def dismiss_user_notifications(
    user: User,
    db_session: Session,
    notif_type: NotificationType | None = None,
) -> None:
    stmt = (
        update(Notification)
        .where(
            *_notification_filters(
                user=user,
                notif_type=notif_type,
                include_dismissed=False,
            )
        )
        .values(dismissed=True)
        .execution_options(synchronize_session=False)
    )
    db_session.execute(stmt)
    db_session.commit()


def dismiss_notification(
    notification_id: int,
    db_session: Session,
    expected_version: datetime | None = None,
) -> bool:
    stmt = update(Notification).where(Notification.id == notification_id)
    if expected_version is not None:
        stmt = stmt.where(Notification.last_shown == expected_version)
    result = type_cast(
        CursorResult[Any],
        db_session.execute(
            stmt.values(dismissed=True).execution_options(synchronize_session=False)
        ),
    )
    db_session.commit()
    return result.rowcount > 0


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
    additional_data: dict[str, Any] | None = None,
) -> set[UUID]:
    """
    Create notifications for multiple users in a single batch operation.
    Uses ON CONFLICT DO NOTHING for atomic idempotent inserts - if a user already
    has a notification with the same (user_id, notif_type, additional_data), the
    insert is silently skipped.

    Returns the set of user_ids whose row was newly inserted (excludes conflicts).
    Callers that need to fire side effects only on fresh inserts (emails, webhooks)
    can iterate the returned set without re-triggering on idempotent retries.

    Relies on unique index on (user_id, notif_type, COALESCE(additional_data, '{}'))
    """
    if not user_ids:
        return set()

    now = datetime.now(timezone.utc)
    additional_data_normalized = additional_data if additional_data is not None else {}

    values = [
        {
            "user_id": uid,
            "notif_type": notif_type,
            "title": title,
            "description": description,
            "dismissed": False,
            "last_shown": now,
            "first_shown": now,
            "additional_data": additional_data_normalized,
        }
        for uid in user_ids
    ]

    stmt = (
        insert(Notification)
        .values(values)
        .on_conflict_do_nothing()
        .returning(Notification.user_id)
    )
    result = db_session.execute(stmt)
    inserted_ids = set(result.scalars())
    db_session.commit()
    return inserted_ids  # ty: ignore[invalid-return-type]


def update_notification_last_shown(
    notification: Notification, db_session: Session
) -> None:
    notification.last_shown = func.now()
    db_session.commit()
