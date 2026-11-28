"""A limit's usage reset counts usage exactly: buckets before the reset day's
bucket drop out, the reset day's bucket counts only what it gained after the
reset (clamped at 0), and a reset from an earlier period changes nothing. A
limit takes its baseline by id: the user's own for a per-user limit, the sum
over the covered users for a pool."""

from datetime import datetime, timedelta, timezone, tzinfo

import pytest

import onyx.server.query_and_chat.token_limit as token_limit
from onyx.configs.constants import TokenRateLimitPeriod, TokenRateLimitScope
from onyx.db.models import TokenRateLimit
from onyx.db.token_limit import UsageBaseline
from onyx.db.user_usage import (
    get_limit_usage_start,
    get_period_window_start,
    get_usage_bucket_start,
    sum_limit_usage,
)
from onyx.server.query_and_chat.token_limit import (
    BudgetUnit,
    WindowUsage,
    budget_windows,
    exhausted_windows,
    resolve_member_allowance,
    usage_cutoff,
)

DAILY = TokenRateLimitPeriod.DAILY
MONTHLY = TokenRateLimitPeriod.MONTHLY
_GROUP_ID = 7
_NOW = datetime(2026, 11, 18, 15, 0, tzinfo=timezone.utc)
_RESET = datetime(2026, 11, 10, 9, 30, tzinfo=timezone.utc)
_RESET_DAY = datetime(2026, 11, 10, tzinfo=timezone.utc)


class _FixedDatetime(datetime):
    @classmethod
    def now(cls, tz: tzinfo | None = None) -> "_FixedDatetime":
        return cls.fromtimestamp(_NOW.timestamp(), tz or timezone.utc)


@pytest.fixture(autouse=True)
def _freeze_clock(monkeypatch: pytest.MonkeyPatch) -> None:
    # exhausted_windows reads the clock; a read across UTC midnight would move
    # the daily window past the reset.
    monkeypatch.setattr(token_limit, "datetime", _FixedDatetime)


def _limit(
    period: TokenRateLimitPeriod,
    cost_budget_cents: float,
    usage_reset_at: datetime | None = None,
    scope: TokenRateLimitScope = TokenRateLimitScope.GLOBAL,
    limit_id: int | None = None,
) -> TokenRateLimit:
    return TokenRateLimit(
        id=limit_id,
        enabled=True,
        cost_budget_cents=cost_budget_cents,
        period=period,
        scope=scope,
        usage_reset_at=usage_reset_at,
    )


def test_usage_start_is_reset_bucket_inside_period() -> None:
    assert get_limit_usage_start(_NOW, MONTHLY, _RESET) == _RESET_DAY
    # A naive reset reads as UTC.
    assert (
        get_limit_usage_start(_NOW, MONTHLY, _RESET.replace(tzinfo=None)) == _RESET_DAY
    )


def test_usage_start_ignores_reset_before_period() -> None:
    month_start = get_period_window_start(_NOW, MONTHLY)
    assert get_limit_usage_start(_NOW, MONTHLY, _RESET - timedelta(days=20)) == (
        month_start
    )
    assert get_limit_usage_start(_NOW, MONTHLY, None) == month_start


def test_reset_day_counts_only_usage_after_reset() -> None:
    buckets = [
        (_RESET_DAY - timedelta(days=1), 50.0),
        (_RESET_DAY, 150.0),
        (_RESET_DAY + timedelta(days=1), 30.0),
    ]
    assert sum_limit_usage(buckets, _NOW, MONTHLY, _RESET, 100.0) == 80.0
    # The reset day's bucket never goes below 0.
    assert sum_limit_usage(buckets, _NOW, MONTHLY, _RESET, 400.0) == 30.0


def test_reset_from_earlier_period_ignores_baseline() -> None:
    buckets = [(get_period_window_start(_NOW, MONTHLY), 70.0)]
    old_reset = get_period_window_start(_NOW, MONTHLY) - timedelta(hours=3)
    assert sum_limit_usage(buckets, _NOW, MONTHLY, old_reset, 500.0) == 70.0


def test_pool_limit_counts_usage_after_reset() -> None:
    today = get_usage_bucket_start(_NOW)
    windows = budget_windows(
        [_limit(DAILY, 100, usage_reset_at=_NOW, limit_id=12)],
        None,
        {12: UsageBaseline(cost_cents=150)},
    )
    assert usage_cutoff(_NOW, windows, BudgetUnit.COST) == today

    assert not exhausted_windows(windows, WindowUsage(cost_cents=[(today, 249.0)]))
    assert exhausted_windows(windows, WindowUsage(cost_cents=[(today, 250.0)]))


def test_per_user_limit_uses_user_baseline() -> None:
    usage = WindowUsage(cost_cents=[(get_usage_bucket_start(_NOW), 150.0)])
    limit = _limit(DAILY, 100, _NOW, TokenRateLimitScope.USER, limit_id=11)

    assert not exhausted_windows(
        budget_windows([limit], None, {11: UsageBaseline(cost_cents=150)}), usage
    )
    # Without the user's baseline the whole reset day counts.
    assert exhausted_windows(budget_windows([limit]), usage)


def test_member_allowance_keeps_chosen_row_reset() -> None:
    group_reset = _NOW - timedelta(minutes=5)
    default_reset = _NOW - timedelta(minutes=10)
    allowance = resolve_member_allowance(
        [
            _limit(DAILY, 100, scope=TokenRateLimitScope.USER, limit_id=1),
            _limit(MONTHLY, 500, default_reset, TokenRateLimitScope.USER, limit_id=2),
        ],
        {
            _GROUP_ID: [
                _limit(
                    DAILY,
                    200,
                    group_reset,
                    TokenRateLimitScope.USER_GROUP_MEMBER,
                    limit_id=3,
                )
            ]
        },
        {3: UsageBaseline(cost_cents=40), 2: UsageBaseline(cost_cents=60)},
    )
    by_period = {window.period: window for window in allowance}
    assert by_period[DAILY].user_group_id == _GROUP_ID
    assert by_period[DAILY].usage_reset_at == group_reset
    assert by_period[DAILY].usage_baseline == 40
    assert by_period[MONTHLY].user_group_id is None
    assert by_period[MONTHLY].usage_reset_at == default_reset
    assert by_period[MONTHLY].usage_baseline == 60
