"""The shared budget for a connector's source API calls, kept in Redis.

Every worker that indexes with the same credential builds a limiter with the
same keys, so they share one budget for each API: a window for the whole
credential (for Google, the GCP project) and a window for each user the
connector acts as. A call waits until it fits both.

The budgets adapt. When the source refuses enough of the recent calls for
its rate, the window that the source named allows less for a time, and then
grows back. A cut of one user's window does not slow other users. A refusal
of a call that took its slot before the last cut does not count toward the
next cut, so the limiter remembers each window's epoch for the calls of this
thread. Report a refusal from the thread that acquired the call's slot.

Waiting calls take turns. Bulk calls (the content reads of conversion) go
after the other calls, such as listing and permission sync, so a few of those
do not starve behind many conversion threads. The calls of one class go in
the order they came.

The calls of one process wait at a gate: one for each credential, API and
class. Only the call at the head of a gate talks to Redis and holds a place
in its queues, so Redis sees about one waiter for each process and class,
not one for each thread. The head sleeps until Redis says that its slot is
due. When it takes its slot, the next call of the gate becomes the head and
gets a new place at the back of the Redis queue, so the processes take turns.
A head that only its user's windows block waits alone, so that one user's
cut does not hold up the other users of the process.

A credential window keeps its share past a run (see redis_rate_window). A new
run starts from the share that the source accepted before, or from a
conservative start share, and not at the full budget. It grows slowly from
either share.

A limiter can also have a pause, which several limiters can share. When the
source answers with a wait time (Retry-After), the caller reports it, and
every call of every worker that reads the pause waits until it ends. The
Microsoft limiters use it: Microsoft asks that all the threads of an app stop
for that time.

Each budget is for a period (a minute for Google), but the window that
enforces it is shorter, with the same rate. A window of the whole period lets
the full budget go in one burst, and then lets requests in only as the burst
leaves the window. The source then sees bursts and stops, not a steady rate.
One request always fits an empty window, so a request larger than the short
window's share could pass the budget of the period. A second window of the
whole period, with the full budget, stops that.
"""

import hashlib
import math
import threading
import time
from collections import deque
from collections.abc import Callable
from typing import Any
from uuid import uuid4

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
from onyx.connectors.credential_families import (
    MICROSOFT_GRAPH_SOURCES,
    microsoft_app_identity,
)
from onyx.connectors.google_drive.quota import DriveQuotaApi
from onyx.connectors.interfaces import SourceApiLimiter
from onyx.connectors.microsoft_utils.config import (
    RU_PER_DAY_FACTOR,
    configured_ru_per_minute,
)
from onyx.connectors.microsoft_utils.request_pacer import (
    DOWNLOAD_LIMITER_API,
    GRAPH_LIMITER_API,
)
from onyx.connectors.models import ConnectorStopSignal

# no-direct-redis: allow the budget is shared by every indexing and sync worker
from onyx.redis.redis_pool import get_redis_client
from onyx.redis.redis_rate_window import (
    WAITER_STALE_SECONDS,
    AcquireResult,
    RateWindow,
    RedisRateWindows,
    WaitTurn,
    WindowStart,
)
from onyx.server.metrics.source_api_metrics import (
    LimiterScope,
    add_local_waiters,
    allowed_units,
    observe_user_budget,
    record_late_refusals,
    record_limiter_cut,
    record_limiter_overdraft,
    record_limiter_pause,
    record_limiter_paused_seconds,
    record_limiter_units,
    record_limiter_wait,
    set_project_budget,
    set_project_ceiling,
    set_redis_waiters,
)
from onyx.utils.logger import setup_logger
from shared_configs.contextvars import get_current_tenant_id

logger = setup_logger()

_KEY_PREFIX = "source_api_limit"
# The longest single sleep, so that a waiting call sees a stop signal soon.
_STOP_CHECK_INTERVAL_SECONDS = 5.0
# A call that waited this long takes its units over the budget. Calls take
# turns, so this happens only when the queue is far longer than the budget
# can serve in this time. The source's own answer then decides, and the
# connector's retries handle a refusal.
MAX_WAIT_SECONDS = 300.0
# A head that waits tries again at least this often, so that its place in the
# Redis queue does not go stale.
_REFRESH_SECONDS = WAITER_STALE_SECONDS / 2
# A call that waits for the budget of the day tries again this often.
_DAY_RETRY_SECONDS = 60.0


