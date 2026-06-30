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
from onyx.db.notification import batch_create_notifications
from onyx.db.notification import count_notifications
from onyx.db.notification import create_notification
from onyx.db.notification import delete_notifications_by_additional_data
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


def test_get_notifications_api_filters_by_type_and_skips_generic_checks(
    db_session: Session,
    tenant_context: None,  # noqa: ARG001
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []

    def record_call(name: str) -> Callable[..., None]:
        def _record_call(*_args: object, **_kwargs: object) -> None:
            calls.append(name)

        return _record_call

    for hook in (
        "ensure_build_mode_intro_notification",
        "ensure_permissions_migration_notification",
        "ensure_release_notes_fresh_and_notify",
    ):
        monkeypatch.setattr(notifications_api, hook, record_call(hook))
    ensure_license_calls: list[object] = []
    monkeypatch.setattr(
        notifications_api,
        "_ensure_license_expiry_notification",
        lambda user, _db_session: ensure_license_calls.append(user.id),
    )

    user = create_test_user(db_session, "notification_api_type_filter")
    base_time = datetime(2026, 1, 1, tzinfo=timezone.utc)
    _create_notification(
        db_session=db_session,
        user=user,
        index=0,
        first_shown=base_time,
        dismissed=False,
    )
    db_session.add(
        Notification(
            user_id=user.id,
            notif_type=NotificationType.LICENSE_EXPIRY_WARNING,
            dismissed=False,
            last_shown=base_time,
            first_shown=base_time,
            title="License expiring",
            additional_data={"stage": "t_30d"},
        )
    )
    db_session.commit()

    response = notifications_api.get_notifications_api(
        page_num=0,
        page_size=50,
        notif_type=NotificationType.LICENSE_EXPIRY_WARNING,
        user=user,
        db_session=db_session,
    )

    assert response.total_items == 1
    assert [n.notif_type for n in response.notifications] == [
        NotificationType.LICENSE_EXPIRY_WARNING
    ]
    # Generic create-checks are skipped for the targeted read, but the license
    # filter still ensures the current admin's warning exists.
    assert calls == []
    assert ensure_license_calls == [user.id]


def test_get_notifications_api_non_license_filter_skips_license_ensure(
    db_session: Session,
    tenant_context: None,  # noqa: ARG001
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ensure_license_calls: list[object] = []
    monkeypatch.setattr(
        notifications_api,
        "_ensure_license_expiry_notification",
        lambda user, _db_session: ensure_license_calls.append(user.id),
    )

    user = create_test_user(db_session, "notification_api_non_license_filter")

    notifications_api.get_notifications_api(
        page_num=0,
        page_size=50,
        notif_type=NotificationType.APPROVAL_REQUESTED,
        user=user,
        db_session=db_session,
    )

    assert ensure_license_calls == []


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


def test_delete_notifications_by_additional_data_clears_all_admins_for_cc_pair(
    db_session: Session,
    tenant_context: None,  # noqa: ARG001
) -> None:
    # Mirrors the connector-error flow: an alert is fanned out to every admin
    # on error, then cleared for all of them when the connector recovers.
    admin_one = create_test_user(db_session, "notif_delete_admin_one")
    admin_two = create_test_user(db_session, "notif_delete_admin_two")

    batch_create_notifications(
        user_ids=[admin_one.id, admin_two.id],
        notif_type=NotificationType.CONNECTOR_REPEATED_ERRORS,
        db_session=db_session,
        title="Connector in repeated error state",
        additional_data={"cc_pair_id": 1},
    )
    # A different connector and a different type must survive the targeted clear.
    create_notification(
        user_id=admin_one.id,
        notif_type=NotificationType.CONNECTOR_REPEATED_ERRORS,
        db_session=db_session,
        title="Other connector in repeated error state",
        additional_data={"cc_pair_id": 2},
    )
    create_notification(
        user_id=admin_one.id,
        notif_type=NotificationType.APPROVAL_REQUESTED,
        db_session=db_session,
        title="Approval for cc_pair 1",
        additional_data={"cc_pair_id": 1},
    )

    admin_ids = [admin_one.id, admin_two.id]

    def rows_for(notif_type: NotificationType) -> list[Notification]:
        # Scope to the users this test created — the shared DB carries committed
        # rows from other tests, so a global query by type is not isolated.
        return list(
            db_session.scalars(
                select(Notification).where(
                    Notification.user_id.in_(admin_ids),
                    Notification.notif_type == notif_type,
                )
            ).all()
        )

    # Both admins start with a cc_pair_id=1 error notification.
    assert (
        len(
            [
                n
                for n in rows_for(NotificationType.CONNECTOR_REPEATED_ERRORS)
                if n.additional_data == {"cc_pair_id": 1}
            ]
        )
        == 2
    )

    # Dismissal must not shield a row from recovery cleanup — otherwise a
    # dismissed-then-recovered connector would never alert again.
    dismissed_row = next(
        n
        for n in rows_for(NotificationType.CONNECTOR_REPEATED_ERRORS)
        if n.user_id == admin_one.id and n.additional_data == {"cc_pair_id": 1}
    )
    dismissed_row.dismissed = True
    db_session.commit()

    delete_notifications_by_additional_data(
        notif_type=NotificationType.CONNECTOR_REPEATED_ERRORS,
        db_session=db_session,
        additional_data={"cc_pair_id": 1},
    )
    db_session.commit()

    # Every admin's cc_pair_id=1 row is gone; the cc_pair_id=2 row is untouched.
    assert [
        n.additional_data for n in rows_for(NotificationType.CONNECTOR_REPEATED_ERRORS)
    ] == [{"cc_pair_id": 2}]
    # A different notif_type with the same cc_pair_id is not affected.
    assert len(rows_for(NotificationType.APPROVAL_REQUESTED)) == 1


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
