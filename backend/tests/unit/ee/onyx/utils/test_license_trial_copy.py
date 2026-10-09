"""Guards that expiry notifications name a trial ending as a trial ending.

A trialing subscription mints a license that expires at the trial end, so the
ordinary expiry stages fire during a perfectly healthy trial. The copy has to
follow the license's trial_end, and licenses issued without that field have to
keep the original wording.
"""

from datetime import datetime, timedelta, timezone

import pytest

from ee.onyx.server.license.models import LicensePayload, PlanType
from ee.onyx.utils.license_expiry import ExpiryWarningStage
from ee.onyx.utils.license_notifications import _build_copy

NOW = datetime(2026, 7, 31, tzinfo=timezone.utc)
EXPIRES = NOW + timedelta(days=14)

WARNING_STAGES = [
    ExpiryWarningStage.T_30D,
    ExpiryWarningStage.T_14D,
    ExpiryWarningStage.T_1D,
]


def _payload(
    trial_end: datetime | None, expires_at: datetime = EXPIRES
) -> LicensePayload:
    return LicensePayload(
        version="1.0",
        tenant_id="tenant_123",
        issued_at=NOW,
        expires_at=expires_at,
        seats=50,
        plan_type=PlanType.MONTHLY,
        trial_end=trial_end,
    )


class TestEndsWithTrial:
    def test_a_license_running_to_its_trial_end_is_a_trial(self) -> None:
        assert _payload(trial_end=EXPIRES).ends_with_trial is True

    def test_a_license_without_a_trial_end_is_not(self) -> None:
        assert _payload(trial_end=None).ends_with_trial is False

    def test_a_converted_subscription_keeps_its_past_trial_end_but_is_not_a_trial(
        self,
    ) -> None:
        """Billing started, so the next lapse is a paid period ending."""
        converted = _payload(
            trial_end=NOW - timedelta(days=5), expires_at=NOW + timedelta(days=30)
        )

        assert converted.ends_with_trial is False


class TestTrialCopy:
    @pytest.mark.parametrize("stage", WARNING_STAGES)
    def test_a_trial_is_never_described_as_losing_access(
        self, stage: ExpiryWarningStage
    ) -> None:
        title, description, subject = _build_copy(stage, EXPIRES, 0, is_trial=True)

        assert "trial ends" in title
        assert "billing begins then" in description
        for text in (title, description, subject):
            assert "expire" not in text.lower()
            assert "service interruption" not in text.lower()

    def test_the_last_day_of_a_trial_reads_as_hours_not_a_date(self) -> None:
        _, description, _ = _build_copy(
            ExpiryWarningStage.T_1D, EXPIRES, 0, is_trial=True
        )

        assert "within 24 hours" in description

    def test_a_lapsed_trial_names_the_missing_billing_not_a_missing_renewal(
        self,
    ) -> None:
        title, description, _ = _build_copy(
            ExpiryWarningStage.GRACE, EXPIRES, 7, is_trial=True
        )

        assert "trial ended" in title
        assert "7 day(s)" in description
        assert "renew" not in description.lower()

    def test_billing_failing_at_trial_end_is_not_reported_as_a_failed_renewal(
        self,
    ) -> None:
        title, description, _ = _build_copy(
            ExpiryWarningStage.GRACE,
            EXPIRES,
            3,
            renewal_error="Your card was declined.",
            is_trial=True,
        )

        assert title == "Onyx could not start your subscription"
        assert "Your card was declined." in description
        assert "renewal" not in description.lower()


class TestNonTrialCopyIsUnchanged:
    @pytest.mark.parametrize(
        "stage,expected",
        [
            (ExpiryWarningStage.T_30D, "approximately 30 days"),
            (ExpiryWarningStage.T_14D, "approximately 2 weeks"),
            (ExpiryWarningStage.T_1D, "within 24 hours"),
        ],
    )
    def test_a_license_with_no_trial_end_keeps_the_original_wording(
        self, stage: ExpiryWarningStage, expected: str
    ) -> None:
        title, description, _ = _build_copy(stage, EXPIRES, 0, is_trial=False)

        assert "Onyx license expires" in title
        assert expected in description

    def test_grace_still_tells_a_paid_customer_to_renew(self) -> None:
        title, description, _ = _build_copy(
            ExpiryWarningStage.GRACE, EXPIRES, 5, is_trial=False
        )

        assert "license expired" in title
        assert "Renew now." in description

    def test_no_stage_is_not_copy(self) -> None:
        with pytest.raises(ValueError):
            _build_copy(ExpiryWarningStage.NONE, EXPIRES, 0, is_trial=True)
