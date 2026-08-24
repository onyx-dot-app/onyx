from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import JSON, cast, select, update
from sqlalchemy.dialects import postgresql
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session
from sqlalchemy.sql import func
from sqlalchemy.sql.elements import ColumnElement

from onyx.auth.permissions import has_global_permission
from onyx.configs.constants import NotificationType
from onyx.db.enums import NotificationSeverity, Permission
from onyx.db.models import Notification, User


def _notification_additional_data_key() -> ColumnElement[dict]:
    """Normalize legacy JSON null and SQL NULL values to the empty-object key."""
    return func.coalesce(
        func.nullif(
            Notification.additional_data,
            cast(JSON.NULL, postgresql.JSONB),
        ),
        cast({}, postgresql.JSONB),
    )


def _notification_filters(
    user: User | None,
    notif_type: NotificationType | None = None,
    include_dismissed: bool = True,
    min_severity: NotificationSeverity | None = None,
) -> list[ColumnElement[bool]]:
    filters = [
        Notification.user_id == user.id if user else Notification.user_id.is_(None)
    ]
    if not include_dismissed:
        filters.append(Notification.dismissed.is_(False))
    if notif_type:
        filters.append(Notification.notif_type == notif_type)
    if min_severity is not None:
        ordered = list(NotificationSeverity)
        filters.append(
            Notification.severity.in_(ordered[ordered.index(min_severity) :])
        )
    return filters


def create_notification(
    user_id: UUID | None,
    notif_type: NotificationType,
    db_session: Session,
    title: str,
    description: str | None = None,
    additional_data: dict | None = None,
    autocommit: bool = True,
    refresh_existing: bool = True,
    severity: NotificationSeverity = NotificationSeverity.INFO,
) -> Notification:
    """Create or return a notification without racing concurrent user inserts."""

    additional_data_normalized = additional_data if additional_data is not None else {}

    existing_notification_query = (
        db_session.query(Notification)
        .filter_by(user_id=user_id, notif_type=notif_type)
        .filter(_notification_additional_data_key() == additional_data_normalized)
    )

    def return_existing(notification: Notification) -> Notification:
        # Read-triggered ensure callers opt out so repeated GETs do not change
        # last_shown and produce different responses.
        if refresh_existing and not notification.dismissed:
            notification.last_shown = func.now()
            if autocommit:
                db_session.commit()
        return notification

    # Avoid an insert attempt (and sequence consumption) on the common
    # idempotent path. The conflict-safe insert below still arbitrates races.
    existing_notification = existing_notification_query.first()
    if existing_notification is not None:
        return return_existing(existing_notification)

    stmt = (
        insert(Notification)
        .values(
            user_id=user_id,
            notif_type=notif_type,
            severity=severity,
            title=title,
            description=description,
            dismissed=False,
            last_shown=func.now(),
            first_shown=func.now(),
            additional_data=additional_data_normalized,
        )
        .on_conflict_do_nothing()
        .returning(Notification)
    )
    notification = db_session.scalars(stmt).one_or_none()

    if notification is None:
        existing_notification = existing_notification_query.first()
        if existing_notification is None:
            raise RuntimeError("Notification insert conflicted but no row was found")
        return return_existing(existing_notification)

    if autocommit:
        db_session.commit()
    return notification


def delete_notifications_by_additional_data(
    notif_type: NotificationType,
    db_session: Session,
    additional_data: dict | None = None,
) -> None:
    """Delete every notification of this type whose additional_data matches,
    regardless of user. Matches the COALESCE(additional_data, '{}') equality
    used at creation, so it clears exactly the rows create_notification /
    batch_create_notifications would have written for the same key."""
    additional_data_normalized = additional_data if additional_data is not None else {}
    db_session.query(Notification).filter(
        Notification.notif_type == notif_type,
        _notification_additional_data_key() == additional_data_normalized,
    ).delete(synchronize_session=False)


def delete_notifications_by_type(
    notif_type: NotificationType,
    db_session: Session,
) -> None:
    """Hard-delete every notification of this type for all users, so an
    admin-authored source that changed out-of-band re-materializes fresh on
    the next read."""
    db_session.query(Notification).filter(Notification.notif_type == notif_type).delete(
        synchronize_session=False
    )
    db_session.commit()


def get_notification_by_id(
    notification_id: int, user: User, db_session: Session
) -> Notification:
    user_id = user.id
    notif = db_session.get(Notification, notification_id)
    if not notif:
        raise ValueError(f"No notification found with id {notification_id}")
    if notif.user_id != user_id and not (
        notif.user_id is None
        and user is not None
        and has_global_permission(user, Permission.FULL_ADMIN_PANEL_ACCESS)
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
    min_severity: NotificationSeverity | None = None,
) -> list[Notification]:
    query = select(Notification).where(
        *_notification_filters(
            user=user,
            notif_type=notif_type,
            include_dismissed=include_dismissed,
            min_severity=min_severity,
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
    min_severity: NotificationSeverity | None = None,
) -> tuple[int, int]:
    query = select(
        func.count(Notification.id),
        func.count(Notification.id).filter(Notification.dismissed.is_(False)),
    ).where(
        *_notification_filters(
            user=user,
            notif_type=notif_type,
            min_severity=min_severity,
        )
    )
    total_items, undismissed_count = db_session.execute(query).one()
    return total_items or 0, undismissed_count or 0


def dismiss_all_notifications(
    notif_type: NotificationType,
    db_session: Session,
) -> None:
    db_session.query(Notification).filter(Notification.notif_type == notif_type).update(
        {"dismissed": True}
    )
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
    severity: NotificationSeverity = NotificationSeverity.INFO,
) -> set[UUID]:
    """
    Create notifications for multiple users in a single batch operation.
    Uses ON CONFLICT DO NOTHING for atomic idempotent inserts - if a user already
    has a notification with the same (user_id, notif_type, additional_data), the
    insert is silently skipped.

    Returns the set of user_ids whose row was newly inserted (excludes conflicts).
    Callers that need to fire side effects only on fresh inserts (emails, webhooks)
    can iterate the returned set without re-triggering on idempotent retries.

    Severity is set only on fresh inserts: a conflicting row keeps its original
    severity. Producers that need an escalation to re-alert must vary
    additional_data (as the license flow does with its stage field).

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
            "severity": severity,
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
