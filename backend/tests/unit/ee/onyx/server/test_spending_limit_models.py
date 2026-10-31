import datetime

import pytest
from pydantic import ValidationError

from ee.onyx.server.spending_limits.models import (
    MAX_TOKEN_BUDGET_THOUSANDS,
    SpendingLimitCardRequest,
    SpendingLimitRequest,
)
from onyx.configs.constants import (
    TokenRateLimitAction,
    TokenRateLimitPeriod,
    TokenRateLimitScope,
)
from onyx.db.models import TokenRateLimit
from onyx.db.user_usage import TokenUsageBucket
from onyx.server.query_and_chat.token_limit import _token_budget_reset


def _is_rate_limited(
    rate_limits: list[TokenRateLimit],
    usage: list[TokenUsageBucket],
) -> bool:
    return _token_budget_reset(rate_limits, usage) is not None


def _rate_limit(
    token_budget: int | None, cost_budget_cents: float | None = None
) -> TokenRateLimit:
    return TokenRateLimit(
        id=1,
        enabled=True,
        token_budget=token_budget,
        cost_budget_cents=cost_budget_cents,
        period=TokenRateLimitPeriod.DAILY,
        scope=TokenRateLimitScope.GLOBAL,
    )


def test_cost_only_rate_limit_skips_token_enforcement() -> None:
    usage = [
        TokenUsageBucket(
            window_start=datetime.datetime.now(datetime.UTC), tokens=1_000_000
        )
    ]

    assert not _is_rate_limited([_rate_limit(None, cost_budget_cents=1.0)], usage)


def test_token_budget_still_enforces_tokens() -> None:
    usage = [
        TokenUsageBucket(window_start=datetime.datetime.now(datetime.UTC), tokens=1_000)
    ]

    assert _is_rate_limited([_rate_limit(1)], usage)


def test_spending_limit_requires_a_budget() -> None:
    with pytest.raises(ValidationError, match="Set a token budget, a cost budget"):
        SpendingLimitRequest(period=TokenRateLimitPeriod.DAILY)


def test_spending_limit_rejects_unknown_period() -> None:
    with pytest.raises(ValidationError):
        SpendingLimitRequest.model_validate({"token_budget": 1, "period": "HOURLY"})


def test_spending_limit_rejects_budgets_above_one_trillion() -> None:
    with pytest.raises(ValidationError):
        SpendingLimitRequest(
            token_budget=MAX_TOKEN_BUDGET_THOUSANDS + 1,
            period=TokenRateLimitPeriod.DAILY,
        )


def test_percentage_is_only_for_alert_only_limits() -> None:
    alert = SpendingLimitRequest(
        period=TokenRateLimitPeriod.DAILY,
        action=TokenRateLimitAction.ALERT_ONLY,
        threshold_percent=80,
    )
    assert alert.threshold_percent == 80

    with pytest.raises(ValidationError, match="Only an alert-only limit"):
        SpendingLimitRequest(period=TokenRateLimitPeriod.DAILY, threshold_percent=80)
    with pytest.raises(ValidationError, match="not both"):
        SpendingLimitRequest(
            period=TokenRateLimitPeriod.DAILY,
            action=TokenRateLimitAction.ALERT_ONLY,
            threshold_percent=80,
            cost_budget_cents=100,
        )


def test_card_rejects_two_limits_for_one_bucket() -> None:
    limit = {"period": "DAILY", "cost_budget_cents": 100}
    with pytest.raises(ValidationError, match="only one limit of each kind"):
        SpendingLimitCardRequest.model_validate(
            {"enabled": True, "limits": [limit, {**limit, "token_budget": 5}]}
        )


def test_token_rate_limit_uses_current_utc_day() -> None:
    now = datetime.datetime.now(datetime.UTC)
    current_day = now.replace(hour=0, minute=0, second=0, microsecond=0)
    previous_day = current_day - datetime.timedelta(days=1)
    limit = _rate_limit(1)

    assert _is_rate_limited(
        [limit], [TokenUsageBucket(window_start=current_day, tokens=1_000)]
    )
    assert not _is_rate_limited(
        [limit], [TokenUsageBucket(window_start=previous_day, tokens=1_000)]
    )
