"""EE user/group cost-budget paths: legacy stored periods (any whole-day value,
possible on rows written before the daily/weekly/monthly restriction) must be
skipped, and the usage fetch cutoff must cover every valid limit's window."""

from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

import pytest

import ee.onyx.server.query_and_chat.token_limit as ee_token_limit
from onyx.configs.constants import TokenRateLimitScope
from onyx.db.models import TokenRateLimit
from onyx.db.user_usage import get_cost_window_start


class _SessionCtx:
    def __enter__(self) -> object:
        return object()

    def __exit__(self, *args: object) -> None:
        return None


class _FixedDatetime(datetime):
    """2026-08-01 is a Saturday: the weekly window (Mon 07-27) starts before the
    monthly window (08-01), so a max-period cutoff would under-fetch weekly usage."""

    @classmethod
    def now(cls, tz: Any = None) -> "_FixedDatetime":
        return cls(2026, 8, 1, 12, tzinfo=tz or timezone.utc)


def _cost_limit(period_hours: int, cost_budget_cents: float = 100.0) -> TokenRateLimit:
    return TokenRateLimit(
        enabled=True,
        token_budget=None,
        cost_budget_cents=cost_budget_cents,
        period_hours=period_hours,
        scope=TokenRateLimitScope.USER,
    )


def _over_budget_buckets(*_a: object) -> list[tuple[datetime, float]]:
    return [(datetime.now(timezone.utc), 10.0**9)]


def test_user_path_skips_legacy_period(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        ee_token_limit, "get_session_with_current_tenant", lambda: _SessionCtx()
    )
    monkeypatch.setattr(
        ee_token_limit,
        "fetch_all_user_token_rate_limits",
        lambda **_: [_cost_limit(period_hours=2136)],
    )
    monkeypatch.setattr(
        ee_token_limit, "get_user_cost_cents_buckets_since", _over_budget_buckets
    )

    ee_token_limit._user_is_rate_limited(uuid4())  # skipped, no raise


def test_group_path_skips_legacy_period(monkeypatch: pytest.MonkeyPatch) -> None:
    limit = _cost_limit(period_hours=2136)
    limit.scope = TokenRateLimitScope.USER_GROUP
    monkeypatch.setattr(
        ee_token_limit, "get_session_with_current_tenant", lambda: _SessionCtx()
    )
    monkeypatch.setattr(
        ee_token_limit, "fetch_user_group_token_rate_limits", lambda *_: {1: [limit]}
    )
    monkeypatch.setattr(
        ee_token_limit,
        "get_group_cost_cents_buckets_since",
        lambda *_: {1: _over_budget_buckets()},
    )

    ee_token_limit._user_is_rate_limited_by_group(uuid4())  # skipped, no raise


def test_user_path_fetch_cutoff_covers_every_window(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    weekly, monthly = _cost_limit(period_hours=168), _cost_limit(period_hours=720)
    captured: list[datetime] = []

    def _capture_cutoff(
        _db: object, _user: object, cutoff: datetime
    ) -> list[tuple[datetime, float]]:
        captured.append(cutoff)
        return []

    monkeypatch.setattr(ee_token_limit, "datetime", _FixedDatetime)
    monkeypatch.setattr(
        ee_token_limit, "get_session_with_current_tenant", lambda: _SessionCtx()
    )
    monkeypatch.setattr(
        ee_token_limit,
        "fetch_all_user_token_rate_limits",
        lambda **_: [weekly, monthly],
    )
    monkeypatch.setattr(
        ee_token_limit, "get_user_cost_cents_buckets_since", _capture_cutoff
    )

    ee_token_limit._user_is_rate_limited(uuid4())

    now = _FixedDatetime.now(timezone.utc)
    assert captured == [
        min(get_cost_window_start(now, 168), get_cost_window_start(now, 720))
    ]


def test_group_path_fetch_cutoff_covers_every_window(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    weekly, monthly = _cost_limit(period_hours=168), _cost_limit(period_hours=720)
    weekly.scope = TokenRateLimitScope.USER_GROUP
    monthly.scope = TokenRateLimitScope.USER_GROUP
    captured: list[datetime] = []

    def _capture_cutoff(
        _db: object, _group_ids: object, cutoff: datetime
    ) -> dict[int, list[tuple[datetime, float]]]:
        captured.append(cutoff)
        return {}

    monkeypatch.setattr(ee_token_limit, "datetime", _FixedDatetime)
    monkeypatch.setattr(
        ee_token_limit, "get_session_with_current_tenant", lambda: _SessionCtx()
    )
    monkeypatch.setattr(
        ee_token_limit,
        "fetch_user_group_token_rate_limits",
        lambda *_: {1: [weekly, monthly]},
    )
    monkeypatch.setattr(
        ee_token_limit, "get_group_cost_cents_buckets_since", _capture_cutoff
    )

    ee_token_limit._user_is_rate_limited_by_group(uuid4())

    now = _FixedDatetime.now(timezone.utc)
    assert captured == [
        min(get_cost_window_start(now, 168), get_cost_window_start(now, 720))
    ]
