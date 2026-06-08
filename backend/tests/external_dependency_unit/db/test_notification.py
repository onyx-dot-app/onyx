from datetime import datetime
from datetime import timedelta
from datetime import timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from onyx.configs.constants import NotificationType
from onyx.db.models import Notification
from onyx.db.models import User
from onyx.db.notification import count_notifications
from onyx.db.notification import create_notification
from onyx.db.notification import dismiss_user_notifications
from onyx.db.notification import get_notifications
from tests.external_dependency_unit.conftest import create_test_user


def _create_notification(
    db_session: Session,
    user: User,
    index: int,
    first_shown: datetime,
    dismissed: bool,
) -> Notification:
    notification = Notification(
        user_id=user.id,
        notif_type=NotificationType.APPROVAL_REQUESTED,
        dismissed=dismissed,
        last_shown=first_shown,
        first_shown=first_shown,
        title=f"Approval {index}",
        additional_data={"test_position": index},
    )
    db_session.add(notification)
    return notification


def test_notification_pagination_counts_and_bulk_dismissal(
    db_session: Session,
    tenant_context: None,  # noqa: ARG001
) -> None:
    user = create_test_user(db_session, "notification_page")
    other_user = create_test_user(db_session, "notification_page_other")
    base_time = datetime(2026, 1, 1, tzinfo=timezone.utc)

    created_notifications = [
        _create_notification(
            db_session=db_session,
            user=user,
            index=index,
            first_shown=base_time + timedelta(minutes=index),
            dismissed=index in {1, 3},
        )
        for index in range(5)
    ]
    other_user_notification = _create_notification(
        db_session=db_session,
        user=other_user,
        index=99,
        first_shown=base_time + timedelta(minutes=99),
        dismissed=False,
    )
    db_session.commit()

    page = get_notifications(
        user=user,
        db_session=db_session,
        notif_type=NotificationType.APPROVAL_REQUESTED,
        include_dismissed=True,
        limit=2,
        offset=2,
    )

    assert [notification.id for notification in page] == [
        created_notifications[0].id,
        created_notifications[3].id,
    ]
    total_items, undismissed_count = count_notifications(
        user=user,
        db_session=db_session,
        notif_type=NotificationType.APPROVAL_REQUESTED,
    )
    assert total_items == 5
    assert undismissed_count == 3

    dismiss_user_notifications(user=user, db_session=db_session)
    total_items, undismissed_count = count_notifications(
        user=user,
        db_session=db_session,
        notif_type=NotificationType.APPROVAL_REQUESTED,
    )
    assert total_items == 5
    assert undismissed_count == 0

    other_user_row = db_session.scalars(
        select(Notification).where(Notification.id == other_user_notification.id)
    ).one()
    assert other_user_row.dismissed is False


def test_create_notification_can_preserve_existing_last_shown(
    db_session: Session,
    tenant_context: None,  # noqa: ARG001
) -> None:
    user = create_test_user(db_session, "notification_touch")
    original_last_shown = datetime(2026, 1, 1, tzinfo=timezone.utc)
    notification = _create_notification(
        db_session=db_session,
        user=user,
        index=1,
        first_shown=original_last_shown,
        dismissed=False,
    )
    notification.last_shown = original_last_shown
    db_session.commit()

    existing_notification = create_notification(
        user_id=user.id,
        notif_type=NotificationType.APPROVAL_REQUESTED,
        db_session=db_session,
        title="Approval 1",
        additional_data={"test_position": 1},
        refresh_existing=False,
    )

    assert existing_notification.id == notification.id
    assert existing_notification.last_shown == original_last_shown
