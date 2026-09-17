from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest

from ee.onyx.utils.license_expiry import (
    LICENSE_GRACE_PERIOD_DAYS,
    ExpiryWarningStage,
    get_expiry_warning_stage,
    get_grace_days_remaining,
    get_grace_period_end,
)

NOW = datetime(2026, 5, 1, 12, 0, 0, tzinfo=timezone.utc)


def _patch_now() -> object:
    p = patch("ee.onyx.utils.license_expiry.datetime")
    mock = p.start()
    mock.now.return_value = NOW
    return p


@pytest.mark.parametrize(
    "delta,want",
    [
        (timedelta(days=60), ExpiryWarningStage.NONE),
        (timedelta(days=31), ExpiryWarningStage.NONE),
        (timedelta(days=30), ExpiryWarningStage.T_30D),
        (timedelta(days=15), ExpiryWarningStage.T_30D),
        (timedelta(days=14, seconds=1), ExpiryWarningStage.T_30D),
        (timedelta(days=14), ExpiryWarningStage.T_14D),
        (timedelta(days=2), ExpiryWarningStage.T_14D),
        (timedelta(days=1, seconds=1), ExpiryWarningStage.T_14D),
        (timedelta(days=1), ExpiryWarningStage.T_1D),
        (timedelta(hours=12), ExpiryWarningStage.T_1D),
        (timedelta(seconds=1), ExpiryWarningStage.T_1D),
        (timedelta(0), ExpiryWarningStage.GRACE),
        (timedelta(hours=-1), ExpiryWarningStage.GRACE),
        (timedelta(days=-1), ExpiryWarningStage.GRACE),
        (timedelta(days=-13), ExpiryWarningStage.GRACE),
        (timedelta(days=-14, seconds=1), ExpiryWarningStage.GRACE),
        (timedelta(days=-14), ExpiryWarningStage.NONE),
        (timedelta(days=-30), ExpiryWarningStage.NONE),
    ],
)
def test_get_expiry_warning_stage_boundaries(
    delta: timedelta, want: ExpiryWarningStage
) -> None:
    with patch("ee.onyx.utils.license_expiry.datetime") as dt:
        dt.now.return_value = NOW
        assert get_expiry_warning_stage(NOW + delta) == want


@pytest.mark.parametrize(
    "delta,want",
    [
        (timedelta(days=14), ExpiryWarningStage.NONE),
        (timedelta(days=4), ExpiryWarningStage.NONE),
        (timedelta(days=3, seconds=1), ExpiryWarningStage.NONE),
        (timedelta(days=3), ExpiryWarningStage.T_14D),
        (timedelta(days=2), ExpiryWarningStage.T_14D),
        (timedelta(days=1), ExpiryWarningStage.T_1D),
        (timedelta(hours=12), ExpiryWarningStage.T_1D),
        # Suppression covers the lead-up only, so a lapsed trial still reaches
        # grace, where the sync and the daily reminder hang off it.
        (timedelta(0), ExpiryWarningStage.GRACE),
        (timedelta(days=-13), ExpiryWarningStage.GRACE),
        (timedelta(days=-14), ExpiryWarningStage.NONE),
    ],
)
def test_a_trial_stays_quiet_until_its_final_days(
    delta: timedelta, want: ExpiryWarningStage
) -> None:
    """A trial is always Stripe-billed, so it is self-renewing too."""
    with patch("ee.onyx.utils.license_expiry.datetime") as dt:
        dt.now.return_value = NOW
        stage = get_expiry_warning_stage(
            NOW + delta, ends_with_trial=True, self_renewing=True
        )
        assert stage == want


