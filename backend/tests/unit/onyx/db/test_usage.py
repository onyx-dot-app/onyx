"""Unit tests for the usage periods and the limit check in onyx.db.usage. The
reads and adds against Postgres are in
tests/external_dependency_unit/db/test_tenant_usage_counter.py."""

from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest
from pydantic import ValidationError

from onyx.db.enums import WindowAnchor
from onyx.db.usage import (
    UsageLimitExceededError,
    UsagePeriod,
    UsageType,
    check_usage_limit,
    current_calendar_period,
)

_MONDAY = datetime(2026, 11, 23, tzinfo=timezone.utc)


class TestCurrentCalendarPeriod:
    def test_is_the_week_from_monday(self) -> None:
        wednesday = datetime(2026, 11, 25, 14, 7, tzinfo=timezone.utc)
        assert current_calendar_period(wednesday) == UsagePeriod(
            anchor=WindowAnchor.CALENDAR,
            start=_MONDAY,
            end=_MONDAY + timedelta(days=7),
        )

    def test_the_end_instant_starts_the_next_period(self) -> None:
        next_monday = _MONDAY + timedelta(days=7)
        assert current_calendar_period(next_monday).start == next_monday


class TestUsagePeriod:
    def test_a_period_may_never_end(self) -> None:
        assert UsagePeriod(anchor=WindowAnchor.CALENDAR, start=_MONDAY).end is None

    @pytest.mark.parametrize("end", [_MONDAY, _MONDAY - timedelta(seconds=1)])
    def test_must_end_after_it_starts(self, end: datetime) -> None:
        with pytest.raises(ValidationError):
            UsagePeriod(anchor=WindowAnchor.CALENDAR, start=_MONDAY, end=end)

    def test_needs_timezone_aware_times(self) -> None:
        with pytest.raises(ValidationError):
            UsagePeriod(
                anchor=WindowAnchor.CALENDAR,
                start=datetime(2026, 11, 23),  # noqa: DTZ001 - the case under test
            )


class TestCheckUsageLimit:
    @pytest.mark.parametrize(
        ("used", "pending", "over"),
        [(50.0, 0, False), (100.0, 0, False), (100.5, 0, True), (99.0, 2, True)],
    )
    def test_raises_only_when_over(self, used: float, pending: int, over: bool) -> None:
        with patch("onyx.db.usage.get_usage", return_value=used):
            if over:
                with pytest.raises(UsageLimitExceededError) as exc_info:
                    check_usage_limit(
                        MagicMock(), UsageType.LLM_COST, 100, pending_amount=pending
                    )
                assert exc_info.value.current == used + pending
                assert exc_info.value.limit == 100.0
            else:
                check_usage_limit(
                    MagicMock(), UsageType.LLM_COST, 100, pending_amount=pending
                )

    def test_reads_the_given_period(self) -> None:
        period = UsagePeriod(anchor=WindowAnchor.CALENDAR, start=_MONDAY)
        with patch("onyx.db.usage.get_usage", return_value=0.0) as get_usage:
            check_usage_limit(MagicMock(), UsageType.API_CALLS, 10, period=period)
        assert get_usage.call_args.args[2] == period

    def test_defaults_to_the_current_calendar_period(self) -> None:
        with patch("onyx.db.usage.get_usage", return_value=0.0) as get_usage:
            check_usage_limit(MagicMock(), UsageType.API_CALLS, 10)
        assert get_usage.call_args.args[2] == current_calendar_period()


def test_error_message_names_the_usage_type_and_values() -> None:
    error = UsageLimitExceededError(UsageType.LLM_COST, current=150.5, limit=100.0)
    assert "llm_cost_cents" in str(error)
    assert "150.5" in str(error)
    assert error.usage_type == UsageType.LLM_COST