def _key_for_log(source: str, key: str) -> str:
    """A limiter key in a form that is safe to log. A Microsoft key holds the
    directory id and the client id of the app, so a log line shows the
    source and a short hash of the key. The hash is the same for one key,
    so the lines of one budget can be found together."""
    digest = hashlib.sha256(key.encode()).hexdigest()[:12]
    return f"{source}#{digest}"


class _Ticket:
    """One call that waits at a gate."""

    __slots__ = ("token", "turn")

    def __init__(self) -> None:
        self.token = uuid4().hex
        # Set when the call is at the head of its gate.
        self.turn = threading.Event()


class _Gate:
    """The calls of this process that wait for one budget of one class, in
    the order they came."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._tickets: deque[_Ticket] = deque()

    def join(self, ticket: _Ticket) -> None:
        with self._lock:
            self._tickets.append(ticket)
            if len(self._tickets) == 1:
                ticket.turn.set()

    def leave(self, ticket: _Ticket) -> None:
        """Removes the call, and wakes the next call when it was the head.
        A call that already left is ignored."""
        with self._lock:
            if not self._tickets:
                return
            was_head = self._tickets[0] is ticket
            try:
                self._tickets.remove(ticket)
            except ValueError:
                return
            if was_head and self._tickets:
                self._tickets[0].turn.set()


_gates: dict[tuple[str, str, bool], _Gate] = {}
_gates_lock = threading.Lock()


def _gate(tenant_id: str, budget_key: str, bulk: bool) -> _Gate:
    key = (tenant_id, budget_key, bulk)
    with _gates_lock:
        gate = _gates.get(key)
        if gate is None:
            gate = _Gate()
            _gates[key] = gate
        return gate


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
    # The share of the credential budget that a new run starts from when no
    # accepted share is stored. None starts at the full budget and stores
    # nothing.
    start_share: float | None = None
    # The credential limit for any 24 hours, in units. None is no limit.
    per_credential_per_day: int | None = None


class RedisSourceApiLimiter(SourceApiLimiter):
    def __init__(
        self,
        tenant_id: str,
        credential_key: str,
        budgets: dict[str, SourceApiBudget],
        should_stop: Callable[[], bool] | None = None,
        *,
        source: DocumentSource,
        bulk: bool = False,
        pause_key: str | None = None,
    ) -> None:
        self._source = source.value
        self._tenant_id = tenant_id
        self._prefix = f"{_KEY_PREFIX}:{credential_key}"
        # The base of the pauses that this limiter reads and sets, one for
        # each API, so a pause of one API never stops the calls of another.
        # None: it has none.
        self._pause_base = f"{_KEY_PREFIX}:{pause_key}" if pause_key else None
        self._budgets = budgets
        self._should_stop = should_stop
        # Every call of a bulk worker, such as docconversion, waits after the
        # other callers.
        self._bulk = bulk
        # no-direct-redis: allow the budget is shared by every indexing and sync worker
        self._windows = RedisRateWindows(get_redis_client(tenant_id=tenant_id))
        # The epoch of each window when this thread last took a slot from it.
        self._thread_epochs = threading.local()

    def credential_window(self, api: str) -> RateWindow | None:
        budget = self._budgets.get(api)
        if budget is None or budget.per_credential is None:
            return None
        return _window(
            f"{self._prefix}:{api}:all",
            budget.per_credential,
            budget,
            budget.start_share,
        )

    def user_window(self, api: str, user: str | None) -> RateWindow | None:
        budget = self._budgets.get(api)
        if budget is None or budget.per_user is None or user is None:
            return None
        return _window(
            f"{self._prefix}:{api}:user:{user.lower()}", budget.per_user, budget
        )

    def credential_guard(self, api: str) -> RateWindow | None:
        budget = self._budgets.get(api)
        if budget is None or budget.per_credential is None:
            return None
        return _period_guard(f"{self._prefix}:{api}:all", budget.per_credential, budget)

    def user_guard(self, api: str, user: str | None) -> RateWindow | None:
        budget = self._budgets.get(api)
        if budget is None or budget.per_user is None or user is None:
            return None
        return _period_guard(
            f"{self._prefix}:{api}:user:{user.lower()}", budget.per_user, budget
        )

    def _all_windows(self, api: str, user: str | None) -> list[RateWindow]:
        """The windows of a call: the credential and user windows first, then
        their guards."""
        return [
            w
            for w in (
                self.credential_window(api),
                self.user_window(api, user),
                self.credential_guard(api),
                self.user_guard(api, user),
            )
            if w is not None
        ]

    def _units(self, api: str, cost: int, request_count: int) -> int:
        budget = self._budgets[api]
        return request_count if budget.count_requests else cost

    def try_acquire(
        self,
        api: str,
        cost: int,
        user: str | None = None,
        request_count: int = 1,
        turn: WaitTurn | None = None,
        force: bool = False,
    ) -> float:
        """Takes the call's units and returns 0, or returns the seconds until
        a full window can have room for it. ``turn`` keeps the call's place
        among the waiters; ``force`` takes the units over the budget."""
        return self._try(api, cost, user, request_count, turn, force).wait_seconds

    def _try(
        self,
        api: str,
        cost: int,
        user: str | None,
        request_count: int,
        turn: WaitTurn | None,
        force: bool,
    ) -> AcquireResult:
        if api not in self._budgets:
            return AcquireResult(wait_seconds=0, shares=[], epochs=[])
        user_window = self.user_window(api, user)
        credential_window = self.credential_window(api)
        windows = self._all_windows(api, user)
        result = self._windows.try_acquire_with_shares(
            windows,
            self._units(api, cost, request_count),
            request_count,
            turn,
            force,
        )
        # No shares when Redis cannot be reached. A guard is never cut, so
        # only the windows have a share to record.
        for window, share in zip(windows, result.shares, strict=False):
            if window.key.endswith(":period"):
                continue
            self._record_budget(api, window, share, window == user_window)
        for window, start, queued, share in zip(
            windows, result.starts, result.queued, result.shares, strict=False
        ):
            if window != credential_window:
                continue
            set_redis_waiters(self._source, api, queued)
            if start != WindowStart.NONE:
                logger.info(
                    "The shared budget %s starts at %.0f%% of its limit (%s).",
                    _key_for_log(self._source, window.key),
                    share * 100,
                    "stored" if start == WindowStart.STORED else "cold start",
                )
        if result.wait_seconds == 0:
            record_limiter_units(
                self._source, api, self._units(api, cost, request_count)
            )
            epochs: dict[str, int] = vars(self._thread_epochs).setdefault("epochs", {})
            for window, epoch in zip(windows, result.epochs, strict=False):
                epochs[window.key] = epoch
        return result

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

    def _blocked_by_user_only(
        self, api: str, user: str | None, result: AcquireResult
    ) -> bool:
        """True when only the user's windows did not fit the call."""
        windows = self._all_windows(api, user)
        shared = {self.credential_window(api), self.credential_guard(api)}
        blocked = [
            window
            for window, is_blocked in zip(windows, result.blocked, strict=False)
            if is_blocked
        ]
        return bool(blocked) and all(window not in shared for window in blocked)

    def _sleep(self, seconds: float) -> None:
        """Sleeps, and checks the stop signal at least every few seconds."""
        end = time.monotonic() + seconds
        while True:
            left = end - time.monotonic()
            if left <= 0:
                return
            time.sleep(min(left, _STOP_CHECK_INTERVAL_SECONDS))
            self._check_stop()

    @override
    def acquire(
        self,
        api: str,
        cost: int,
        user: str | None = None,
        request_count: int = 1,
        *,
        bulk: bool = False,
    ) -> None:
        if api not in self._budgets:
            return
        self._wait_for_pause(api)
        if self._wait_for_day_budget(api, self._units(api, cost, request_count)):
            # The source can ask for a pause while the call waits for the day.
            self._wait_for_pause(api)
        is_bulk = bulk or self._bulk
        gate = _gate(self._tenant_id, f"{self._prefix}:{api}", is_bulk)
        ticket = _Ticket()
        turn = WaitTurn(token=ticket.token, bulk=is_bulk)
        started = time.monotonic()
        waited_at_all = False
        taken = False
        tried = False
        # A call that only its user's windows block waits alone, out of
        # the gate.
        alone = False
        gate.join(ticket)
        add_local_waiters(self._source, api, 1)
        try:
            while True:
                waited = time.monotonic() - started
                force = waited >= MAX_WAIT_SECONDS
                if not force and not alone and not ticket.turn.is_set():
                    # Another call of this process is at the head.
                    self._check_stop()
                    waited_at_all = True
                    ticket.turn.wait(
                        min(_STOP_CHECK_INTERVAL_SECONDS, MAX_WAIT_SECONDS - waited)
                    )
                    continue
                result = self._try(api, cost, user, request_count, turn, force)
                tried = True
                if result.wait_seconds == 0:
                    taken = True
                    break
                if not alone and self._blocked_by_user_only(api, user, result):
                    alone = True
                    gate.leave(ticket)
                self._check_stop()
                waited_at_all = True
                # Redis gives the time when the slot is due. A long wait
                # still tries again before its place goes stale.
                self._sleep(
                    max(
                        0.0,
                        min(
                            result.wait_seconds,
                            _REFRESH_SECONDS,
                            MAX_WAIT_SECONDS - waited,
                        ),
                    )
                )
            if force:
                record_limiter_overdraft(self._source, api)
                logger.warning(
                    "A %s call waited %.0fs for the shared budget; it takes its "
                    "slot over the budget.",
                    api,
                    waited,
                )
            # A stop during the last wait ends the call before its request.
            if waited_at_all:
                self._check_stop()
                # The source can ask for a pause while the call waits.
                self._wait_for_pause(api)
        finally:
            gate.leave(ticket)
            add_local_waiters(self._source, api, -1)
            if tried and not taken:
                self._windows.leave(
                    self._all_windows(api, user),
                    turn,
                    self._units(api, cost, request_count),
                )
            if waited_at_all:
                record_limiter_wait(self._source, api, time.monotonic() - started)

    def _pause_key(self, api: str) -> str | None:
        if self._pause_base is None:
            return None
        return f"{self._pause_base}:{api}:blocked_until"

    def _wait_for_pause(self, api: str) -> None:
        """Waits until the pause of ``api`` that the source asked for ends."""
        pause_key = self._pause_key(api)
        if pause_key is None:
            return
        waited = 0.0
        try:
            while True:
                left = self._windows.pause_left(pause_key)
                if left <= 0:
                    return
                self._check_stop()
                started = time.monotonic()
                self._sleep(left)
                waited += time.monotonic() - started
        finally:
            record_limiter_paused_seconds(self._source, api, waited)

    def _wait_for_day_budget(self, api: str, units: int) -> bool:
        """Takes the call's units from the budget of the day, and waits for
        room when the day is full. True when it waited."""
        limit = self._budgets[api].per_credential_per_day
        if limit is None:
            return False
        key = f"{self._prefix}:{api}:all:day"
        started = time.monotonic()
        warned = False
        try:
            while True:
                wait = self._windows.try_take_from_day(key, units, limit)
                if wait <= 0:
                    return warned
                if not warned:
                    warned = True
                    logger.warning(
                        "The %s budget %s for 24 hours (%d units) is used; the "
                        "calls wait for it.",
                        api,
                        key,
                        limit,
                    )
                self._check_stop()
                self._sleep(min(wait, _DAY_RETRY_SECONDS))
        finally:
            if warned:
                record_limiter_wait(self._source, api, time.monotonic() - started)

    @override
    def report_retry_after(self, api: str, seconds: float) -> None:
        pause_key = self._pause_key(api)
        if pause_key is None or seconds <= 0 or api not in self._budgets:
            return
        left = self._windows.pause(pause_key, seconds)
        record_limiter_pause(self._source, api)
        logger.info(
            "%s asked its callers to wait %.1fs (Retry-After); every call of "
            "the shared pause %s waits %.1fs.",
            api,
            seconds,
            _key_for_log(self._source, pause_key),
            left,
        )

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
        epochs: dict[str, int] = vars(self._thread_epochs).get("epochs", {})
        result = self._windows.report_refusals(window, count, epochs.get(window.key))
        scope = LimiterScope.USER if user_scope else LimiterScope.PROJECT
        if result.late:
            record_late_refusals(self._source, api, scope, count)
            return
        if not result.applied:
            return
        record_limiter_cut(self._source, api, scope)
        self._record_budget(api, window, result.share, user_scope)
        budget = self._budgets[api]
        if not user_scope and budget.per_credential is not None:
            set_project_ceiling(
                self._source,
                api,
                allowed_units(budget.per_credential, result.ceiling),
            )
        logger.info(
            "%s refused %.1f%% of the recent calls for its rate (%s); the shared "
            "budget %s is cut%s to %.0f%% of its limit. It accepted %.0f%%.",
            api,
            result.refused_share * 100,
            "user" if user_scope else "credential",
            _key_for_log(self._source, window.key),
            " hard" if result.hard else "",
            result.share * 100,
            result.accepted_share * 100,
        )


