"""Prometheus metrics for the requests that a connector sends to a source API,
and for the shared limiter that paces them.

Labels are low cardinality. ``source`` is a ``DocumentSource`` value, ``api``
is a fixed API name of the source (for Google: drive, docs, forms, admin),
``outcome`` is a ``RequestOutcome`` and ``scope`` is a ``LimiterScope``. No
label carries a user or a file: the per-user budgets are aggregated.
"""

import math
import threading
import time
from collections.abc import Callable
from enum import Enum

from prometheus_client import Counter, Gauge


class RequestOutcome(str, Enum):
    OK = "ok"
    # 429, or a 403 that the source uses for a rate limit.
    RATE_LIMITED = "rate_limited"
    # Any other 4xx, and a refused token.
    DENIED = "denied"
    SERVER_ERROR = "server_error"
    # No answer: a lost connection or a timeout.
    NETWORK_ERROR = "network_error"


class LimiterScope(str, Enum):
    # The budget of the whole credential, for Google the GCP project.
    PROJECT = "project"
    # The budget of each user that the connector acts as.
    USER = "user"


SOURCE_API_REQUESTS = Counter(
    "onyx_source_api_requests_total",
    "Requests sent to a source API, by outcome. Each try of a retried request counts.",
    ["source", "api", "outcome"],
)

LIMITER_BUDGET = Gauge(
    "onyx_source_api_limiter_budget",
    "Units that the shared limiter allows in one window now. For scope user, "
    "the lowest budget of the users that this process used recently.",
    ["source", "api", "scope"],
)

LIMITER_CUT_USERS = Gauge(
    "onyx_source_api_limiter_cut_users",
    "Users that this process used recently whose budget is below its limit",
    ["source", "api"],
)

LIMITER_CUTS = Counter(
    "onyx_source_api_limiter_cuts_total",
    "Times the shared limiter cut a budget after the source refused a share of "
    "the recent requests for its rate",
    ["source", "api", "scope"],
)

LIMITER_WAIT_SECONDS = Counter(
    "onyx_source_api_limiter_wait_seconds_total",
    "Time that callers waited for the shared limiter",
    ["source", "api"],
)

# A user budget counts toward the user gauges for this long after its last use.
USER_BUDGET_RECENT_SECONDS = 120.0
# The user gauges are computed again at most once in this interval.
_USER_GAUGE_INTERVAL_SECONDS = 1.0


def record_source_api_request(
    source: str, api: str, outcome: RequestOutcome, count: int = 1
) -> None:
    SOURCE_API_REQUESTS.labels(source=source, api=api, outcome=outcome.value).inc(count)


def record_limiter_cut(source: str, api: str, scope: LimiterScope) -> None:
    LIMITER_CUTS.labels(source=source, api=api, scope=scope.value).inc()


def record_limiter_wait(source: str, api: str, seconds: float) -> None:
    if seconds > 0:
        LIMITER_WAIT_SECONDS.labels(source=source, api=api).inc(seconds)


def allowed_units(limit: int, share: float) -> int:
    """The units a window allows at ``share`` of its ``limit``."""
    return math.floor(limit * share)


def set_project_budget(source: str, api: str, allowed: int) -> None:
    LIMITER_BUDGET.labels(source=source, api=api, scope=LimiterScope.PROJECT.value).set(
        allowed
    )


class _UserBudgets:
    """The latest budget of each user, so that the user gauges show the
    lowest budget and the number of cut users with no label for each user."""

    def __init__(self, clock: Callable[[], float] = time.monotonic) -> None:
        self._clock = clock
        self._lock = threading.Lock()
        # (source, api) -> user key -> (allowed, limit, last use)
        self._budgets: dict[tuple[str, str], dict[str, tuple[int, int, float]]] = {}
        self._published_at: dict[tuple[str, str], float] = {}

    def observe(
        self, source: str, api: str, user_key: str, allowed: int, limit: int
    ) -> None:
        now = self._clock()
        key = (source, api)
        with self._lock:
            budgets = self._budgets.setdefault(key, {})
            previous = budgets.get(user_key)
            budgets[user_key] = (allowed, limit, now)
            changed = previous is None or previous[:2] != (allowed, limit)
            # A change publishes at once, so a cut shows in the next scrape.
            if (
                not changed
                and now - self._published_at.get(key, -math.inf)
                < _USER_GAUGE_INTERVAL_SECONDS
            ):
                return
            self._published_at[key] = now
            recent = {
                user: budget
                for user, budget in budgets.items()
                if now - budget[2] <= USER_BUDGET_RECENT_SECONDS
            }
            self._budgets[key] = recent
            lowest = min(budget[0] for budget in recent.values())
            cut_users = sum(1 for budget in recent.values() if budget[0] < budget[1])
            # Publish under the lock, so an older observation cannot overwrite
            # a newer one.
            LIMITER_BUDGET.labels(
                source=source, api=api, scope=LimiterScope.USER.value
            ).set(lowest)
            LIMITER_CUT_USERS.labels(source=source, api=api).set(cut_users)


_user_budgets = _UserBudgets()


def observe_user_budget(
    source: str, api: str, user_key: str, allowed: int, limit: int
) -> None:
    """Records the budget of one user. ``user_key`` stays in this process: no
    metric label carries it."""
    _user_budgets.observe(source, api, user_key, allowed, limit)
