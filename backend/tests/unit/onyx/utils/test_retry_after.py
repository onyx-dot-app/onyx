from datetime import datetime
from datetime import timedelta
from datetime import timezone
from email.utils import format_datetime

import pytest

from onyx.utils.retry_after import parse_retry_after_seconds


@pytest.mark.parametrize(
    "value,expected",
    [
        ("0", 0.0),
        ("1", 1.0),
        ("120", 120.0),
        ("12.5", 12.5),
        ("  30  ", 30.0),
        # Negative seconds are nonsensical; floor at 0.
        ("-5", 0.0),
    ],
)
def test_parses_delay_seconds(value: str, expected: float) -> None:
    assert parse_retry_after_seconds(value) == expected


@pytest.mark.parametrize("value", [None, "", "   ", "not-a-date", "soon"])
def test_returns_none_for_missing_or_unparseable(value: str | None) -> None:
    assert parse_retry_after_seconds(value) is None


@pytest.mark.parametrize(
    "value", ["nan", "inf", "-inf", "infinity", "Inf", "NaN", "1e400"]
)
def test_rejects_non_finite_numbers(value: str) -> None:
    # These parse as floats but are not valid delays; they must not produce an
    # undefined or unbounded sleep.
    assert parse_retry_after_seconds(value) is None


def test_parses_future_http_date() -> None:
    future = datetime.now(timezone.utc) + timedelta(seconds=120)
    parsed = parse_retry_after_seconds(format_datetime(future, usegmt=True))
    assert parsed is not None
    # Allow a little slack for clock drift / execution time.
    assert 110 <= parsed <= 121


def test_past_http_date_floors_at_zero() -> None:
    past = datetime.now(timezone.utc) - timedelta(hours=1)
    assert parse_retry_after_seconds(format_datetime(past, usegmt=True)) == 0.0


def test_parses_literal_http_date_string() -> None:
    # A date far in the past must floor at 0 regardless of formatting details.
    assert parse_retry_after_seconds("Wed, 21 Oct 2015 07:28:00 GMT") == 0.0