def _window(
    key: str,
    limit: int,
    budget: SourceApiBudget,
    start_share: float | None = None,
) -> RateWindow:
    """The window that enforces ``limit`` for the budget's period."""
    if budget.window_seconds is None or budget.window_seconds >= budget.period_seconds:
        return RateWindow(
            key=key,
            limit=limit,
            period_seconds=budget.period_seconds,
            start_share=start_share,
        )
    return RateWindow(
        key=key,
        limit=max(1, math.floor(limit * budget.window_seconds / budget.period_seconds)),
        period_seconds=budget.window_seconds,
        start_share=start_share,
    )


def _period_guard(key: str, limit: int, budget: SourceApiBudget) -> RateWindow | None:
    """The window of the whole period behind a shorter window, or None when
    the budget's window is the whole period."""
    if budget.window_seconds is None or budget.window_seconds >= budget.period_seconds:
        return None
    return RateWindow(
        key=f"{key}:period", limit=limit, period_seconds=budget.period_seconds
    )


# Google's quotas are for one minute. A window of 10 seconds keeps the rate
# steady; see the module docstring.
_GOOGLE_WINDOW_SECONDS = 10.0
# With no accepted share stored, a run starts at this share of the project
# budget and grows from it. Google accepted about 0.25-0.29 of the bench
# budget; a start at the full budget refused most calls in the first minutes.
GOOGLE_START_SHARE = 0.25

