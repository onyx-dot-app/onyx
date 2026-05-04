"""External dependency unit tests for license-expiry notification orchestration.

Verifies idempotency, stage-transition behavior, and grace-period daily cadence
against a real PostgreSQL database. The email send path is patched so we can
assert "fresh insert only" behavior without configuring SendGrid.
"""

from datetime import datetime
from datetime import timedelta
from datetime import timezone
from unittest.mock import patch
from uuid import UUID

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from ee.onyx.utils.license_expiry import ExpiryWarningStage
from ee.onyx.utils.license_notifications import notify_admins_for_stage
from onyx.configs.constants import NotificationType
from onyx.db.models import Notification
from onyx.db.models import User
from onyx.db.models import UserRole
from tests.external_dependency_unit.conftest import create_test_user

EXPIRES_AT = datetime(2026, 6, 1, 12, 0, 0, tzinfo=timezone.utc)


@pytest.fixture(autouse=True)
def email_configured() -> object:
    """Default to the local-email path so existing tests assert against it.

    Tests covering the control-plane fallback override this explicitly.
    """
    with patch("ee.onyx.utils.license_notifications.EMAIL_CONFIGURED", True):
        yield


@pytest.fixture
def admin(
    db_session: Session,
    tenant_context: None,  # noqa: ARG001
) -> User:
    return create_test_user(db_session, "license_admin", role=UserRole.ADMIN)


@pytest.fixture
def two_admins(
    db_session: Session,
    tenant_context: None,  # noqa: ARG001
) -> list[User]:
    return [
        create_test_user(db_session, "license_admin1", role=UserRole.ADMIN),
        create_test_user(db_session, "license_admin2", role=UserRole.ADMIN),
    ]


@pytest.fixture
def basic_user(
    db_session: Session,
    tenant_context: None,  # noqa: ARG001
) -> User:
    return create_test_user(db_session, "license_basic", role=UserRole.BASIC)


def _count_license_notifs(
    db_session: Session, user_id: UUID, stage_value: str | None = None
) -> int:
    query = select(Notification).where(
        Notification.user_id == user_id,
        Notification.notif_type == NotificationType.LICENSE_EXPIRY_WARNING,
    )
    rows = db_session.execute(query).scalars().all()
    if stage_value is None:
        return len(rows)
    return sum(1 for r in rows if (r.additional_data or {}).get("stage") == stage_value)


def test_stage_none_short_circuits(db_session: Session) -> None:
    with patch("ee.onyx.utils.license_notifications._send_local_email") as send_email:
        notify_admins_for_stage(db_session, ExpiryWarningStage.NONE, EXPIRES_AT)
    assert send_email.call_count == 0


def test_basic_users_are_not_notified(
    db_session: Session, admin: User, basic_user: User
) -> None:
    """The role filter excludes BASIC users — only ADMINs get notified."""
    with patch("ee.onyx.utils.license_notifications._send_local_email") as send_email:
        notify_admins_for_stage(db_session, ExpiryWarningStage.T_30D, EXPIRES_AT)
    assert _count_license_notifs(db_session, basic_user.id) == 0
    assert _count_license_notifs(db_session, admin.id, "t_30d") == 1
    targeted = {c.kwargs["user_email"] for c in send_email.call_args_list}
    assert basic_user.email not in targeted
    assert admin.email in targeted


def test_first_call_creates_notification_and_sends_email(
    db_session: Session, admin: User
) -> None:
    with patch("ee.onyx.utils.license_notifications._send_local_email") as send_email:
        notify_admins_for_stage(db_session, ExpiryWarningStage.T_30D, EXPIRES_AT)

    assert _count_license_notifs(db_session, admin.id, "t_30d") == 1
    admin_email_calls = [
        c for c in send_email.call_args_list if c.kwargs["user_email"] == admin.email
    ]
    assert len(admin_email_calls) == 1


def test_second_call_same_stage_is_noop(db_session: Session, admin: User) -> None:
    """Second invocation with identical (stage, expires_at) — no new row, no email."""
    with patch("ee.onyx.utils.license_notifications._send_local_email"):
        notify_admins_for_stage(db_session, ExpiryWarningStage.T_30D, EXPIRES_AT)

    with patch("ee.onyx.utils.license_notifications._send_local_email") as send_email_2:
        notify_admins_for_stage(db_session, ExpiryWarningStage.T_30D, EXPIRES_AT)

    admin_email_calls = [
        c for c in send_email_2.call_args_list if c.kwargs["user_email"] == admin.email
    ]
    assert len(admin_email_calls) == 0
    assert _count_license_notifs(db_session, admin.id, "t_30d") == 1


def test_stage_transition_creates_new_notification(
    db_session: Session, admin: User
) -> None:
    """T_30D then T_14D → distinct rows + distinct email per stage."""
    with patch("ee.onyx.utils.license_notifications._send_local_email"):
        notify_admins_for_stage(db_session, ExpiryWarningStage.T_30D, EXPIRES_AT)

    with patch("ee.onyx.utils.license_notifications._send_local_email") as send_email_2:
        notify_admins_for_stage(db_session, ExpiryWarningStage.T_14D, EXPIRES_AT)

    assert _count_license_notifs(db_session, admin.id, "t_30d") == 1
    assert _count_license_notifs(db_session, admin.id, "t_14d") == 1
    admin_email_calls = [
        c for c in send_email_2.call_args_list if c.kwargs["user_email"] == admin.email
    ]
    assert len(admin_email_calls) == 1


