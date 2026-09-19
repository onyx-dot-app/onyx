"""External dependency unit tests for the license-expiry beat task.

Verifies the task short-circuits correctly when:
- Multi-tenant cloud mode is enabled
- No license row exists
- License signature verification fails
- Stage derivation returns NONE

And dispatches to ``notify_admins_for_stage`` only when there is a real,
verifiable, in-window license.
"""

from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest

from ee.onyx.background.celery.tasks.license_notifications.tasks import (
    check_license_expiry_notifications_task,
)
from ee.onyx.utils.license_expiry import ExpiryWarningStage

_TASK_MODULE = "ee.onyx.background.celery.tasks.license_notifications.tasks"


pytestmark = pytest.mark.usefixtures("db_session", "tenant_context")


def _fake_payload(expires_in_days: int = 25, self_renewing: bool = False) -> MagicMock:
    payload = MagicMock()
    payload.expires_at = datetime.now(timezone.utc) + timedelta(days=expires_in_days)
    # Explicit: bare MagicMock attributes are truthy, which would read as a
    # self-renewing trial and suppress the warning ladder.
    payload.ends_with_trial = False
    payload.self_renewing = self_renewing
    return payload


def _fake_license_row() -> MagicMock:
    row = MagicMock()
    row.license_data = "fake-base64-license"
    return row


def test_multi_tenant_short_circuits() -> None:
    with (
        patch(f"{_TASK_MODULE}.MULTI_TENANT", True),
        patch(f"{_TASK_MODULE}.notify_admins_for_stage") as notify,
        patch(f"{_TASK_MODULE}.get_license") as get_license_fn,
    ):
        check_license_expiry_notifications_task(tenant_id="anything")

    assert notify.call_count == 0
    assert get_license_fn.call_count == 0


def test_no_license_row_skips() -> None:
    with (
        patch(f"{_TASK_MODULE}.MULTI_TENANT", False),
        patch(f"{_TASK_MODULE}.get_license", return_value=None),
        patch(f"{_TASK_MODULE}.notify_admins_for_stage") as notify,
    ):
        check_license_expiry_notifications_task(tenant_id="t")

    assert notify.call_count == 0


def test_signature_failure_skips() -> None:
    with (
        patch(f"{_TASK_MODULE}.MULTI_TENANT", False),
        patch(f"{_TASK_MODULE}.get_license", return_value=_fake_license_row()),
        patch(
            f"{_TASK_MODULE}.verify_license_signature",
            side_effect=ValueError("bad sig"),
        ),
        patch(f"{_TASK_MODULE}.notify_admins_for_stage") as notify,
    ):
        check_license_expiry_notifications_task(tenant_id="t")

    assert notify.call_count == 0


def test_stage_none_skips() -> None:
    """License valid but >30 days out → stage NONE → no notification work."""
    with (
        patch(f"{_TASK_MODULE}.MULTI_TENANT", False),
        patch(f"{_TASK_MODULE}.get_license", return_value=_fake_license_row()),
        patch(
            f"{_TASK_MODULE}.verify_license_signature",
            return_value=_fake_payload(expires_in_days=120),
        ),
        patch(f"{_TASK_MODULE}.notify_admins_for_stage") as notify,
    ):
        check_license_expiry_notifications_task(tenant_id="t")

    assert notify.call_count == 0


def test_in_window_dispatches_to_notify() -> None:
    """A sales-issued license within T_30D dispatches, since a person has to
    go get its replacement."""
    payload = _fake_payload(expires_in_days=25)
    with (
        patch(f"{_TASK_MODULE}.MULTI_TENANT", False),
        patch(f"{_TASK_MODULE}.get_license", return_value=_fake_license_row()),
        patch(f"{_TASK_MODULE}.verify_license_signature", return_value=payload),
        patch(f"{_TASK_MODULE}.notify_admins_for_stage") as notify,
    ):
        check_license_expiry_notifications_task(tenant_id="t")

    assert notify.call_count == 1
    call_kwargs = notify.call_args.kwargs
    assert call_kwargs["stage"] == ExpiryWarningStage.T_30D
    assert call_kwargs["expires_at"] == payload.expires_at


def test_self_renewing_license_is_suppressed_before_lapse() -> None:
    """A Stripe-billed license renews itself, so its lead-up stages give the
    admin nothing to act on and must not notify."""
    payload = _fake_payload(expires_in_days=25, self_renewing=True)
    with (
        patch(f"{_TASK_MODULE}.MULTI_TENANT", False),
        patch(f"{_TASK_MODULE}.get_license", return_value=_fake_license_row()),
        patch(f"{_TASK_MODULE}.verify_license_signature", return_value=payload),
        patch(f"{_TASK_MODULE}.notify_admins_for_stage") as notify,
    ):
        check_license_expiry_notifications_task(tenant_id="t")

    assert notify.call_count == 0
