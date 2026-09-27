from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeoutError
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from onyx.configs.constants import NotificationType
from onyx.db.connector_alerts import (
    clear_connector_alerts__no_commit,
    notify_admins_of_connector_alert,
)
from onyx.db.enums import NotificationSeverity
from onyx.db.models import Notification, User
from onyx.db.notification import (
    batch_create_notifications,
    count_notifications,
    create_notification,
    delete_notifications_by_additional_data,
    dismiss_user_notifications,
    get_notifications,
)
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


def test_create_notification_normalizes_missing_additional_data(
    db_session: Session,
    tenant_context: None,  # noqa: ARG001
) -> None:
    user = create_test_user(db_session, "notification_missing_data")

    first = create_notification(
        user_id=user.id,
        notif_type=NotificationType.FEATURE_ANNOUNCEMENT,
        db_session=db_session,
        title="No additional data",
    )
    second = create_notification(
        user_id=user.id,
        notif_type=NotificationType.FEATURE_ANNOUNCEMENT,
        db_session=db_session,
        title="No additional data",
    )

    assert second.id == first.id
    assert second.additional_data == {}
    matching_ids = db_session.scalars(
        select(Notification.id).where(
            Notification.user_id == user.id,
            Notification.notif_type == NotificationType.FEATURE_ANNOUNCEMENT,
        )
    ).all()
    assert matching_ids == [first.id]


def test_create_notification_matches_legacy_json_null_additional_data(
    db_session: Session,
    tenant_context: None,  # noqa: ARG001
) -> None:
    user = create_test_user(db_session, "notification_legacy_json_null")
    now = datetime.now(timezone.utc)
    legacy_notification = Notification(
        user_id=user.id,
        notif_type=NotificationType.FEATURE_ANNOUNCEMENT,
        dismissed=False,
        last_shown=now,
        first_shown=now,
        title="Legacy JSON null",
        additional_data=None,
    )
    db_session.add(legacy_notification)
    db_session.commit()
    legacy_notification_id = legacy_notification.id

    existing = create_notification(
        user_id=user.id,
        notif_type=NotificationType.FEATURE_ANNOUNCEMENT,
        db_session=db_session,
        title="Legacy JSON null",
    )

    assert existing.id == legacy_notification_id


def test_create_notification_handles_concurrent_insert(
    db_session: Session,
    tenant_context: None,  # noqa: ARG001
) -> None:
    user = create_test_user(db_session, "notification_concurrent_insert")
    additional_data = {"test": "concurrent_insert"}

    def create_competing_notification() -> int:
        with Session(bind=db_session.get_bind()) as competing_session:
            notification = create_notification(
                user_id=user.id,
                notif_type=NotificationType.FEATURE_ANNOUNCEMENT,
                db_session=competing_session,
                title="Competing notification",
                additional_data=additional_data,
            )
            return notification.id

    with Session(bind=db_session.get_bind()) as winning_session:
        winning_notification = Notification(
            user_id=user.id,
            notif_type=NotificationType.FEATURE_ANNOUNCEMENT,
            dismissed=False,
            last_shown=datetime.now(timezone.utc),
            first_shown=datetime.now(timezone.utc),
            title="Winning notification",
            additional_data=additional_data,
        )
        winning_session.add(winning_notification)
        winning_session.flush()
        winning_notification_id = winning_notification.id

        with ThreadPoolExecutor(max_workers=1) as executor:
            competing_result = executor.submit(create_competing_notification)
            with pytest.raises(FutureTimeoutError):
                competing_result.result(timeout=0.2)

            winning_session.commit()
            competing_notification_id = competing_result.result(timeout=5)

    assert competing_notification_id == winning_notification_id
    matching_notifications = list(
        db_session.scalars(
            select(Notification).where(
                Notification.user_id == user.id,
                Notification.notif_type == NotificationType.FEATURE_ANNOUNCEMENT,
                Notification.additional_data == additional_data,
            )
        ).all()
    )
    assert [notification.id for notification in matching_notifications] == [
        winning_notification_id
    ]


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


def test_get_notifications_filters_by_min_severity(
    db_session: Session,
    tenant_context: None,  # noqa: ARG001
) -> None:
    user = create_test_user(db_session, "notification_severity")
    for index, severity in enumerate(NotificationSeverity):
        create_notification(
            user_id=user.id,
            notif_type=NotificationType.APPROVAL_REQUESTED,
            db_session=db_session,
            title=f"severity {severity.value}",
            additional_data={"severity_case": index},
            severity=severity,
        )

    def severities(
        min_severity: NotificationSeverity | None,
    ) -> set[NotificationSeverity]:
        return {
            n.severity
            for n in get_notifications(
                user=user, db_session=db_session, min_severity=min_severity
            )
        }

    # No filter returns everything; min_severity is exact-or-above.
    assert severities(None) == set(NotificationSeverity)
    assert severities(NotificationSeverity.WARNING) == {
        NotificationSeverity.WARNING,
        NotificationSeverity.ERROR,
    }
    assert severities(NotificationSeverity.ERROR) == {NotificationSeverity.ERROR}

    total_items, undismissed_count = count_notifications(
        user=user,
        db_session=db_session,
        min_severity=NotificationSeverity.WARNING,
    )
    assert total_items == 2
    assert undismissed_count == 2