# The budgets of Google's Drive and Docs quotas, from the configuration.
GOOGLE_DRIVE_BUDGETS: dict[str, SourceApiBudget] = {
    DriveQuotaApi.DRIVE.value: SourceApiBudget(
        per_credential=GOOGLE_DRIVE_QUOTA_PER_PROJECT,
        per_user=GOOGLE_DRIVE_QUOTA_PER_USER,
        count_requests=GOOGLE_DRIVE_QUOTA_MODEL == "requests",
        window_seconds=_GOOGLE_WINDOW_SECONDS,
        start_share=GOOGLE_START_SHARE,
    ),
    DriveQuotaApi.DOCS.value: SourceApiBudget(
        per_credential=GOOGLE_DOCS_READS_PER_PROJECT,
        per_user=GOOGLE_DOCS_READS_PER_USER,
        window_seconds=_GOOGLE_WINDOW_SECONDS,
        start_share=GOOGLE_START_SHARE,
    ),
}


# Microsoft counts resource units (RU) for each app registration in a tenant,
# for one minute. The limit depends on the tenant's licenses: 1,250 RU for the
# smallest tier and 6,250 RU for the largest. The budget is the largest limit,
# and a new window starts at the smallest one.
MICROSOFT_GRAPH_RU_PER_MINUTE = 6_250
_MICROSOFT_WINDOW_SECONDS = 10.0
MICROSOFT_START_SHARE = 0.2
# The fetches of pre-authenticated download links in one minute, for each
# app. Microsoft publishes no limit for the download host, so the lane learns
# it from 429 answers, from a start share of this ceiling.
MICROSOFT_LINK_DOWNLOADS_PER_MINUTE = 6_000
# The learned download lane. It is apart from the Graph budget: a link fetch
# costs no RU, and a throttle of the download host pauses and cuts only it.
MICROSOFT_DOWNLOAD_BUDGET = SourceApiBudget(
    per_credential=MICROSOFT_LINK_DOWNLOADS_PER_MINUTE,
    window_seconds=_MICROSOFT_WINDOW_SECONDS,
    start_share=MICROSOFT_START_SHARE,
)
# The learned budget that the connectors on one app share when they set no
# budget of their own.
MICROSOFT_GRAPH_BUDGETS: dict[str, SourceApiBudget] = {
    GRAPH_LIMITER_API: SourceApiBudget(
        per_credential=MICROSOFT_GRAPH_RU_PER_MINUTE,
        window_seconds=_MICROSOFT_WINDOW_SECONDS,
        start_share=MICROSOFT_START_SHARE,
    ),
    DOWNLOAD_LIMITER_API: MICROSOFT_DOWNLOAD_BUDGET,
}


