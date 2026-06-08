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
from onyx.db.notification import create_or_resurface_notification
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


def test_create_notification_does_not_mutate_existing_notification(
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
    )
    db_session.commit()

    assert existing_notification.id == notification.id
    assert existing_notification.last_shown == original_last_shown


def test_create_notification_does_not_reopen_dismissed_existing(
    db_session: Session,
    tenant_context: None,  # noqa: ARG001
) -> None:
    user = create_test_user(db_session, "notification_dismissed_dedupe")
    original_first_shown = datetime(2026, 1, 1, tzinfo=timezone.utc)
    notification = Notification(
        user_id=user.id,
        notif_type=NotificationType.APPROVAL_REQUESTED,
        dismissed=True,
        last_shown=original_first_shown,
        first_shown=original_first_shown,
        title="Old approval",
        additional_data={
            "session_id": "session-1",
            "link": "/craft/v1?sessionId=session-1",
        },
    )
    db_session.add(notification)
    db_session.commit()

    existing_notification = create_notification(
        user_id=user.id,
        notif_type=NotificationType.APPROVAL_REQUESTED,
        db_session=db_session,
        title="New approval",
        description="New approval details",
        additional_data={
            "session_id": "session-1",
            "link": "/craft/v1?sessionId=session-1",
        },
    )
    db_session.commit()
    db_session.refresh(existing_notification)

    assert existing_notification.id == notification.id
    assert existing_notification.dismissed is True
    assert existing_notification.title == "Old approval"
    assert existing_notification.description is None
    assert existing_notification.first_shown == original_first_shown


def test_create_or_resurface_notification_reopens_existing_session(
    db_session: Session,
    tenant_context: None,  # noqa: ARG001
) -> None:
    user = create_test_user(db_session, "notification_reopen_session")
    original_first_shown = datetime(2026, 1, 1, tzinfo=timezone.utc)
    notification = Notification(
        user_id=user.id,
        notif_type=NotificationType.APPROVAL_REQUESTED,
        dismissed=True,
        last_shown=original_first_shown,
        first_shown=original_first_shown,
        title="Old approval",
        additional_data={
            "session_id": "11111111-1111-1111-1111-111111111111",
            "link": "/craft/v1?sessionId=old-link-format",
        },
    )
    db_session.add(notification)
    db_session.commit()

    reopened_notification = create_or_resurface_notification(
        user_id=user.id,
        notif_type=NotificationType.APPROVAL_REQUESTED,
        db_session=db_session,
        title="New approval",
        description="New approval details",
        additional_data={
            "session_id": "11111111-1111-1111-1111-111111111111",
            "link": "/craft/v1?sessionId=11111111-1111-1111-1111-111111111111",
        },
        dedupe_by_additional_data={
            "session_id": "11111111-1111-1111-1111-111111111111"
        },
    )
    db_session.commit()
    db_session.refresh(reopened_notification)

    assert reopened_notification.id == notification.id
    assert reopened_notification.dismissed is False
    assert reopened_notification.title == "New approval"
    assert reopened_notification.description == "New approval details"
    assert reopened_notification.additional_data is not None
    assert reopened_notification.additional_data == {
        "session_id": "11111111-1111-1111-1111-111111111111",
        "link": "/craft/v1?sessionId=11111111-1111-1111-1111-111111111111",
    }
    assert reopened_notification.first_shown != original_first_shown

    new_session_notification = create_notification(
        user_id=user.id,
        notif_type=NotificationType.APPROVAL_REQUESTED,
        db_session=db_session,
        title="Different session approval",
        additional_data={
            "session_id": "session-2",
            "link": "/craft/v1?sessionId=session-2",
        },
    )
    db_session.commit()
    db_session.refresh(new_session_notification)

    assert new_session_notification.id != reopened_notification.id
    total_items, undismissed_count = count_notifications(
        user=user,
        db_session=db_session,
        notif_type=NotificationType.APPROVAL_REQUESTED,
    )
    assert total_items == 2
    assert undismissed_count == 2


def test_create_or_resurface_notification_updates_active_existing_without_restarting_age(
    db_session: Session,
    tenant_context: None,  # noqa: ARG001
) -> None:
    user = create_test_user(db_session, "notification_resurface_active")
    original_shown = datetime(2026, 1, 1, tzinfo=timezone.utc)
    notification = Notification(
        user_id=user.id,
        notif_type=NotificationType.APPROVAL_REQUESTED,
        dismissed=False,
        last_shown=original_shown,
        first_shown=original_shown,
        title="Old approval",
        additional_data={
            "session_id": "22222222-2222-2222-2222-222222222222",
            "link": "/craft/v1?sessionId=old-link-format",
        },
    )
    db_session.add(notification)
    db_session.commit()

    resurfaced_notification = create_or_resurface_notification(
        user_id=user.id,
        notif_type=NotificationType.APPROVAL_REQUESTED,
        db_session=db_session,
        title="Latest approval",
        description="Latest approval details",
        additional_data={
            "session_id": "22222222-2222-2222-2222-222222222222",
            "link": "/craft/v1?sessionId=22222222-2222-2222-2222-222222222222",
        },
        dedupe_by_additional_data={
            "session_id": "22222222-2222-2222-2222-222222222222"
        },
    )
    db_session.commit()
    db_session.refresh(resurfaced_notification)

    assert resurfaced_notification.id == notification.id
    assert resurfaced_notification.dismissed is False
    assert resurfaced_notification.title == "Latest approval"
    assert resurfaced_notification.description == "Latest approval details"
    assert resurfaced_notification.additional_data == {
        "session_id": "22222222-2222-2222-2222-222222222222",
        "link": "/craft/v1?sessionId=22222222-2222-2222-2222-222222222222",
    }
    assert resurfaced_notification.first_shown == original_shown
    assert resurfaced_notification.last_shown != original_shown


