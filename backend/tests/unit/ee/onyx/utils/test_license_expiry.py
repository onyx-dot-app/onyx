from datetime import datetime
from datetime import timedelta
from datetime import timezone
from unittest.mock import patch

import pytest

from ee.onyx.utils.license_expiry import ExpiryWarningStage
from ee.onyx.utils.license_expiry import get_expiry_warning_stage
from ee.onyx.utils.license_expiry import get_grace_days_remaining
from ee.onyx.utils.license_expiry import get_grace_period_end
from ee.onyx.utils.license_expiry import LICENSE_GRACE_PERIOD_DAYS

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