def microsoft_app_key(
    source: DocumentSource, credential_json: dict[str, Any]
) -> str | None:
    """The limiter key of the app registration that a Microsoft credential
    uses: its directory (tenant) id and client id. Microsoft limits each app
    in a tenant, so every connector on the app shares this key. None when
    the source is not a Microsoft Graph source or the credential has no app.
    ``credential_json`` has the source's own keys."""
    identity = microsoft_app_identity(source, credential_json)
    if identity is None:
        if source in MICROSOFT_GRAPH_SOURCES:
            logger.warning(
                "The %s credential has no app registration ids; its calls are "
                "not limited.",
                source.value,
            )
        return None
    directory_id, client_id = identity
    return f"microsoft:{directory_id}:{client_id}"


def microsoft_connector_budgets(ru_per_minute: int) -> dict[str, SourceApiBudget]:
    """The budgets of a connector whose admin set its RU per minute: the
    full value from the start, and Microsoft's limit for 24 hours at the
    same tier. A 429 answer still cuts the window."""
    return {
        GRAPH_LIMITER_API: SourceApiBudget(
            per_credential=ru_per_minute,
            window_seconds=_MICROSOFT_WINDOW_SECONDS,
            per_credential_per_day=ru_per_minute * RU_PER_DAY_FACTOR,
        )
    }


