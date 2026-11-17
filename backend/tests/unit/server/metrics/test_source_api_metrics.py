"""The user budget gauges of the source-API limiter."""

from uuid import uuid4

from onyx.server.metrics import source_api_metrics
from onyx.server.metrics.source_api_metrics import (
    LIMITER_BUDGET,
    LIMITER_CUT_USERS,
    USER_BUDGET_RECENT_SECONDS,
)


def _user_gauges(source: str) -> tuple[float, float]:
    budget = LIMITER_BUDGET.labels(source=source, api="drive", scope="user")
    cut_users = LIMITER_CUT_USERS.labels(source=source, api="drive")
    return budget._value.get(), cut_users._value.get()


def test_the_user_gauges_show_the_lowest_budget_and_the_cut_users() -> None:
    now = 1000.0
    budgets = source_api_metrics._UserBudgets(clock=lambda: now)
    # A unique source keeps other tests' series apart.
    source = f"test_{uuid4().hex[:8]}"

    budgets.observe(source, "drive", "a", allowed=100, limit=100)
    budgets.observe(source, "drive", "b", allowed=100, limit=100)
    assert _user_gauges(source) == (100, 0)

    # A cut publishes at once.
    budgets.observe(source, "drive", "b", allowed=50, limit=100)
    assert _user_gauges(source) == (50, 1)

    # The user recovers.
    now += 10
    budgets.observe(source, "drive", "b", allowed=100, limit=100)
    assert _user_gauges(source) == (100, 0)

    # A user that was not used recently no longer counts.
    budgets.observe(source, "drive", "b", allowed=25, limit=100)
    now += USER_BUDGET_RECENT_SECONDS + 1
    budgets.observe(source, "drive", "a", allowed=100, limit=100)
    assert _user_gauges(source) == (100, 0)