@pytest.mark.parametrize(
    "delta,want",
    [
        (timedelta(days=25), ExpiryWarningStage.NONE),
        (timedelta(days=7), ExpiryWarningStage.NONE),
        (timedelta(hours=1), ExpiryWarningStage.NONE),
        # The renewal failing to arrive is the first thing worth saying.
        (timedelta(0), ExpiryWarningStage.GRACE),
        (timedelta(days=-13), ExpiryWarningStage.GRACE),
    ],
)
def test_a_self_renewing_license_warns_only_once_it_has_actually_lapsed(
    delta: timedelta, want: ExpiryWarningStage
) -> None:
    """Warning a Stripe-billed customer before expiry asks for an action that
    does not exist, since the replacement arrives on its own."""
    with patch("ee.onyx.utils.license_expiry.datetime") as dt:
        dt.now.return_value = NOW
        assert get_expiry_warning_stage(NOW + delta, self_renewing=True) == want


@pytest.mark.parametrize(
    "delta,want",
    [
        (timedelta(days=25), ExpiryWarningStage.T_30D),
        (timedelta(days=7), ExpiryWarningStage.T_14D),
        (timedelta(hours=12), ExpiryWarningStage.T_1D),
        (timedelta(days=-1), ExpiryWarningStage.GRACE),
    ],
)
def test_a_sales_issued_license_warns_across_the_whole_lead_up(
    delta: timedelta, want: ExpiryWarningStage
) -> None:
    """Nothing replaces it automatically, so every stage is actionable."""
    with patch("ee.onyx.utils.license_expiry.datetime") as dt:
        dt.now.return_value = NOW
        assert get_expiry_warning_stage(NOW + delta, self_renewing=False) == want


def test_grace_days_remaining_full_window() -> None:
    just_expired = NOW - timedelta(seconds=1)
    with patch("ee.onyx.utils.license_expiry.datetime") as dt:
        dt.now.return_value = NOW
        assert get_grace_days_remaining(just_expired) == LICENSE_GRACE_PERIOD_DAYS


def test_grace_days_remaining_one_day_left() -> None:
    expires = NOW - timedelta(days=LICENSE_GRACE_PERIOD_DAYS - 1)
    with patch("ee.onyx.utils.license_expiry.datetime") as dt:
        dt.now.return_value = NOW
        assert get_grace_days_remaining(expires) == 1


def test_grace_days_remaining_exhausted() -> None:
    expires = NOW - timedelta(days=LICENSE_GRACE_PERIOD_DAYS)
    with patch("ee.onyx.utils.license_expiry.datetime") as dt:
        dt.now.return_value = NOW
        assert get_grace_days_remaining(expires) == 0


def test_get_grace_period_end_is_expires_plus_window() -> None:
    expires = datetime(2026, 6, 1, 12, 0, 0, tzinfo=timezone.utc)
    assert get_grace_period_end(expires) == expires + timedelta(
        days=LICENSE_GRACE_PERIOD_DAYS
    )


def _status_with_default_grace(expires: datetime) -> str:
    """Reproduce the wiring in `update_license_cache`: derive the grace
    period end from `expires_at` and feed it to `get_license_status` so the
    middleware-facing status is consistent with the banner stage."""
    from unittest.mock import MagicMock

    from ee.onyx.utils.license import get_license_status

    payload = MagicMock()
    payload.expires_at = expires
    grace_end = get_grace_period_end(expires)
    with patch("ee.onyx.utils.license.datetime") as dt_mock:
        dt_mock.now.return_value = NOW
        return get_license_status(payload, grace_end).value


def test_default_grace_keeps_active_status_pre_expiry() -> None:
    expires = NOW + timedelta(days=10)
    assert _status_with_default_grace(expires) == "active"


def test_default_grace_returns_grace_period_within_window() -> None:
    expires = NOW - timedelta(days=5)
    assert _status_with_default_grace(expires) == "grace_period"


def test_default_grace_gates_after_window_exhausted() -> None:
    expires = NOW - timedelta(days=LICENSE_GRACE_PERIOD_DAYS + 1)
    assert _status_with_default_grace(expires) == "gated_access"
