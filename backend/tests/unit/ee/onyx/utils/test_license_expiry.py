from datetime import datetime
from datetime import timedelta
from datetime import timezone

import pytest

from ee.onyx.utils.license_expiry import ExpiryWarningStage
from ee.onyx.utils.license_expiry import get_expiry_warning_stage
from ee.onyx.utils.license_expiry import get_grace_days_remaining
from ee.onyx.utils.license_expiry import LICENSE_GRACE_PERIOD_DAYS

NOW = datetime(2026, 5, 1, 12, 0, 0, tzinfo=timezone.utc)


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
    assert get_expiry_warning_stage(NOW + delta, now=NOW) == want


def test_grace_days_remaining_full_window() -> None:
    just_expired = NOW - timedelta(seconds=1)
    assert get_grace_days_remaining(just_expired, now=NOW) == LICENSE_GRACE_PERIOD_DAYS


def test_grace_days_remaining_one_day_left() -> None:
    expires = NOW - timedelta(days=LICENSE_GRACE_PERIOD_DAYS - 1)
    assert get_grace_days_remaining(expires, now=NOW) == 1


def test_grace_days_remaining_exhausted() -> None:
    expires = NOW - timedelta(days=LICENSE_GRACE_PERIOD_DAYS)
    assert get_grace_days_remaining(expires, now=NOW) == 0
