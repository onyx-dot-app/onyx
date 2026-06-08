from collections.abc import Callable
from datetime import datetime
from datetime import timedelta
from datetime import timezone

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from onyx.configs.constants import NotificationType
from onyx.db.models import Notification
from onyx.db.models import User
from onyx.db.notification import count_notifications
from onyx.db.notification import create_notification
from onyx.db.notification import dismiss_user_notifications
from onyx.db.notification import get_notifications
from onyx.server.features.notifications import api as notifications_api
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


def test_notification_pagination_uses_stable_tie_breaker(
    db_session: Session,
    tenant_context: None,  # noqa: ARG001
) -> None:
    user = create_test_user(db_session, "notification_tie_break")
    first_shown = datetime(2026, 1, 1, tzinfo=timezone.utc)
    created_notifications = [
        _create_notification(
            db_session=db_session,
            user=user,
            index=index,
            first_shown=first_shown,
            dismissed=False,
        )
        for index in range(3)
    ]
    db_session.commit()

    page = get_notifications(
        user=user,
        db_session=db_session,
        notif_type=NotificationType.APPROVAL_REQUESTED,
        include_dismissed=True,
        limit=3,
    )

    assert [notification.id for notification in page] == sorted(
        notification.id for notification in created_notifications
    )[::-1]


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


def test_get_notifications_api_returns_paginated_response(
    db_session: Session,
    tenant_context: None,  # noqa: ARG001
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _disable_notification_ensure_checks(monkeypatch)
    user = create_test_user(db_session, "notification_api_page")
    base_time = datetime(2026, 1, 1, tzinfo=timezone.utc)
    for index in range(3):
        _create_notification(
            db_session=db_session,
            user=user,
            index=index,
            first_shown=base_time + timedelta(minutes=index),
            dismissed=index == 0,
        )
    db_session.commit()

    response = notifications_api.get_notifications_api(
        page_num=0,
        page_size=2,
        user=user,
        db_session=db_session,
    )

    assert len(response.notifications) == 2
    assert response.total_items == 3
    assert response.undismissed_count == 2
    assert response.page_num == 0
    assert response.page_size == 2
    assert response.has_more is True


def test_get_notifications_api_runs_ensure_checks_on_first_page(
    db_session: Session,
    tenant_context: None,  # noqa: ARG001
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user = create_test_user(db_session, "notification_api_ensure_checks")
    calls: list[str] = []

    def record_call(name: str) -> Callable[..., None]:
        def _record_call(*_args: object, **_kwargs: object) -> None:
            calls.append(name)

        return _record_call

    monkeypatch.setattr(
        notifications_api,
        "ensure_build_mode_intro_notification",
        record_call("build"),
    )
    monkeypatch.setattr(
        notifications_api,
        "ensure_permissions_migration_notification",
        record_call("permissions"),
    )
    monkeypatch.setattr(
        notifications_api,
        "ensure_release_notes_fresh_and_notify",
        record_call("release_notes"),
    )

    notifications_api.get_notifications_api(
        page_num=0,
        page_size=2,
        user=user,
        db_session=db_session,
    )
    assert calls == ["build", "permissions", "release_notes"]

    calls.clear()
    notifications_api.get_notifications_api(
        page_num=1,
        page_size=2,
        user=user,
        db_session=db_session,
    )
    assert calls == []


def test_notification_summary_runs_ensure_checks_before_counting(
    db_session: Session,
    tenant_context: None,  # noqa: ARG001
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user = create_test_user(db_session, "notification_summary_no_checks")
    calls: list[str] = []

    def record_call(name: str) -> Callable[..., None]:
        def _record_call(*_args: object, **_kwargs: object) -> None:
            calls.append(name)

        return _record_call

    monkeypatch.setattr(
        notifications_api,
        "ensure_build_mode_intro_notification",
        record_call("build"),
    )
    monkeypatch.setattr(
        notifications_api,
        "ensure_permissions_migration_notification",
        record_call("permissions"),
    )
    monkeypatch.setattr(
        notifications_api,
        "ensure_release_notes_fresh_and_notify",
        record_call("release_notes"),
    )

    summary = notifications_api.get_notifications_summary_api(
        user=user,
        db_session=db_session,
    )

    assert summary.total_items == 0
    assert summary.undismissed_count == 0
    assert calls == ["build", "permissions", "release_notes"]


def test_notification_summary_and_dismiss_all_api(
    db_session: Session,
    tenant_context: None,  # noqa: ARG001
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _disable_notification_ensure_checks(monkeypatch)
    user = create_test_user(db_session, "notification_summary")
    other_user = create_test_user(db_session, "notification_summary_other")
    first_shown = datetime(2026, 1, 1, tzinfo=timezone.utc)
    _create_notification(
        db_session=db_session,
        user=user,
        index=1,
        first_shown=first_shown,
        dismissed=False,
    )
    _create_notification(
        db_session=db_session,
        user=user,
        index=2,
        first_shown=first_shown + timedelta(minutes=1),
        dismissed=True,
    )
    other_user_notification = _create_notification(
        db_session=db_session,
        user=other_user,
        index=3,
        first_shown=first_shown + timedelta(minutes=2),
        dismissed=False,
    )
    db_session.commit()

    summary = notifications_api.get_notifications_summary_api(
        user=user,
        db_session=db_session,
    )
    assert summary.total_items == 2
    assert summary.undismissed_count == 1

    notifications_api.dismiss_all_notifications_endpoint(
        user=user,
        db_session=db_session,
    )

    summary = notifications_api.get_notifications_summary_api(
        user=user,
        db_session=db_session,
    )
    assert summary.total_items == 2
    assert summary.undismissed_count == 0
    other_user_row = db_session.scalars(
        select(Notification).where(Notification.id == other_user_notification.id)
    ).one()
    assert other_user_row.dismissed is False


def _disable_notification_ensure_checks(monkeypatch: pytest.MonkeyPatch) -> None:
    def noop_ensure(*_args: object, **_kwargs: object) -> None:
        return None

    monkeypatch.setattr(
        notifications_api,
        "ensure_build_mode_intro_notification",
        noop_ensure,
    )
    monkeypatch.setattr(
        notifications_api,
        "ensure_permissions_migration_notification",
        noop_ensure,
    )
    monkeypatch.setattr(
        notifications_api,
        "ensure_release_notes_fresh_and_notify",
        noop_ensure,
    )
