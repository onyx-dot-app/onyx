import datetime

import pytest
from pydantic import ValidationError

from onyx.configs.constants import TokenRateLimitScope
from onyx.db.models import TokenRateLimit
from onyx.server.query_and_chat.token_limit import _is_rate_limited
from onyx.server.token_rate_limits.models import TokenRateLimitArgs
from onyx.server.token_rate_limits.models import TokenRateLimitDisplay


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
    usage = [(datetime.datetime.now(datetime.UTC), 1_000_000)]

    assert not _is_rate_limited([_rate_limit(None, cost_budget_cents=1.0)], usage)


def test_token_budget_still_enforces_tokens() -> None:
    usage = [(datetime.datetime.now(datetime.UTC), 1_000)]

    assert _is_rate_limited([_rate_limit(1)], usage)


def test_token_rate_limit_args_requires_a_budget() -> None:
    with pytest.raises(
        ValidationError, match="Either token_budget or cost_budget_cents"
    ):
        TokenRateLimitArgs(enabled=True, period_hours=1)


def test_token_rate_limit_display_allows_cost_only_limit() -> None:
    display = TokenRateLimitDisplay.from_db(_rate_limit(None, cost_budget_cents=2.5))

    assert display.token_budget is None
    assert display.cost_budget_cents == 2.5
