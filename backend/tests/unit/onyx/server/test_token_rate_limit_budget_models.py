import datetime
from unittest.mock import Mock

import pytest
from pydantic import ValidationError

from onyx.configs.constants import TokenRateLimitScope
from onyx.db.models import TokenRateLimit
from onyx.db.token_limit import update_token_rate_limit
from onyx.db.user_usage import TokenUsageBucket
from onyx.error_handling.exceptions import OnyxError
from onyx.server.query_and_chat.token_limit import _token_budget_reset
from onyx.server.token_rate_limits.models import (
    MAX_TOKEN_BUDGET_THOUSANDS,
    TokenRateLimitArgs,
    TokenRateLimitDisplay,
    TokenRateLimitUpdateArgs,
)


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


def test_token_rate_limit_args_rejects_budgets_above_one_trillion() -> None:
    with pytest.raises(ValidationError):
        TokenRateLimitArgs(
            enabled=True,
            token_budget=MAX_TOKEN_BUDGET_THOUSANDS + 1,
            period_hours=24,
        )


def test_token_rate_limit_update_args_accepts_legacy_budget() -> None:
    args = TokenRateLimitUpdateArgs(
        enabled=False,
        token_budget=MAX_TOKEN_BUDGET_THOUSANDS + 1,
        period_hours=24,
    )

    assert args.token_budget == MAX_TOKEN_BUDGET_THOUSANDS + 1


def test_legacy_budget_can_be_toggled_without_increasing_it() -> None:
    legacy_budget = MAX_TOKEN_BUDGET_THOUSANDS + 1
    limit = _rate_limit(legacy_budget)
    limit.id = 7
    session = Mock()
    session.get.return_value = limit

    updated = update_token_rate_limit(
        session,
        7,
        TokenRateLimitUpdateArgs(
            enabled=False,
            token_budget=legacy_budget,
            period_hours=24,
        ),
    )

    assert updated.enabled is False
    session.commit.assert_called_once()


def test_existing_limit_cannot_be_raised_above_one_trillion() -> None:
    limit = _rate_limit(MAX_TOKEN_BUDGET_THOUSANDS)
    limit.id = 7
    session = Mock()
    session.get.return_value = limit

    with pytest.raises(OnyxError):
        update_token_rate_limit(
            session,
            7,
            TokenRateLimitUpdateArgs(
                enabled=True,
                token_budget=MAX_TOKEN_BUDGET_THOUSANDS + 1,
                period_hours=24,
            ),
        )

    session.commit.assert_not_called()


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
