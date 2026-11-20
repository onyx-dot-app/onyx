"""The user budget gauges of the source-API limiter."""

import threading
from collections.abc import Callable
from unittest.mock import MagicMock
from uuid import uuid4

import pytest
from prometheus_client import REGISTRY

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


def _published(source: str) -> tuple[float | None, float | None]:
    budget = REGISTRY.get_sample_value(
        "onyx_source_api_limiter_budget",
        {"source": source, "api": "drive", "scope": "user"},
    )
    cut_users = REGISTRY.get_sample_value(
        "onyx_source_api_limiter_cut_users", {"source": source, "api": "drive"}
    )
    return budget, cut_users


def test_a_refresh_drops_expired_budgets_with_no_new_observation() -> None:
    now = 1000.0
    budgets = source_api_metrics._UserBudgets(clock=lambda: now)
    source = f"test_{uuid4().hex[:8]}"
    budgets.observe(source, "drive", "a", allowed=100, limit=100)
    budgets.observe(source, "drive", "b", allowed=50, limit=100)
    assert _published(source) == (50, 1)

    now += 60
    budgets.observe(source, "drive", "a", allowed=100, limit=100)
    now += USER_BUDGET_RECENT_SECONDS - 30
    budgets.refresh()
    # The cut of user b expired. User a is still recent.
    assert _published(source) == (100, 0)

    now += USER_BUDGET_RECENT_SECONDS
    budgets.refresh()
    assert _published(source) == (None, None)


class _PausingGauge:
    """Runs `on_first_set` in the middle of the first `set`, as a thread
    that another thread interrupts there."""

    def __init__(self, on_first_set: Callable[[], None]) -> None:
        self._on_first_set: Callable[[], None] | None = on_first_set
        self.values: list[float] = []

    def labels(self, **_labels: str) -> "_PausingGauge":
        return self

    def set(self, value: float) -> None:
        on_first_set, self._on_first_set = self._on_first_set, None
        if on_first_set is not None:
            on_first_set()
        self.values.append(value)


def test_an_older_state_does_not_overwrite_a_newer_publication(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    budgets = source_api_metrics._UserBudgets()
    source = f"test_{uuid4().hex[:8]}"
    cut = threading.Thread(target=budgets.observe, args=(source, "drive", "b", 50, 100))

    def observe_a_cut_meanwhile() -> None:
        cut.start()
        # With the publication under the lock, the cut waits for this one.
        cut.join(timeout=0.5)

    gauge = _PausingGauge(observe_a_cut_meanwhile)
    monkeypatch.setattr(source_api_metrics, "LIMITER_BUDGET", gauge)
    monkeypatch.setattr(source_api_metrics, "LIMITER_CUT_USERS", MagicMock())

    budgets.observe(source, "drive", "a", allowed=100, limit=100)
    cut.join()

    # The cut is the newer state, so it is the last value published.
    assert gauge.values == [100, 50]
