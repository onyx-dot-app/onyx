"""External dependency unit tests for license-expiry notification orchestration.

Verifies idempotency, stage-transition behavior, and grace-period daily cadence
against a real PostgreSQL database. The email send path is patched so we can
assert "fresh insert only" behavior without configuring SendGrid.
"""

from collections.abc import Generator
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch
from uuid import UUID

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from ee.onyx.db.license import delete_license, get_license, upsert_license
from ee.onyx.server.license.models import LicensePayload, PlanType
from ee.onyx.utils.license import verify_and_store_license
from ee.onyx.utils.license_expiry import ExpiryWarningStage
from ee.onyx.utils.license_notifications import (
    ensure_license_expiry_notification_for_user,
    notify_admins_for_stage,
)
from onyx.configs.constants import NotificationType
from onyx.db.models import Notification, User
from tests.external_dependency_unit.conftest import create_test_user

EXPIRES_AT = datetime(2026, 6, 1, 12, 0, 0, tzinfo=timezone.utc)
RENEWED_EXPIRES_AT = EXPIRES_AT + timedelta(days=365)
_STORED_EXPIRY = "ee.onyx.utils.license_notifications._stored_license_expires_at"


@pytest.fixture(autouse=True)
def _no_stored_license() -> Generator[None, None, None]:
    """Keep the license in the shared test database out of these tests."""
    with patch(_STORED_EXPIRY, return_value=None):
        yield


@pytest.fixture
def admin(
    db_session: Session,
    tenant_context: None,  # noqa: ARG001
) -> User:
    return create_test_user(db_session, "license_admin", is_admin=True)


@pytest.fixture
def two_admins(
    db_session: Session,
    tenant_context: None,  # noqa: ARG001
) -> list[User]:
    return [
        create_test_user(db_session, "license_admin1", is_admin=True),
        create_test_user(db_session, "license_admin2", is_admin=True),
    ]


@pytest.fixture
def basic_user(
    db_session: Session,
    tenant_context: None,  # noqa: ARG001
) -> User:
    return create_test_user(db_session, "license_basic")


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
    with patch(
        "ee.onyx.utils.license_notifications._send_email_for_stage"
    ) as send_email:
        notify_admins_for_stage(db_session, ExpiryWarningStage.NONE, EXPIRES_AT)
    assert send_email.call_count == 0


def test_basic_users_are_not_notified(
    db_session: Session, admin: User, basic_user: User
) -> None:
    """The role filter excludes BASIC users — only ADMINs get notified."""
    with patch(
        "ee.onyx.utils.license_notifications._send_email_for_stage"
    ) as send_email:
        notify_admins_for_stage(db_session, ExpiryWarningStage.T_30D, EXPIRES_AT)
    assert _count_license_notifs(db_session, basic_user.id) == 0
    assert _count_license_notifs(db_session, admin.id, "t_30d") == 1
    targeted = {c.kwargs["user_email"] for c in send_email.call_args_list}
    assert basic_user.email not in targeted
    assert admin.email in targeted


def test_first_call_creates_notification_and_sends_email(
    db_session: Session, admin: User
) -> None:
    with patch(
        "ee.onyx.utils.license_notifications._send_email_for_stage"
    ) as send_email:
        notify_admins_for_stage(db_session, ExpiryWarningStage.T_30D, EXPIRES_AT)

    assert _count_license_notifs(db_session, admin.id, "t_30d") == 1
    admin_email_calls = [
        c for c in send_email.call_args_list if c.kwargs["user_email"] == admin.email
    ]
    assert len(admin_email_calls) == 1