def test_grace_period_fires_once_per_day(db_session: Session, admin: User) -> None:
    """Grace stage with same expires_at but different sent_date → new fire."""
    grace_expires = datetime(2026, 6, 1, 12, 0, 0, tzinfo=timezone.utc)
    day1 = datetime(2026, 6, 5, 12, 0, 0, tzinfo=timezone.utc)
    day2 = datetime(2026, 6, 6, 12, 0, 0, tzinfo=timezone.utc)

    with (
        patch("ee.onyx.utils.license_notifications.datetime") as dt,
        patch("ee.onyx.utils.license_notifications._send_local_email") as send_email_d1,
    ):
        dt.now.return_value = day1
        notify_admins_for_stage(db_session, ExpiryWarningStage.GRACE, grace_expires)

    with (
        patch("ee.onyx.utils.license_notifications.datetime") as dt,
        patch("ee.onyx.utils.license_notifications._send_local_email") as send_email_d2,
    ):
        dt.now.return_value = day2
        notify_admins_for_stage(db_session, ExpiryWarningStage.GRACE, grace_expires)

    d1_calls = [
        c for c in send_email_d1.call_args_list if c.kwargs["user_email"] == admin.email
    ]
    d2_calls = [
        c for c in send_email_d2.call_args_list if c.kwargs["user_email"] == admin.email
    ]
    assert len(d1_calls) == 1
    assert len(d2_calls) == 1
    assert _count_license_notifs(db_session, admin.id, "grace") == 2


def test_grace_period_same_day_is_noop(db_session: Session, admin: User) -> None:
    """Grace stage called twice with same sent_date → no second email."""
    grace_expires = datetime(2026, 6, 1, 12, 0, 0, tzinfo=timezone.utc)
    same_day = datetime(2026, 6, 5, 12, 0, 0, tzinfo=timezone.utc)

    with (
        patch("ee.onyx.utils.license_notifications.datetime") as dt,
        patch("ee.onyx.utils.license_notifications._send_local_email"),
    ):
        dt.now.return_value = same_day
        notify_admins_for_stage(db_session, ExpiryWarningStage.GRACE, grace_expires)

    with (
        patch("ee.onyx.utils.license_notifications.datetime") as dt,
        patch("ee.onyx.utils.license_notifications._send_local_email") as send_email_2,
    ):
        dt.now.return_value = same_day
        notify_admins_for_stage(db_session, ExpiryWarningStage.GRACE, grace_expires)

    admin_email_calls = [
        c for c in send_email_2.call_args_list if c.kwargs["user_email"] == admin.email
    ]
    assert len(admin_email_calls) == 0


def test_two_admins_both_get_notified(
    db_session: Session, two_admins: list[User]
) -> None:
    a1, a2 = two_admins
    with patch("ee.onyx.utils.license_notifications._send_local_email") as send_email:
        notify_admins_for_stage(
            db_session,
            ExpiryWarningStage.T_1D,
            EXPIRES_AT + timedelta(days=10),
        )

    assert _count_license_notifs(db_session, a1.id, "t_1d") == 1
    assert _count_license_notifs(db_session, a2.id, "t_1d") == 1
    targeted_emails = {c.kwargs["user_email"] for c in send_email.call_args_list}
    assert a1.email in targeted_emails
    assert a2.email in targeted_emails


def test_falls_back_to_control_plane_when_local_email_disabled(
    db_session: Session, admin: User
) -> None:
    """When EMAIL_CONFIGURED is False, route via the cloud DP proxy once per fire."""
    with (
        patch("ee.onyx.utils.license_notifications.EMAIL_CONFIGURED", False),
        patch("ee.onyx.utils.license_notifications._send_local_email") as send_local,
        patch(
            "ee.onyx.utils.license_notifications._send_via_control_plane",
            return_value=True,
        ) as send_cp,
    ):
        notify_admins_for_stage(db_session, ExpiryWarningStage.T_30D, EXPIRES_AT)

    assert send_local.call_count == 0
    assert send_cp.call_count == 1
    cp_kwargs = send_cp.call_args.kwargs
    assert cp_kwargs["stage"] == ExpiryWarningStage.T_30D
    assert cp_kwargs["expires_at"] == EXPIRES_AT
    assert _count_license_notifs(db_session, admin.id, "t_30d") == 1


def test_control_plane_fallback_fires_once_for_many_admins(
    db_session: Session, two_admins: list[User]
) -> None:
    """CP recipient is per-tenant (Stripe customer), so one call regardless of admin count."""
    a1, a2 = two_admins
    with (
        patch("ee.onyx.utils.license_notifications.EMAIL_CONFIGURED", False),
        patch(
            "ee.onyx.utils.license_notifications._send_via_control_plane",
            return_value=True,
        ) as send_cp,
    ):
        notify_admins_for_stage(
            db_session,
            ExpiryWarningStage.T_1D,
            EXPIRES_AT + timedelta(days=10),
        )

    assert send_cp.call_count == 1
    assert _count_license_notifs(db_session, a1.id, "t_1d") == 1
    assert _count_license_notifs(db_session, a2.id, "t_1d") == 1