def test_create_or_resurface_notification_is_not_approval_specific(
    db_session: Session,
    tenant_context: None,  # noqa: ARG001
) -> None:
    user = create_test_user(db_session, "notification_generic_resurface")
    original_shown = datetime(2026, 1, 1, tzinfo=timezone.utc)
    notification = Notification(
        user_id=user.id,
        notif_type=NotificationType.FEATURE_ANNOUNCEMENT,
        dismissed=True,
        last_shown=original_shown,
        first_shown=original_shown,
        title="Old announcement",
        additional_data={
            "feature": "stable-feature",
            "link": "/old-link",
        },
    )
    db_session.add(notification)
    db_session.commit()

    resurfaced_notification = create_or_resurface_notification(
        user_id=user.id,
        notif_type=NotificationType.FEATURE_ANNOUNCEMENT,
        db_session=db_session,
        title="Updated announcement",
        description="Updated announcement details",
        additional_data={
            "feature": "stable-feature",
            "link": "/new-link",
        },
        dedupe_by_additional_data={"feature": "stable-feature"},
    )
    db_session.commit()
    db_session.refresh(resurfaced_notification)

    assert resurfaced_notification.id == notification.id
    assert resurfaced_notification.dismissed is False
    assert resurfaced_notification.title == "Updated announcement"
    assert resurfaced_notification.description == "Updated announcement details"
    assert resurfaced_notification.additional_data == {
        "feature": "stable-feature",
        "link": "/new-link",
    }
    assert resurfaced_notification.first_shown != original_shown


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


def test_notification_summary_ensure_transactions_commit_and_rollback_independently(
    db_session: Session,
    tenant_context: None,  # noqa: ARG001
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user = create_test_user(db_session, "notification_summary_transactions")
    user_id = user.id
    calls: list[str] = []

    def create_ensure_notification(key: str, check_db_session: Session) -> None:
        create_notification(
            user_id=user_id,
            notif_type=NotificationType.APPROVAL_REQUESTED,
            db_session=check_db_session,
            title=f"{key} notification",
            additional_data={"ensure_transaction_key": key},
        )

    def ensure_build(_user: User, check_db_session: Session) -> None:
        calls.append("build")
        create_ensure_notification("build", check_db_session)

    def ensure_permissions(_user: User, check_db_session: Session) -> None:
        calls.append("permissions")
        create_ensure_notification("permissions", check_db_session)
        raise RuntimeError("permissions ensure failed")

    def ensure_release_notes(check_db_session: Session) -> None:
        calls.append("release_notes")
        create_ensure_notification("release_notes", check_db_session)

    monkeypatch.setattr(
        notifications_api,
        "ensure_build_mode_intro_notification",
        ensure_build,
    )
    monkeypatch.setattr(
        notifications_api,
        "ensure_permissions_migration_notification",
        ensure_permissions,
    )
    monkeypatch.setattr(
        notifications_api,
        "ensure_release_notes_fresh_and_notify",
        ensure_release_notes,
    )

    summary = notifications_api.get_notifications_summary_api(
        user=user,
        db_session=db_session,
    )

    notifications = get_notifications(
        user=user,
        db_session=db_session,
        include_dismissed=True,
        limit=10,
    )
    persisted_keys = {
        notification.additional_data["ensure_transaction_key"]
        for notification in notifications
        if notification.additional_data is not None
        and "ensure_transaction_key" in notification.additional_data
    }

    assert calls == ["build", "permissions", "release_notes"]
    assert persisted_keys == {"build", "release_notes"}
    assert summary.total_items == 2
    assert summary.undismissed_count == 2


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


def test_dismiss_notification_api_ignores_stale_last_shown(
    db_session: Session,
    tenant_context: None,  # noqa: ARG001
) -> None:
    user = create_test_user(db_session, "notification_stale_dismiss")
    first_shown = datetime(2026, 1, 1, tzinfo=timezone.utc)
    notification = _create_notification(
        db_session=db_session,
        user=user,
        index=1,
        first_shown=first_shown,
        dismissed=False,
    )
    last_shown = first_shown + timedelta(minutes=1)
    notification.last_shown = last_shown
    db_session.commit()

    notifications_api.dismiss_notification_endpoint(
        notification_id=notification.id,
        request=notifications_api.DismissNotificationRequest(
            expected_last_shown=last_shown - timedelta(minutes=1)
        ),
        user=user,
        db_session=db_session,
    )
    db_session.refresh(notification)
    assert notification.dismissed is False

    notifications_api.dismiss_notification_endpoint(
        notification_id=notification.id,
        request=notifications_api.DismissNotificationRequest(
            expected_last_shown=last_shown
        ),
        user=user,
        db_session=db_session,
    )
    db_session.refresh(notification)
    assert notification.dismissed is True


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
