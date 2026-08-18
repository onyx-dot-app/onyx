"""EE cost-budget paths skip unsupported periods and fetch every valid window."""

from datetime import datetime, timezone, tzinfo
from uuid import uuid4

import pytest

import ee.onyx.server.query_and_chat.token_limit as ee_token_limit
from onyx.configs.constants import TokenRateLimitScope
from onyx.db.models import TokenRateLimit


class _SessionCtx:
    def __enter__(self) -> object:
        return object()

    def __exit__(self, *args: object) -> None:
        return None


@pytest.fixture(autouse=True)
def _stub_session(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        ee_token_limit, "get_session_with_current_tenant", lambda: _SessionCtx()
    )


class _FixedDatetime(datetime):
    """The fixed month starts on Saturday, after the weekly window starts."""

    @classmethod
    def now(cls, tz: tzinfo | None = None) -> "_FixedDatetime":
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
        ee_token_limit,
        "fetch_all_user_token_rate_limits",
        lambda **_: [weekly, monthly],
    )
    monkeypatch.setattr(
        ee_token_limit, "get_user_cost_cents_buckets_since", _capture_cutoff
    )

    ee_token_limit._user_is_rate_limited(uuid4())

    assert captured == [datetime(2026, 7, 27, tzinfo=timezone.utc)]


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
        ee_token_limit,
        "fetch_user_group_token_rate_limits",
        lambda *_: {1: [weekly, monthly]},
    )
    monkeypatch.setattr(
        ee_token_limit, "get_group_cost_cents_buckets_since", _capture_cutoff
    )

    ee_token_limit._user_is_rate_limited_by_group(uuid4())

    assert captured == [datetime(2026, 7, 27, tzinfo=timezone.utc)]
