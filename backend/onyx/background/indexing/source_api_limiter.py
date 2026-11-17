"""The shared budget for a connector's source API calls, kept in Redis.

Every worker that indexes with the same credential builds a limiter with the
same keys, so they share one budget for each API: a window for the whole
credential (for Google, the GCP project) and a window for each user the
connector acts as. A call waits until it fits both.

The budgets adapt. When the source refuses enough of the recent calls for
its rate, the window that the source named allows less for a time, and then
grows back. A cut of one user's window does not slow other users.

Each budget is for a period (a minute for Google), but the window that
enforces it is shorter, with the same rate. A window of the whole period lets
the full budget go in one burst, and then lets requests in only as the burst
leaves the window. The source then sees bursts and stops, not a steady rate.
"""

import math
import time
from collections.abc import Callable

from pydantic import BaseModel
from typing_extensions import override

from onyx.configs.app_configs import (
    ENABLE_SOURCE_API_LIMITER,
    GOOGLE_DOCS_READS_PER_PROJECT,
    GOOGLE_DOCS_READS_PER_USER,
    GOOGLE_DRIVE_QUOTA_MODEL,
    GOOGLE_DRIVE_QUOTA_PER_PROJECT,
    GOOGLE_DRIVE_QUOTA_PER_USER,
)
from onyx.configs.constants import DocumentSource
from onyx.connectors.google_drive.quota import DriveQuotaApi
from onyx.connectors.interfaces import SourceApiLimiter
from onyx.connectors.models import ConnectorStopSignal
from onyx.redis.redis_pool import get_redis_client
from onyx.redis.redis_rate_window import RateWindow, RedisRateWindows
from onyx.server.metrics.source_api_metrics import (
    LimiterScope,
    allowed_units,
    observe_user_budget,
    record_limiter_cut,
    record_limiter_wait,
    set_project_budget,
)
from onyx.utils.logger import setup_logger
from shared_configs.contextvars import get_current_tenant_id

logger = setup_logger()

_KEY_PREFIX = "source_api_limit"
# The longest single sleep, so that a waiting call sees a stop signal soon.
_STOP_CHECK_INTERVAL_SECONDS = 5.0
# A call that waited this long goes on with no slot. The source's own answer
# then decides, and the connector's retries handle a refusal.
MAX_WAIT_SECONDS = 300.0


class SourceApiBudget(BaseModel):
    """The limits of one API for one period. None is no limit."""

    per_credential: int | None = None
    per_user: int | None = None
    period_seconds: float = 60.0
    # The window that enforces the limits, at the same rate. None is the whole
    # period.
    window_seconds: float | None = None
    # True when the source counts requests, so a call costs its number of
    # requests whatever cost the connector gives.
    count_requests: bool = False


