"""The shared budget for a connector's source API calls, kept in Redis.

Every worker that indexes with the same credential builds a limiter with the
same keys, so they share one budget for each API: a window for the whole
credential (for Google, the GCP project) and a window for each user the
connector acts as. A call waits until it fits both.

The budgets adapt. When the source refuses a call for its rate, the window
that the source named allows half as much for a time, and then grows back.
A cut of one user's window does not slow other users.
"""

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
    # True when the source counts requests, so each call costs 1 whatever
    # cost the connector gives.
    count_requests: bool = False


class RedisSourceApiLimiter(SourceApiLimiter):
    def __init__(
        self,
        tenant_id: str,
        credential_key: str,
        budgets: dict[str, SourceApiBudget],
        should_stop: Callable[[], bool] | None = None,
    ) -> None:
        self._prefix = f"{_KEY_PREFIX}:{credential_key}"
        self._budgets = budgets
        self._should_stop = should_stop
        self._windows = RedisRateWindows(get_redis_client(tenant_id=tenant_id))

    def credential_window(self, api: str) -> RateWindow | None:
        budget = self._budgets.get(api)
        if budget is None or budget.per_credential is None:
            return None
        return RateWindow(
            key=f"{self._prefix}:{api}:all",
            limit=budget.per_credential,
            period_seconds=budget.period_seconds,
        )

    def user_window(self, api: str, user: str | None) -> RateWindow | None:
        budget = self._budgets.get(api)
        if budget is None or budget.per_user is None or user is None:
            return None
        return RateWindow(
            key=f"{self._prefix}:{api}:user:{user.lower()}",
            limit=budget.per_user,
            period_seconds=budget.period_seconds,
        )

    def _windows_for(self, api: str, user: str | None) -> list[RateWindow]:
        windows = [self.credential_window(api), self.user_window(api, user)]
        return [window for window in windows if window is not None]

    def try_acquire(self, api: str, cost: int, user: str | None = None) -> float:
        """Takes the call's units and returns 0, or returns the seconds until
        a full window has room."""
        budget = self._budgets.get(api)
        if budget is None:
            return 0
        return self._windows.try_acquire(
            self._windows_for(api, user), 1 if budget.count_requests else cost
        )

    @override
    def acquire(self, api: str, cost: int, user: str | None = None) -> None:
        started = time.monotonic()
        while (wait := self.try_acquire(api, cost, user)) > 0:
            waited = time.monotonic() - started
            if waited >= MAX_WAIT_SECONDS:
                logger.warning(
                    "A %s call waited %.0fs for the shared budget; it goes on "
                    "with no slot.",
                    api,
                    waited,
                )
                return
            if self._should_stop is not None and self._should_stop():
                raise ConnectorStopSignal(
                    "Stop signal while waiting for the API budget"
                )
            time.sleep(
                min(wait, _STOP_CHECK_INTERVAL_SECONDS, MAX_WAIT_SECONDS - waited)
            )

    @override
    def report_rate_limit(self, api: str, user: str | None, user_scope: bool) -> None:
        window = (
            self.user_window(api, user) if user_scope else self.credential_window(api)
        )
        if window is None:
            return
        share = self._windows.cut(window)
        logger.info(
            "%s refused a call for its rate (%s); the shared budget %s is at "
            "%.0f%% of its limit.",
            api,
            "user" if user_scope else "credential",
            window.key,
            share * 100,
        )


def google_drive_budgets() -> dict[str, SourceApiBudget]:
    """The budgets of Google's Drive and Docs quotas, from the configuration."""
    return {
        DriveQuotaApi.DRIVE.value: SourceApiBudget(
            per_credential=GOOGLE_DRIVE_QUOTA_PER_PROJECT,
            per_user=GOOGLE_DRIVE_QUOTA_PER_USER,
            count_requests=GOOGLE_DRIVE_QUOTA_MODEL == "requests",
        ),
        DriveQuotaApi.DOCS.value: SourceApiBudget(
            per_credential=GOOGLE_DOCS_READS_PER_PROJECT,
            per_user=GOOGLE_DOCS_READS_PER_USER,
        ),
    }


def build_source_api_limiter(
    source: DocumentSource, credential_id: int
) -> SourceApiLimiter | None:
    """The shared limiter for a connector of ``source`` that uses the
    credential, or None when the source has no budgets or the limiter is off.
    Connectors that share a credential share its budgets."""
    if not ENABLE_SOURCE_API_LIMITER or source != DocumentSource.GOOGLE_DRIVE:
        return None
    return RedisSourceApiLimiter(
        tenant_id=get_current_tenant_id(),
        credential_key=f"{source.value}:{credential_id}",
        budgets=google_drive_budgets(),
    )
