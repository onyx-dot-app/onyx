"""EE cost-budget paths fetch usage far enough back to cover every period window."""

from datetime import datetime, timezone, tzinfo
from uuid import uuid4

import pytest

import ee.onyx.server.query_and_chat.token_limit as ee_token_limit
from onyx.configs.constants import TokenRateLimitPeriod, TokenRateLimitScope
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


def _cost_limit(
    period: TokenRateLimitPeriod, cost_budget_cents: float = 100.0
) -> TokenRateLimit:
    return TokenRateLimit(
        enabled=True,
        token_budget=None,
        cost_budget_cents=cost_budget_cents,
        period=period,
        scope=TokenRateLimitScope.USER,
    )


def test_user_path_fetch_cutoff_covers_every_window(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    weekly = _cost_limit(TokenRateLimitPeriod.WEEKLY)
    monthly = _cost_limit(TokenRateLimitPeriod.MONTHLY)
    captured: list[datetime] = []

    def _capture_cutoff(
        _db: object, _user: object, cutoff: datetime, _model: int | None
    ) -> list[tuple[datetime, float]]:
        captured.append(cutoff)
        return []

    monkeypatch.setattr(ee_token_limit, "datetime", _FixedDatetime)
    monkeypatch.setattr(
        ee_token_limit,
        "fetch_enforced_token_rate_limits",
        lambda *_: [weekly, monthly],
    )
    monkeypatch.setattr(
        ee_token_limit, "fetch_user_group_enforced_token_rate_limits", lambda *_: {}
    )
    monkeypatch.setattr(
        ee_token_limit, "get_user_cost_cents_buckets_since", _capture_cutoff
    )

    ee_token_limit._user_is_rate_limited(uuid4(), None)

    assert captured == [datetime(2026, 7, 27, tzinfo=timezone.utc)]


def test_group_path_fetch_cutoff_covers_every_window(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    weekly = _cost_limit(TokenRateLimitPeriod.WEEKLY)
    monthly = _cost_limit(TokenRateLimitPeriod.MONTHLY)
    weekly.scope = TokenRateLimitScope.USER_GROUP
    monthly.scope = TokenRateLimitScope.USER_GROUP
    captured: list[datetime] = []

    def _capture_cutoff(
        _db: object, _group_ids: object, cutoff: datetime, _model: int | None
    ) -> dict[int, list[tuple[datetime, float]]]:
        captured.append(cutoff)
        return {}

    monkeypatch.setattr(ee_token_limit, "datetime", _FixedDatetime)
    monkeypatch.setattr(
        ee_token_limit,
        "fetch_user_group_enforced_token_rate_limits",
        lambda *_: {1: [weekly, monthly]},
    )
    monkeypatch.setattr(
        ee_token_limit, "get_group_cost_cents_buckets_since", _capture_cutoff
    )

    ee_token_limit._user_is_rate_limited_by_group(uuid4(), None)

    assert captured == [datetime(2026, 7, 27, tzinfo=timezone.utc)]
