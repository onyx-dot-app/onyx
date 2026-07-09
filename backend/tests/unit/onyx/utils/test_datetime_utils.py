"""Unit tests for onyx.utils.datetime window helpers."""

import datetime

from onyx.utils.datetime import get_window_start


class TestGetWindowStart:
    def test_weekly_aligns_to_monday(self) -> None:
        # 2026-06-03 is a Wednesday.
        dt = datetime.datetime(2026, 6, 3, 14, 22, tzinfo=datetime.timezone.utc)
        window = get_window_start(dt, period_hours=168)
        assert window.weekday() == 0  # Monday
        assert window == datetime.datetime(2026, 6, 1, tzinfo=datetime.timezone.utc)

    def test_hourly_epoch_aligned(self) -> None:
        dt = datetime.datetime(2026, 6, 3, 14, 59, 59, tzinfo=datetime.timezone.utc)
        window = get_window_start(dt, period_hours=1)
        assert window == datetime.datetime(
            2026, 6, 3, 14, 0, 0, tzinfo=datetime.timezone.utc
        )

    def test_naive_datetime_treated_as_utc(self) -> None:
        naive = datetime.datetime(2026, 6, 3, 14, 30)
        aware = datetime.datetime(2026, 6, 3, 14, 30, tzinfo=datetime.timezone.utc)
        assert get_window_start(naive, 1) == get_window_start(aware, 1)
