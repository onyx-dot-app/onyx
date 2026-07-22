import datetime

import pytest
from pydantic import ValidationError

from onyx.configs.constants import TokenRateLimitScope
from onyx.db.models import TokenRateLimit
from onyx.db.user_usage import TokenUsageBucket
from onyx.server.query_and_chat.token_limit import _is_rate_limited
from onyx.server.token_rate_limits.models import (
    TokenRateLimitArgs,
    TokenRateLimitDisplay,
)


def _rate_limit(
    token_budget: int | None, cost_budget_cents: float | None = None
) -> TokenRateLimit:
    return TokenRateLimit(
        id=1,
        enabled=True,
        token_budget=token_budget,
        cost_budget_cents=cost_budget_cents,
        period_hours=1,
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


def test_token_rate_limit_args_requires_a_budget() -> None:
    with pytest.raises(
        ValidationError, match="Either token_budget or cost_budget_cents"
    ):
        TokenRateLimitArgs(enabled=True, period_hours=24)


def test_token_rate_limit_args_requires_whole_utc_days() -> None:
    with pytest.raises(ValidationError, match="whole UTC days"):
        TokenRateLimitArgs(enabled=True, token_budget=1, period_hours=25)


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


def test_token_rate_limit_display_allows_cost_only_limit() -> None:
    display = TokenRateLimitDisplay.from_db(_rate_limit(None, cost_budget_cents=2.5))

    assert display.token_budget is None
    assert display.cost_budget_cents == 2.5


def test_token_rate_limit_display_normalizes_legacy_period() -> None:
    display = TokenRateLimitDisplay.from_db(_rate_limit(1))

    assert display.period_hours == 24