def test_second_call_same_stage_is_noop(db_session: Session, admin: User) -> None:
    """Second invocation with identical (stage, expires_at) — no new row, no email."""
    with patch("ee.onyx.utils.license_notifications._send_email_for_stage"):
        notify_admins_for_stage(db_session, ExpiryWarningStage.T_30D, EXPIRES_AT)

    with patch(
        "ee.onyx.utils.license_notifications._send_email_for_stage"
    ) as send_email_2:
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
    with patch("ee.onyx.utils.license_notifications._send_email_for_stage"):
        notify_admins_for_stage(db_session, ExpiryWarningStage.T_30D, EXPIRES_AT)

    with patch(
        "ee.onyx.utils.license_notifications._send_email_for_stage"
    ) as send_email_2:
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
        patch(
            "ee.onyx.utils.license_notifications._send_email_for_stage"
        ) as send_email_d1,
    ):
        dt.now.return_value = day1
        notify_admins_for_stage(db_session, ExpiryWarningStage.GRACE, grace_expires)

    with (
        patch("ee.onyx.utils.license_notifications.datetime") as dt,
        patch(
            "ee.onyx.utils.license_notifications._send_email_for_stage"
        ) as send_email_d2,
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
        patch("ee.onyx.utils.license_notifications._send_email_for_stage"),
    ):
        dt.now.return_value = same_day
        notify_admins_for_stage(db_session, ExpiryWarningStage.GRACE, grace_expires)

    with (
        patch("ee.onyx.utils.license_notifications.datetime") as dt,
        patch(
            "ee.onyx.utils.license_notifications._send_email_for_stage"
        ) as send_email_2,
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
    with patch(
        "ee.onyx.utils.license_notifications._send_email_for_stage"
    ) as send_email:
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


def _license_notif_dismissed(
    db_session: Session, user_id: UUID, expires_at: datetime
) -> list[bool]:
    db_session.expire_all()
    rows = (
        db_session.execute(
            select(Notification).where(
                Notification.user_id == user_id,
                Notification.notif_type == NotificationType.LICENSE_EXPIRY_WARNING,
            )
        )
        .scalars()
        .all()
    )
    return [
        r.dismissed
        for r in rows
        if (r.additional_data or {}).get("expires_at") == expires_at.isoformat()
    ]


def test_storing_renewal_dismisses_old_license_warnings(
    db_session: Session, admin: User
) -> None:
    """A renewal clears the replaced license's banners but keeps any already
    raised for the new license's own expiry."""
    renewed_expires = RENEWED_EXPIRES_AT
    with patch("ee.onyx.utils.license_notifications._send_email_for_stage"):
        notify_admins_for_stage(db_session, ExpiryWarningStage.GRACE, EXPIRES_AT)
        notify_admins_for_stage(db_session, ExpiryWarningStage.T_30D, renewed_expires)

    renewal = LicensePayload(
        version="1.0",
        tenant_id="tenant_renewal",
        issued_at=datetime.now(timezone.utc),
        expires_at=renewed_expires,
        seats=10,
        plan_type=PlanType.ANNUAL,
    )
    previous = get_license(db_session)
    previous_data = previous.license_data if previous else None
    try:
        with (
            patch(
                "ee.onyx.utils.license.verify_license_signature",
                return_value=renewal,
            ),
            patch("ee.onyx.utils.license.publish_license_cache"),
            patch("ee.onyx.utils.license.resume_license_reclaim"),
        ):
            verify_and_store_license(db_session, "renewed-license-blob")
    finally:
        if previous_data is None:
            delete_license(db_session)
        else:
            upsert_license(db_session, previous_data)

    assert _license_notif_dismissed(db_session, admin.id, EXPIRES_AT) == [True]
    assert _license_notif_dismissed(db_session, admin.id, renewed_expires) == [False]


def test_warning_for_replaced_license_is_not_written(
    db_session: Session, admin: User
) -> None:
    """A daily run that read the license before a renewal landed must not
    write a warning for the replaced expiry."""
    with (
        patch(_STORED_EXPIRY, return_value=RENEWED_EXPIRES_AT),
        patch(
            "ee.onyx.utils.license_notifications._send_email_for_stage"
        ) as send_email,
    ):
        notify_admins_for_stage(db_session, ExpiryWarningStage.GRACE, EXPIRES_AT)

    assert _license_notif_dismissed(db_session, admin.id, EXPIRES_AT) == []
    assert send_email.call_count == 0


def test_on_read_warning_for_replaced_license_is_not_written(
    db_session: Session, admin: User
) -> None:
    """The on-read ensure has the same window: it read the replaced license,
    and the stored one changed before its insert."""
    # Relative to now so the replaced license is inside a warning window.
    replaced_expires = datetime.now(timezone.utc) + timedelta(days=10)
    replaced = LicensePayload(
        version="1.0",
        tenant_id="tenant_replaced",
        issued_at=replaced_expires - timedelta(days=365),
        expires_at=replaced_expires,
        seats=10,
        plan_type=PlanType.ANNUAL,
    )
    license_row = MagicMock(license_data="replaced-license-blob")
    with (
        patch(_STORED_EXPIRY, return_value=replaced_expires + timedelta(days=365)),
        patch(
            "ee.onyx.utils.license_notifications.get_license",
            return_value=license_row,
        ),
        patch(
            "ee.onyx.utils.license_notifications.verify_license_signature",
            return_value=replaced,
        ),
        patch("ee.onyx.utils.license_notifications.MULTI_TENANT", False),
    ):
        ensure_license_expiry_notification_for_user(admin, db_session)

    assert _license_notif_dismissed(db_session, admin.id, replaced_expires) == []