def test_get_notifications_api_filters_by_min_severity(
    db_session: Session,
    tenant_context: None,  # noqa: ARG001
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _disable_notification_ensure_checks(monkeypatch)
    monkeypatch.setattr(notifications_api, "_polled_ensure_cache", {})
    user = create_test_user(db_session, "notification_api_severity")
    for index, severity in enumerate(NotificationSeverity):
        create_notification(
            user_id=user.id,
            notif_type=NotificationType.APPROVAL_REQUESTED,
            db_session=db_session,
            title=f"severity {severity.value}",
            additional_data={"api_severity_case": index},
            severity=severity,
        )

    response = notifications_api.get_notifications_api(
        page_num=0,
        page_size=50,
        min_severity=NotificationSeverity.WARNING,
        user=user,
        db_session=db_session,
    )

    assert response.total_items == 2
    assert {n.severity for n in response.notifications} == {
        NotificationSeverity.WARNING,
        NotificationSeverity.ERROR,
    }


def test_get_notifications_api_polled_ensures_run_once_per_window(
    db_session: Session,
    tenant_context: None,  # noqa: ARG001
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A severity-only request (the banner poll) runs the banner-type ensures
    at most once per user per throttle window; the generic create-checks
    never run on that path."""
    generic_calls: list[str] = []

    def record_call(name: str) -> Callable[..., None]:
        def _record_call(*_args: object, **_kwargs: object) -> None:
            generic_calls.append(name)

        return _record_call

    for hook in (
        "ensure_build_mode_intro_notification",
        "ensure_permissions_migration_notification",
        "ensure_release_notes_fresh_and_notify",
    ):
        monkeypatch.setattr(notifications_api, hook, record_call(hook))

    banner_ensure_calls: list[str] = []

    def record_banner_ensure(name: str) -> Callable[..., bool]:
        def _record(*_args: object, **_kwargs: object) -> bool:
            banner_ensure_calls.append(name)
            return True

        return _record

    monkeypatch.setattr(
        notifications_api,
        "_ensure_system_announcement_notification",
        record_banner_ensure("announcement"),
    )
    monkeypatch.setattr(
        notifications_api,
        "_ensure_license_expiry_notification",
        record_banner_ensure("license"),
    )
    monkeypatch.setattr(notifications_api, "_polled_ensure_cache", {})

    user = create_test_user(db_session, "notification_api_polled_throttle")

    notifications_api.get_notifications_api(
        page_num=0,
        page_size=50,
        min_severity=NotificationSeverity.WARNING,
        user=user,
        db_session=db_session,
    )
    assert banner_ensure_calls == ["announcement", "license"]
    assert generic_calls == []

    banner_ensure_calls.clear()
    notifications_api.get_notifications_api(
        page_num=0,
        page_size=50,
        min_severity=NotificationSeverity.WARNING,
        user=user,
        db_session=db_session,
    )
    assert banner_ensure_calls == []
    assert generic_calls == []


def test_connector_alert_lifecycle_producer_and_recovery_agree(
    db_session: Session,
    tenant_context: None,  # noqa: ARG001
) -> None:
    """The producer and the recovery cleanup must target the same dedup key:
    fan-out on entering the error state, exact-match delete on recovery,
    fresh row on the next incident."""
    admin_one = create_test_user(db_session, "alert_lifecycle_admin1", is_admin=True)
    admin_two = create_test_user(db_session, "alert_lifecycle_admin2", is_admin=True)
    admin_ids = [admin_one.id, admin_two.id]
    cc_pair_id = 424242
    notif_type = NotificationType.CONNECTOR_REPEATED_ERRORS

    def produce() -> None:
        notify_admins_of_connector_alert(
            db_session=db_session,
            cc_pair_id=cc_pair_id,
            notif_type=notif_type,
            title="Connector 'Lifecycle Test' failed",
            description="test",
        )

    def rows() -> list[Notification]:
        return list(
            db_session.scalars(
                select(Notification).where(
                    Notification.notif_type == notif_type,
                    Notification.user_id.in_(admin_ids),
                )
            ).all()
        )

    # Incident: one ERROR row per admin; a repeat produce is a no-op.
    produce()
    produce()
    incident_rows = rows()
    assert len(incident_rows) == 2
    assert {r.severity for r in incident_rows} == {NotificationSeverity.ERROR}
    assert {(r.additional_data or {}).get("link") for r in incident_rows} == {
        f"/admin/connector/{cc_pair_id}"
    }

    # Recovery: cleanup deletes by the same helper-built key.
    clear_connector_alerts__no_commit(
        db_session=db_session,
        cc_pair_id=cc_pair_id,
        notif_type=notif_type,
    )
    db_session.commit()
    assert rows() == []

    # Next incident re-creates fresh undismissed rows.
    produce()
    assert len(rows()) == 2
