"""Guards the grace-entry renewal fetch: an expired instance pulls the license
it is waiting on where the stage is already computed, and an admin is told what
actually failed rather than to renew something Onyx already tried to renew."""

from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest
import requests

from ee.onyx.background.celery.tasks.license_notifications.tasks import (
    check_license_expiry_notifications_task,
)
from ee.onyx.server.license.models import LicensePayload, LicenseSource, PlanType
from ee.onyx.utils.license import LicenseRejectedError

TASKS_MODULE = "ee.onyx.background.celery.tasks.license_notifications.tasks"


def _payload(*, expires_delta: timedelta, issued_delta: timedelta) -> LicensePayload:
    now = datetime.now(timezone.utc)
    return LicensePayload(
        version="1.0",
        tenant_id="tenant_123",
        organization_name="Test Org",
        issued_at=now + issued_delta,
        expires_at=now + expires_delta,
        seats=10,
        plan_type=PlanType.MONTHLY,
        stripe_customer_id="cus_123",
    )


def _run(
    *, stored: LicensePayload, reclaim: object = None
) -> tuple[MagicMock, MagicMock]:
    with (
        patch(f"{TASKS_MODULE}.get_session_with_current_tenant") as mock_session,
        patch(f"{TASKS_MODULE}.get_license") as mock_get_license,
        patch(f"{TASKS_MODULE}.verify_license_signature", return_value=stored),
        patch(f"{TASKS_MODULE}.reclaim_license_from_control_plane") as mock_reclaim,
        patch(f"{TASKS_MODULE}.notify_admins_for_stage") as mock_notify,
    ):
        mock_session.return_value.__enter__.return_value = MagicMock()
        mock_get_license.return_value = MagicMock(license_data="blob")
        if isinstance(reclaim, Exception):
            mock_reclaim.side_effect = reclaim
        elif reclaim is not None:
            mock_reclaim.return_value = reclaim
        check_license_expiry_notifications_task(tenant_id="tenant_123")
    return mock_notify, mock_reclaim


class TestGraceEntryFetchesTheRenewal:
    def test_a_renewal_silences_the_warning(self) -> None:
        """The customer renewed. Warning them tells a healthy account to renew
        immediately."""
        stored = _payload(
            expires_delta=timedelta(days=-1), issued_delta=timedelta(days=-31)
        )
        renewed = _payload(
            expires_delta=timedelta(days=29), issued_delta=timedelta(minutes=-1)
        )

        notify, _ = _run(stored=stored, reclaim=renewed)

        notify.assert_not_called()

    def test_no_renewal_available_says_so(self) -> None:
        """Same license back means the subscription did not renew."""
        stored = _payload(
            expires_delta=timedelta(days=-1), issued_delta=timedelta(days=-31)
        )
        notify, _ = _run(stored=stored, reclaim=stored)

        assert "No renewed license" in notify.call_args.kwargs["renewal_error"]

    def test_a_rejection_reports_the_upstream_reason(self) -> None:
        stored = _payload(
            expires_delta=timedelta(days=-1), issued_delta=timedelta(days=-31)
        )
        notify, _ = _run(
            stored=stored,
            reclaim=LicenseRejectedError("Invalid license: Invalid license signature"),
        )

        assert "Invalid license" in notify.call_args.kwargs["renewal_error"]

    def test_an_unreachable_control_plane_is_not_a_billing_failure(self) -> None:
        """Telling an admin their billing failed when Onyx was unreachable
        sends them to fix a card that is fine."""
        stored = _payload(
            expires_delta=timedelta(days=-1), issued_delta=timedelta(days=-31)
        )
        notify, _ = _run(stored=stored, reclaim=requests.ConnectionError("down"))

        assert "could not be reached" in notify.call_args.kwargs["renewal_error"]

    def test_a_sales_license_is_never_fetched(self) -> None:
        """No Stripe customer means no control plane to ask."""
        stored = _payload(
            expires_delta=timedelta(days=-1), issued_delta=timedelta(days=-31)
        )
        stored.stripe_customer_id = None
        assert stored.source == LicenseSource.MANUAL_UPLOAD

        notify, reclaim = _run(stored=stored)

        reclaim.assert_not_called()
        assert "sales" in notify.call_args.kwargs["renewal_error"]

    @pytest.mark.parametrize("expires_delta", [timedelta(days=3), timedelta(days=20)])
    def test_no_fetch_before_the_license_actually_expires(
        self, expires_delta: timedelta
    ) -> None:
        """A renewal only exists once the period ends, so fetching earlier polls
        the control plane for something it cannot have yet."""
        stored = _payload(expires_delta=expires_delta, issued_delta=timedelta(days=-27))

        _, reclaim = _run(stored=stored)

        reclaim.assert_not_called()
