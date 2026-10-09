"""Unit tests for onyx.utils.datetime window helpers."""

import datetime

import pytest

from onyx.utils.datetime import get_window_start


class TestGetWindowStart:
    def test_weekly_aligns_to_monday(self) -> None:
        # 2026-06-03 is a Wednesday.
        dt = datetime.datetime(2026, 6, 3, 14, 22, tzinfo=datetime.timezone.utc)
        window = get_window_start(dt, period_seconds=604_800)
        assert window.weekday() == 0  # Monday
        assert window == datetime.datetime(2026, 6, 1, tzinfo=datetime.timezone.utc)

    def test_hourly_epoch_aligned(self) -> None:
        dt = datetime.datetime(2026, 6, 3, 14, 59, 59, tzinfo=datetime.timezone.utc)
        window = get_window_start(dt, period_seconds=3_600)
        assert window == datetime.datetime(
            2026, 6, 3, 14, 0, 0, tzinfo=datetime.timezone.utc
        )

    def test_naive_datetime_treated_as_utc(self) -> None:
        naive = datetime.datetime(2026, 6, 3, 14, 30)
        aware = datetime.datetime(2026, 6, 3, 14, 30, tzinfo=datetime.timezone.utc)
        assert get_window_start(naive, 3_600) == get_window_start(aware, 3_600)

    def test_non_hour_window_preserves_exact_duration(self) -> None:
        dt = datetime.datetime(1970, 1, 1, 2, 20, tzinfo=datetime.timezone.utc)
        assert get_window_start(dt, 5_400) == datetime.datetime(
            1970, 1, 1, 1, 30, tzinfo=datetime.timezone.utc
        )

    def test_non_positive_period_rejected(self) -> None:
        with pytest.raises(ValueError, match="period_seconds must be positive"):
            get_window_start(datetime.datetime.now(datetime.timezone.utc), 0)