class RedisSourceApiLimiter(SourceApiLimiter):
    def __init__(
        self,
        tenant_id: str,
        credential_key: str,
        budgets: dict[str, SourceApiBudget],
        should_stop: Callable[[], bool] | None = None,
        *,
        source: DocumentSource,
    ) -> None:
        self._source = source.value
        self._prefix = f"{_KEY_PREFIX}:{credential_key}"
        self._budgets = budgets
        self._should_stop = should_stop
        self._windows = RedisRateWindows(get_redis_client(tenant_id=tenant_id))

    def credential_window(self, api: str) -> RateWindow | None:
        budget = self._budgets.get(api)
        if budget is None or budget.per_credential is None:
            return None
        return _window(f"{self._prefix}:{api}:all", budget.per_credential, budget)

    def user_window(self, api: str, user: str | None) -> RateWindow | None:
        budget = self._budgets.get(api)
        if budget is None or budget.per_user is None or user is None:
            return None
        return _window(
            f"{self._prefix}:{api}:user:{user.lower()}", budget.per_user, budget
        )

    def try_acquire(
        self, api: str, cost: int, user: str | None = None, request_count: int = 1
    ) -> float:
        """Takes the call's units and returns 0, or returns the seconds until
        a full window has room."""
        budget = self._budgets.get(api)
        if budget is None:
            return 0
        credential_window = self.credential_window(api)
        user_window = self.user_window(api, user)
        windows = [w for w in (credential_window, user_window) if w is not None]
        result = self._windows.try_acquire_with_shares(
            windows, request_count if budget.count_requests else cost, request_count
        )
        # No shares when Redis cannot be reached.
        if result.shares:
            for window, share in zip(windows, result.shares, strict=True):
                self._record_budget(api, window, share, window is user_window)
        return result.wait_seconds

    def _record_budget(
        self, api: str, window: RateWindow, share: float, user_scope: bool
    ) -> None:
        # The metrics show the budget of the whole period, as configured.
        budget = self._budgets[api]
        limit = budget.per_user if user_scope else budget.per_credential
        if limit is None:
            return
        allowed = allowed_units(limit, share)
        if user_scope:
            observe_user_budget(self._source, api, window.key, allowed, limit)
        else:
            set_project_budget(self._source, api, allowed)

    @override
    def acquire(
        self, api: str, cost: int, user: str | None = None, request_count: int = 1
    ) -> None:
        started = time.monotonic()
        slept = 0.0
        try:
            while (wait := self.try_acquire(api, cost, user, request_count)) > 0:
                self._check_stop()
                waited = time.monotonic() - started
                if waited >= MAX_WAIT_SECONDS:
                    logger.warning(
                        "A %s call waited %.0fs for the shared budget; it goes "
                        "on with no slot.",
                        api,
                        waited,
                    )
                    return
                sleep = min(
                    wait, _STOP_CHECK_INTERVAL_SECONDS, MAX_WAIT_SECONDS - waited
                )
                time.sleep(sleep)
                slept += sleep
            # A stop during the last sleep ends the call before its request.
            if slept > 0:
                self._check_stop()
        finally:
            record_limiter_wait(self._source, api, slept)

    def _check_stop(self) -> None:
        if self._should_stop is not None and self._should_stop():
            raise ConnectorStopSignal("Stop signal while waiting for the API budget")

    @override
    def report_rate_limit(
        self, api: str, user: str | None, user_scope: bool, count: int = 1
    ) -> None:
        window = (
            self.user_window(api, user) if user_scope else self.credential_window(api)
        )
        if window is None:
            return
        result = self._windows.report_refusals(window, count)
        if not result.applied:
            return
        record_limiter_cut(
            self._source,
            api,
            LimiterScope.USER if user_scope else LimiterScope.PROJECT,
        )
        self._record_budget(api, window, result.share, user_scope)
        logger.info(
            "%s refused %.1f%% of the recent calls for its rate (%s); the shared "
            "budget %s is cut%s to %.0f%% of its limit.",
            api,
            result.refused_share * 100,
            "user" if user_scope else "credential",
            window.key,
            " hard" if result.hard else "",
            result.share * 100,
        )


def _window(key: str, limit: int, budget: SourceApiBudget) -> RateWindow:
    """The window that enforces ``limit`` for the budget's period."""
    if budget.window_seconds is None or budget.window_seconds >= budget.period_seconds:
        return RateWindow(key=key, limit=limit, period_seconds=budget.period_seconds)
    return RateWindow(
        key=key,
        limit=max(1, math.floor(limit * budget.window_seconds / budget.period_seconds)),
        period_seconds=budget.window_seconds,
    )


# Google's quotas are for one minute. A window of 10 seconds keeps the rate
# steady; see the module docstring.
_GOOGLE_WINDOW_SECONDS = 10.0

# The budgets of Google's Drive and Docs quotas, from the configuration.
GOOGLE_DRIVE_BUDGETS: dict[str, SourceApiBudget] = {
    DriveQuotaApi.DRIVE.value: SourceApiBudget(
        per_credential=GOOGLE_DRIVE_QUOTA_PER_PROJECT,
        per_user=GOOGLE_DRIVE_QUOTA_PER_USER,
        count_requests=GOOGLE_DRIVE_QUOTA_MODEL == "requests",
        window_seconds=_GOOGLE_WINDOW_SECONDS,
    ),
    DriveQuotaApi.DOCS.value: SourceApiBudget(
        per_credential=GOOGLE_DOCS_READS_PER_PROJECT,
        per_user=GOOGLE_DOCS_READS_PER_USER,
        window_seconds=_GOOGLE_WINDOW_SECONDS,
    ),
}


def build_source_api_limiter(
    source: DocumentSource,
    credential_id: int,
    should_stop: Callable[[], bool] | None = None,
) -> SourceApiLimiter | None:
    """The shared limiter for a connector of ``source`` that uses the
    credential, or None when the source has no budgets or the limiter is off.
    Connectors that share a credential share its budgets. A call that waits
    for its budget ends with ConnectorStopSignal when ``should_stop`` turns
    true."""
    if not ENABLE_SOURCE_API_LIMITER or source != DocumentSource.GOOGLE_DRIVE:
        return None
    return RedisSourceApiLimiter(
        tenant_id=get_current_tenant_id(),
        credential_key=f"{source.value}:{credential_id}",
        budgets=GOOGLE_DRIVE_BUDGETS,
        should_stop=should_stop,
        source=source,
    )