def build_source_api_limiter(
    source: DocumentSource,
    credential_id: int,
    should_stop: Callable[[], bool] | None = None,
    bulk: bool = False,
    load_credential_json: Callable[[], dict[str, Any]] | None = None,
    cc_pair_id: int | None = None,
    connector_specific_config: dict[str, Any] | None = None,
) -> SourceApiLimiter | None:
    """The shared limiter for a connector of ``source`` that uses the
    credential, or None when the source has no budgets or the limiter is off.
    Connectors that share a credential share its budgets. A call that waits
    for its budget ends with ConnectorStopSignal when ``should_stop`` turns
    true. With ``bulk``, every call waits after the calls of other workers.

    A Microsoft Graph source needs ``load_credential_json``, which returns
    the credential in the source's own keys. Its connectors share one budget
    and one pause for each app registration in a tenant, whatever credential
    row holds the app. A connector whose config sets ``ru_per_minute`` has a
    budget of its own, keyed by ``cc_pair_id``, and still shares the pause."""
    if not ENABLE_SOURCE_API_LIMITER:
        return None
    if source in MICROSOFT_GRAPH_SOURCES:
        if load_credential_json is None:
            return None
        app_key = microsoft_app_key(source, load_credential_json())
        if app_key is None:
            return None
        ru_per_minute = configured_ru_per_minute(connector_specific_config or {})
        if ru_per_minute is not None and cc_pair_id is not None:
            return RedisSourceApiLimiter(
                tenant_id=get_current_tenant_id(),
                credential_key=f"microsoft:cc_pair:{cc_pair_id}",
                budgets=microsoft_connector_budgets(ru_per_minute),
                should_stop=should_stop,
                source=source,
                bulk=bulk,
                pause_key=app_key,
            )
        return RedisSourceApiLimiter(
            tenant_id=get_current_tenant_id(),
            credential_key=app_key,
            budgets=MICROSOFT_GRAPH_BUDGETS,
            should_stop=should_stop,
            source=source,
            bulk=bulk,
            pause_key=app_key,
        )
    if source != DocumentSource.GOOGLE_DRIVE:
        return None
    return RedisSourceApiLimiter(
        tenant_id=get_current_tenant_id(),
        credential_key=f"{source.value}:{credential_id}",
        budgets=GOOGLE_DRIVE_BUDGETS,
        should_stop=should_stop,
        source=source,
        bulk=bulk,
    )
