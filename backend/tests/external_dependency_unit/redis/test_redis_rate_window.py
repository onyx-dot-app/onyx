"""The shared rate windows and the source-API limiter against a real Redis.

Each test uses a unique tenant, so runs cannot collide. Separate limiter
objects, and a separate process, stand in for separate worker pods: they share
only Redis."""

import subprocess
import sys
import threading
import time
from collections.abc import Callable, Iterator
from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

import pytest
from prometheus_client import REGISTRY
from redis.exceptions import ConnectionError as RedisConnectionError

from onyx.configs.constants import DocumentSource
from onyx.connectors import source_api_limiter
from onyx.connectors.models import ConnectorStopSignal
from onyx.connectors.source_api_limiter import (
    RedisSourceApiLimiter,
    SourceApiBudget,
)
from onyx.redis import redis_rate_window
from onyx.redis.redis_pool import get_redis_client
from onyx.redis.redis_rate_window import (
    RateWindow,
    RedisRateWindows,
    RefusalResult,
    WaitTurn,
)
from onyx.server.metrics import source_api_metrics

_API = "drive"


@pytest.fixture
def tenant_id() -> Iterator[str]:
    tenant = f"tenant_test_{uuid4().hex[:12]}"
    yield tenant
    client = get_redis_client(tenant_id=tenant)
    for key in client.scan_iter("*"):
        client.delete(key)


@pytest.fixture
def windows(tenant_id: str) -> RedisRateWindows:
    return RedisRateWindows(get_redis_client(tenant_id=tenant_id))


def _limiter(
    tenant_id: str, per_credential: int | None, per_user: int | None, **kwargs: bool
) -> RedisSourceApiLimiter:
    return RedisSourceApiLimiter(
        tenant_id,
        "google_drive:1",
        {
            _API: SourceApiBudget(
                per_credential=per_credential,
                per_user=per_user,
                period_seconds=10,
                **kwargs,
            )
        },
        source=DocumentSource.GOOGLE_DRIVE,
    )


def test_a_request_takes_its_cost_from_the_window(windows: RedisRateWindows) -> None:
    window = RateWindow(key="w", limit=1000, period_seconds=10)

    assert windows.try_acquire([window], cost=400) == 0
    assert windows.try_acquire([window], cost=400) == 0
    # 800 of 1000 are taken: 300 more do not fit, 200 do.
    assert 0 < windows.try_acquire([window], cost=300) <= 10
    assert windows.try_acquire([window], cost=200) == 0


def test_units_come_back_when_their_request_leaves_the_window(
    windows: RedisRateWindows,
) -> None:
    window = RateWindow(key="w", limit=100, period_seconds=0.3)
    assert windows.try_acquire([window], cost=100) == 0
    wait = windows.try_acquire([window], cost=60)
    assert 0 < wait <= 0.3

    time.sleep(wait + 0.05)  # test-flakes: allow the window reads the Redis clock

    assert windows.try_acquire([window], cost=60) == 0
    assert 0 < windows.try_acquire([window], cost=60)


def test_a_request_takes_from_every_window_or_from_none(
    windows: RedisRateWindows,
) -> None:
    project = RateWindow(key="project", limit=300, period_seconds=10)
    user_a = RateWindow(key="user:a", limit=100, period_seconds=10)
    user_b = RateWindow(key="user:b", limit=100, period_seconds=10)

    assert windows.try_acquire([project, user_a], cost=100) == 0
    # User A is full. The refused request must take nothing from the project.
    assert windows.try_acquire([project, user_a], cost=100) > 0
    assert windows.try_acquire([project, user_b], cost=100) == 0
    assert windows.try_acquire([project], cost=100) == 0
    assert windows.try_acquire([project], cost=1) > 0


def test_one_request_larger_than_the_limit_fits_an_empty_window(
    windows: RedisRateWindows,
) -> None:
    window = RateWindow(key="w", limit=50, period_seconds=10)
    assert windows.try_acquire([window], cost=200) == 0
    assert windows.try_acquire([window], cost=1) > 0


def test_a_report_keeps_the_total_of_a_window_longer_than_the_meta_ttl(
    tenant_id: str, windows: RedisRateWindows
) -> None:
    window = RateWindow(key="w", limit=100, period_seconds=3600)
    assert windows.try_acquire([window], cost=100) == 0

    windows.report_refusals(window)

    # The running total must live as long as the log of the window.
    client = get_redis_client(tenant_id=tenant_id)
    assert client.pttl("w:meta") > 600_000
    assert windows.try_acquire([window], cost=1) > 0


def test_a_short_window_cannot_pass_the_budget_of_the_period(tenant_id: str) -> None:
    """A request larger than the short window's share fits an empty window.
    The window of the whole period still holds the configured budget."""
    limiter = RedisSourceApiLimiter(
        tenant_id,
        "google_drive:1",
        {
            _API: SourceApiBudget(
                per_credential=300, period_seconds=60, window_seconds=10
            )
        },
        source=DocumentSource.GOOGLE_DRIVE,
    )
    short_window = limiter.credential_window(_API)
    assert short_window is not None and short_window.limit == 50

    taken = 0
    for _ in range(6):
        # As if the short window emptied between the requests.
        limiter._windows.delete(short_window)
        if limiter.try_acquire(_API, 100) == 0:
            taken += 100

    assert taken == 300


def _send(windows: RedisRateWindows, window: RateWindow, requests: int) -> None:
    """Counts ``requests`` requests that took no units."""
    assert (
        windows.try_acquire_with_shares(
            [window], cost=0, requests=requests
        ).wait_seconds
        == 0
    )


def test_one_refusal_among_many_requests_does_not_cut(
    windows: RedisRateWindows,
) -> None:
    window = RateWindow(key="w", limit=100, period_seconds=10)
    _send(windows, window, 1000)

    result = windows.report_refusals(window)

    assert result == RefusalResult(
        share=1.0, applied=False, hard=False, refused_share=0.001
    )
    assert windows.try_acquire([window], cost=100) == 0


def test_a_few_refusals_with_no_requests_do_not_cut(
    windows: RedisRateWindows,
) -> None:
    """A share of 100 % needs the minimum count too."""
    window = RateWindow(key="w", limit=100, period_seconds=10)
    for _ in range(redis_rate_window.MIN_REFUSALS_TO_CUT - 1):
        assert not windows.report_refusals(window).applied


def test_a_refused_share_over_the_threshold_cuts_gently(
    windows: RedisRateWindows,
) -> None:
    window = RateWindow(key="w", limit=100, period_seconds=10)
    _send(windows, window, 500)

    # 15 of 500 is 3 %: over the threshold, under a storm.
    result = windows.report_refusals(window, count=15)

    assert result == RefusalResult(
        share=0.8, applied=True, hard=False, refused_share=0.03, ceiling=0.8
    )
    assert windows.try_acquire([window], cost=80) == 0
    assert windows.try_acquire([window], cost=1) > 0


def test_a_storm_cuts_to_the_accepted_share(windows: RedisRateWindows) -> None:
    window = RateWindow(key="w", limit=100, period_seconds=10)
    _send(windows, window, 100)

    # Google refused 70 of 100: the window keeps the 30 % that it accepted.
    result = windows.report_refusals(window, count=70)

    assert result == RefusalResult(
        share=0.3, applied=True, hard=True, refused_share=0.7, ceiling=0.3
    )


def test_a_storm_cuts_at_least_by_half(windows: RedisRateWindows) -> None:
    window = RateWindow(key="w", limit=100, period_seconds=10)
    _send(windows, window, 100)
    result = windows.report_refusals(window, count=20)
    assert (result.share, result.hard) == (0.5, True)


def test_no_second_cut_in_the_hold(windows: RedisRateWindows) -> None:
    window = RateWindow(key="w", limit=100, period_seconds=10)
    _send(windows, window, 500)
    assert windows.report_refusals(window, count=15).applied

    # The same burst goes on, at a share under a storm.
    _send(windows, window, 500)
    result = windows.report_refusals(window, count=15)

    assert (result.share, result.applied) == (0.8, False)


def test_a_storm_cuts_again_in_the_hold_after_the_recut_time(
    windows: RedisRateWindows, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(redis_rate_window, "STORM_RECUT_SECONDS", 0.2)
    window = RateWindow(key="w", limit=100, period_seconds=10)
    _send(windows, window, 100)
    assert windows.report_refusals(window, count=50).share == 0.5

    # Too soon: the window has not seen the lower rate yet.
    _send(windows, window, 100)
    assert not windows.report_refusals(window, count=50).applied

    time.sleep(0.25)  # test-flakes: allow the window reads the Redis clock
    _send(windows, window, 100)
    result = windows.report_refusals(window, count=50)
    assert (result.share, result.applied, result.hard) == (0.25, True, True)


def test_a_cut_stops_at_the_lowest_share(
    windows: RedisRateWindows, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(redis_rate_window, "STORM_RECUT_SECONDS", 0.0)
    window = RateWindow(key="w", limit=100, period_seconds=10)
    shares = []
    for _ in range(3):
        _send(windows, window, 10)
        shares.append(windows.report_refusals(window, count=10).share)
    assert shares == [0.1, 0.1, 0.1]


def test_a_storm_cut_keeps_most_of_the_accepted_share(
    windows: RedisRateWindows,
) -> None:
    """The window was full and Google refused 30 %: it accepted 70 % of the
    limit. Half of the share would cut far below that."""
    window = RateWindow(key="w", limit=1000, period_seconds=10)
    assert (
        windows.try_acquire_with_shares([window], cost=1000, requests=100).wait_seconds
        == 0
    )

    result = windows.report_refusals(window, count=30)

    assert (result.applied, result.hard) == (True, True)
    assert result.accepted_share == 0.7
    assert result.share == 0.63


def test_a_late_refusal_does_not_cut_again(
    windows: RedisRateWindows, monkeypatch: pytest.MonkeyPatch
) -> None:
    """One burst gives one cut. Refusals that arrive after the cut, for
    requests sent before it, do not count. Refusals for requests sent after
    the cut still can cut again."""
    monkeypatch.setattr(redis_rate_window, "STORM_RECUT_SECONDS", 0.0)
    window = RateWindow(key="w", limit=100, period_seconds=10)
    before = windows.try_acquire_with_shares([window], cost=0, requests=100)
    assert before.epochs == [0]
    first = windows.report_refusals(window, count=50, epoch=0)
    assert (first.share, first.applied) == (0.5, True)

    # The rest of the burst arrives late: no cut, and no count.
    for _ in range(5):
        late = windows.report_refusals(window, count=50, epoch=0)
        assert (late.share, late.applied, late.late) == (0.5, False, True)

    # Google goes on refusing the requests sent at the lower share.
    after = windows.try_acquire_with_shares([window], cost=0, requests=100)
    assert after.epochs == [1]
    again = windows.report_refusals(window, count=50, epoch=1)
    assert (again.share, again.applied, again.late) == (0.25, True, False)


def test_the_share_grows_fast_below_the_ceiling_and_slowly_near_it(
    windows: RedisRateWindows, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(redis_rate_window, "CUT_HOLD_SECONDS", 0.3)
    monkeypatch.setattr(redis_rate_window, "STORM_RECUT_SECONDS", 0.0)
    monkeypatch.setattr(redis_rate_window, "GROW_INTERVAL_SECONDS", 0.1)
    monkeypatch.setattr(redis_rate_window, "GROW_STEP", 0.1)
    monkeypatch.setattr(redis_rate_window, "SLOW_GROW_STEP", 0.02)
    monkeypatch.setattr(redis_rate_window, "SLOW_ZONE", 0.8)
    window = RateWindow(key="w", limit=1000, period_seconds=10)
    # A storm cuts from 100 % to 50 %: the ceiling is 50 %.
    windows.try_acquire_with_shares([window], cost=600, requests=100)
    assert windows.report_refusals(window, count=50).share == 0.5
    # Google refuses 90 % of the requests after the cut, while its quota
    # recovers from the burst. The second cut goes to the floor, and the
    # ceiling keeps 90 % of 50 %.
    windows.try_acquire_with_shares([window], cost=0, requests=100)
    assert windows.report_refusals(window, count=90, epoch=1).share == 0.1

    def share_after_one_interval() -> float:
        time.sleep(0.12)  # test-flakes: allow the window reads the Redis clock
        return windows.try_acquire_with_shares([window], cost=0).shares[0]

    # No growth in the hold.
    assert windows.try_acquire_with_shares([window], cost=0).shares[0] == 0.1
    time.sleep(0.3)  # test-flakes: allow the window reads the Redis clock
    grown = [share_after_one_interval() for _ in range(7)]
    # Fast steps up to 80 % of the ceiling of 45 %, then slow steps. Past the
    # ceiling, the ceiling moves up and the steps stay slow.
    assert grown == [0.2, 0.3, 0.4, 0.42, 0.44, 0.46, 0.48]


def test_a_cut_resets_the_refused_share(windows: RedisRateWindows) -> None:
    window = RateWindow(key="w", limit=100, period_seconds=10)
    _send(windows, window, 500)
    assert windows.report_refusals(window, count=15).applied
    # The refusals before the cut do not count after it.
    _send(windows, window, 1000)
    assert windows.report_refusals(window).refused_share == 0.001


def test_two_processes_share_one_budget(tenant_id: str) -> None:
    """Another process spends 800 of 1000 units. This process then has 200."""
    code = (
        "from onyx.connectors.source_api_limiter import "
        "RedisSourceApiLimiter, SourceApiBudget\n"
        "from onyx.configs.constants import DocumentSource\n"
        f"limiter = RedisSourceApiLimiter({tenant_id!r}, 'google_drive:1', "
        "{'drive': SourceApiBudget(per_credential=1000, per_user=None, "
        "period_seconds=10)}, source=DocumentSource.GOOGLE_DRIVE)\n"
        "assert all(limiter.try_acquire('drive', 200, 'a@x.com') == 0 "
        "for _ in range(4))\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, timeout=120
    )
    assert result.returncode == 0, result.stderr

    limiter = _limiter(tenant_id, per_credential=1000, per_user=None)
    assert limiter.try_acquire(_API, 200, "b@x.com") == 0
    assert limiter.try_acquire(_API, 200, "b@x.com") > 0


def test_concurrent_workers_never_exceed_the_budget(tenant_id: str) -> None:
    pods = [_limiter(tenant_id, per_credential=1000, per_user=None) for _ in range(4)]

    def take(index: int) -> bool:
        return pods[index % 4].try_acquire(_API, 100, f"user{index}@x.com") == 0

    with ThreadPoolExecutor(max_workers=16) as pool:
        taken = list(pool.map(take, range(64)))

    assert sum(taken) == 10


def test_a_user_cut_does_not_slow_another_user(tenant_id: str) -> None:
    limiter = _limiter(tenant_id, per_credential=10_000, per_user=1000)
    _send_requests(limiter, "a@x.com", 100)

    # Google answered 403 userRateLimitExceeded to half of user A's requests.
    limiter.report_rate_limit(_API, "a@x.com", user_scope=True, count=50)

    assert limiter.try_acquire(_API, 500, "a@x.com") == 0
    assert limiter.try_acquire(_API, 100, "a@x.com") > 0
    assert limiter.try_acquire(_API, 1000, "b@x.com") == 0


def test_a_project_cut_slows_every_user(tenant_id: str) -> None:
    limiter = _limiter(tenant_id, per_credential=1000, per_user=1000)
    _send_requests(limiter, "a@x.com", 100)

    limiter.report_rate_limit(_API, "a@x.com", user_scope=False, count=50)

    assert limiter.try_acquire(_API, 300, "a@x.com") == 0
    assert limiter.try_acquire(_API, 200, "b@x.com") == 0
    assert limiter.try_acquire(_API, 100, "c@x.com") > 0


def _send_requests(limiter: RedisSourceApiLimiter, user: str, count: int) -> None:
    """Counts ``count`` requests that took no units."""
    assert limiter.try_acquire(_API, 0, user, request_count=count) == 0


def test_a_user_refusal_does_not_count_for_the_project(tenant_id: str) -> None:
    limiter = _limiter(tenant_id, per_credential=1000, per_user=1000)
    _send_requests(limiter, "a@x.com", 100)
    limiter.report_rate_limit(_API, "a@x.com", user_scope=True, count=50)

    # The project's refused share is still 0: one more refusal does not cut.
    limiter.report_rate_limit(_API, "a@x.com", user_scope=False, count=1)
    assert limiter.try_acquire(_API, 1000, "b@x.com") == 0


def test_the_requests_model_counts_each_call_as_one(tenant_id: str) -> None:
    limiter = _limiter(tenant_id, per_credential=2, per_user=None, count_requests=True)
    assert limiter.try_acquire(_API, 200, "a@x.com") == 0
    assert limiter.try_acquire(_API, 5, "a@x.com") == 0
    assert limiter.try_acquire(_API, 5, "a@x.com") > 0


def test_the_requests_model_counts_each_request_of_a_batch(tenant_id: str) -> None:
    limiter = _limiter(tenant_id, per_credential=3, per_user=None, count_requests=True)
    assert limiter.try_acquire(_API, 10, "a@x.com", request_count=2) == 0
    # 2 of 3 requests are taken: a batch of 2 more does not fit, 1 does.
    assert limiter.try_acquire(_API, 10, "a@x.com", request_count=2) > 0
    assert limiter.try_acquire(_API, 10, "a@x.com") == 0


def test_an_api_with_no_budget_is_not_limited(tenant_id: str) -> None:
    limiter = _limiter(tenant_id, per_credential=1, per_user=1)
    assert limiter.try_acquire("admin", 100, "a@x.com") == 0
    assert limiter.try_acquire("admin", 100, "a@x.com") == 0
    limiter.report_rate_limit("admin", "a@x.com", user_scope=True)


def test_acquire_waits_for_room(tenant_id: str) -> None:
    limiter = RedisSourceApiLimiter(
        tenant_id,
        "google_drive:1",
        {_API: SourceApiBudget(per_credential=100, period_seconds=0.4)},
        source=DocumentSource.GOOGLE_DRIVE,
    )
    limiter.acquire(_API, 100)
    started = time.monotonic()
    limiter.acquire(_API, 100)
    assert 0.2 < time.monotonic() - started < 2


def test_a_stop_signal_ends_the_wait(tenant_id: str) -> None:
    limiter = RedisSourceApiLimiter(
        tenant_id,
        "google_drive:1",
        {_API: SourceApiBudget(per_credential=100, period_seconds=30)},
        should_stop=lambda: True,
        source=DocumentSource.GOOGLE_DRIVE,
    )
    limiter.acquire(_API, 100)
    with pytest.raises(ConnectorStopSignal):
        limiter.acquire(_API, 100)


def test_a_call_takes_its_slot_over_the_budget_after_the_longest_wait(
    tenant_id: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(source_api_limiter, "MAX_WAIT_SECONDS", 0.3)
    limiter = _limiter(tenant_id, per_credential=100, per_user=None)

    def overdrafts() -> float:
        return (
            REGISTRY.get_sample_value(
                "onyx_source_api_limiter_overdrafts_total",
                {"source": "google_drive", "api": _API},
            )
            or 0.0
        )

    before = overdrafts()
    limiter.acquire(_API, 100)
    started = time.monotonic()
    limiter.acquire(_API, 100)
    assert 0.3 <= time.monotonic() - started < 3
    assert overdrafts() == before + 1
    # The window counts the slot that the call took over the budget.
    assert limiter.try_acquire(_API, 1) > 0


def _short_limiter(
    tenant_id: str,
    limit: int,
    period_seconds: float,
    should_stop: Callable[[], bool] | None = None,
) -> RedisSourceApiLimiter:
    return RedisSourceApiLimiter(
        tenant_id,
        "google_drive:1",
        {_API: SourceApiBudget(per_credential=limit, period_seconds=period_seconds)},
        should_stop,
        source=DocumentSource.GOOGLE_DRIVE,
    )


def test_a_new_call_does_not_take_the_room_that_a_waiter_waits_for(
    tenant_id: str,
) -> None:
    limiter = _short_limiter(tenant_id, limit=2, period_seconds=0.3)
    assert limiter.try_acquire(_API, 2) == 0
    turn = WaitTurn(token="waiter", bulk=True)
    assert limiter.try_acquire(_API, 2, turn=turn) > 0

    time.sleep(0.35)  # test-flakes: allow the window reads the Redis clock

    # The window is empty, but the waiter came first and waits for 2 units.
    assert limiter.try_acquire(_API, 1) > 0
    assert limiter.try_acquire(_API, 2, turn=turn) == 0


def test_a_priority_call_goes_before_the_bulk_waiters(tenant_id: str) -> None:
    limiter = _short_limiter(tenant_id, limit=1, period_seconds=0.3)
    assert limiter.try_acquire(_API, 1) == 0
    conversion = WaitTurn(token="conversion", bulk=True)
    assert limiter.try_acquire(_API, 1, turn=conversion) > 0

    time.sleep(0.35)  # test-flakes: allow the window reads the Redis clock

    # Group sync comes later, but it does not wait behind conversion.
    assert limiter.try_acquire(_API, 1, turn=WaitTurn(token="sync")) == 0
    assert limiter.try_acquire(_API, 1, turn=conversion) > 0


def test_waiting_calls_of_one_class_go_in_the_order_they_came(
    tenant_id: str,
) -> None:
    limiter = _short_limiter(tenant_id, limit=1, period_seconds=0.2)
    limiter.acquire(_API, 1)
    order: list[int] = []
    lock = threading.Lock()

    def call(index: int) -> None:
        limiter.acquire(_API, 1, bulk=True)
        with lock:
            order.append(index)

    threads = []
    for index in range(4):
        thread = threading.Thread(target=call, args=(index,))
        thread.start()
        threads.append(thread)
        time.sleep(0.03)  # test-flakes: allow each call gets its place in turn
    for thread in threads:
        thread.join(timeout=10)

    assert order == [0, 1, 2, 3]


def test_every_call_of_a_bulk_worker_waits_after_the_other_callers(
    tenant_id: str,
) -> None:
    stop = threading.Event()
    budget = {_API: SourceApiBudget(per_credential=1, period_seconds=30)}
    conversion = RedisSourceApiLimiter(
        tenant_id,
        "google_drive:1",
        budget,
        stop.is_set,
        source=DocumentSource.GOOGLE_DRIVE,
        bulk=True,
    )
    conversion.acquire(_API, 1)

    # A listing call of the conversion worker is bulk too.
    thread = threading.Thread(
        target=lambda: pytest.raises(ConnectorStopSignal, conversion.acquire, _API, 1)
    )
    thread.start()
    window = conversion.credential_window(_API)
    assert window is not None
    client = get_redis_client(tenant_id=tenant_id)
    queue: list[tuple[bytes, float]] = []
    for _ in range(100):
        queue = client.zrange(f"{window.key}:queue", 0, -1, withscores=True)
        if queue:
            break
        stop.wait(0.02)
    stop.set()
    thread.join(timeout=10)

    assert len(queue) == 1
    # A bulk place sorts after the place of every priority waiter.
    assert queue[0][1] >= 10**13


def test_a_waiter_that_stops_trying_leaves_the_queue(
    tenant_id: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(redis_rate_window, "WAITER_STALE_SECONDS", 0.2)
    limiter = _short_limiter(tenant_id, limit=1, period_seconds=0.3)
    assert limiter.try_acquire(_API, 1) == 0
    assert limiter.try_acquire(_API, 1, turn=WaitTurn(token="gone")) > 0

    time.sleep(0.35)  # test-flakes: allow the window reads the Redis clock

    assert limiter.try_acquire(_API, 1) == 0


def test_a_stopped_call_gives_up_its_place(tenant_id: str) -> None:
    stop = threading.Event()
    limiter = _short_limiter(
        tenant_id, limit=1, period_seconds=0.5, should_stop=stop.is_set
    )
    limiter.acquire(_API, 1)
    errors: list[BaseException] = []

    def call() -> None:
        try:
            limiter.acquire(_API, 1, bulk=True)
        except ConnectorStopSignal as error:
            errors.append(error)

    thread = threading.Thread(target=call)
    thread.start()
    time.sleep(0.1)  # test-flakes: allow the call takes its place first
    stop.set()
    thread.join(timeout=10)
    assert len(errors) == 1

    time.sleep(0.5)  # test-flakes: allow the window reads the Redis clock
    # No waiter is left before a new call.
    assert limiter.try_acquire(_API, 1) == 0


def test_the_factory_builds_the_drive_limiter_and_wires_the_stop_signal(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Through `build_source_api_limiter`, as `instantiate_connector` calls
    it: off by default, on for Google Drive only, with the budgets from the
    configuration and the caller's stop signal."""
    credential_id = int(uuid4().int % 1_000_000_000)
    monkeypatch.setattr(source_api_limiter, "ENABLE_SOURCE_API_LIMITER", False)
    assert (
        source_api_limiter.build_source_api_limiter(
            DocumentSource.GOOGLE_DRIVE, credential_id
        )
        is None
    )

    monkeypatch.setattr(source_api_limiter, "ENABLE_SOURCE_API_LIMITER", True)
    monkeypatch.setitem(
        source_api_limiter.GOOGLE_DRIVE_BUDGETS,
        "drive",
        source_api_limiter.GOOGLE_DRIVE_BUDGETS["drive"].model_copy(
            # 1800 units a minute is 300 in each 10 s window. Units, whatever
            # quota model the environment sets. The full window from the
            # start: test_source_api_limiter_gates tests the start share.
            update={
                "per_credential": 1800,
                "count_requests": False,
                "start_share": None,
            }
        ),
    )
    assert source_api_limiter.build_source_api_limiter(DocumentSource.SLACK, 1) is None
    stop = False
    limiter = source_api_limiter.build_source_api_limiter(
        DocumentSource.GOOGLE_DRIVE, credential_id, should_stop=lambda: stop
    )
    assert isinstance(limiter, RedisSourceApiLimiter)
    try:
        # Three list pages fill the project window of 300 units.
        for _ in range(3):
            limiter.acquire("drive", 100, "a@x.com")
        assert limiter.try_acquire("drive", 100, "b@x.com") > 0
        # The Docs API has its own budget.
        assert limiter.try_acquire("docs", 1, "a@x.com") == 0

        stop = True
        with pytest.raises(ConnectorStopSignal):
            limiter.acquire("drive", 100, "b@x.com")
    finally:
        for api in ("drive", "docs"):
            for user in ("a@x.com", "b@x.com"):
                for window in (
                    limiter.credential_window(api),
                    limiter.user_window(api, user),
                    limiter.credential_guard(api),
                    limiter.user_guard(api, user),
                ):
                    if window is not None:
                        limiter._windows.delete(window)


def test_an_unreachable_redis_logs_one_warning_and_does_not_limit(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    class _DownRedis:
        def eval(self, *_args: object, **_kwargs: object) -> int:
            raise RedisConnectionError("down")

    monkeypatch.setattr(redis_rate_window, "_last_unreachable_warning", 0.0)
    down = RedisRateWindows(_DownRedis())  # ty: ignore[invalid-argument-type]
    window = RateWindow(key="w", limit=1, period_seconds=10)

    with caplog.at_level("WARNING"):
        assert [down.try_acquire([window]) for _ in range(5)] == [0] * 5
        assert down.report_refusals(window) == RefusalResult(
            share=1.0, applied=False, hard=False, refused_share=0.0
        )

    warnings = [r for r in caplog.records if "cannot reach Redis" in r.getMessage()]
    assert len(warnings) == 1


def test_the_limiter_metrics_show_a_cut_and_the_recovery(
    tenant_id: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(redis_rate_window, "CUT_HOLD_SECONDS", 0.3)
    monkeypatch.setattr(redis_rate_window, "GROW_INTERVAL_SECONDS", 0.1)
    monkeypatch.setattr(redis_rate_window, "GROW_STEP", 0.25)
    monkeypatch.setattr(redis_rate_window, "SLOW_GROW_STEP", 0.25)
    # Only this test's users count toward the user gauges.
    monkeypatch.setattr(
        source_api_metrics, "_user_budgets", source_api_metrics._UserBudgets()
    )
    limiter = RedisSourceApiLimiter(
        tenant_id,
        f"google_drive:{uuid4().hex}",
        {_API: SourceApiBudget(per_credential=1000, per_user=100, period_seconds=10)},
        source=DocumentSource.GOOGLE_DRIVE,
    )

    def sample(name: str, **labels: str) -> float:
        return (
            REGISTRY.get_sample_value(
                name, {"source": "google_drive", "api": _API, **labels}
            )
            or 0.0
        )

    def budget(scope: str) -> float:
        return sample("onyx_source_api_limiter_budget", scope=scope)

    def cuts(scope: str) -> float:
        return sample("onyx_source_api_limiter_cuts_total", scope=scope)

    project_cuts, user_cuts = cuts("project"), cuts("user")
    assert limiter.try_acquire(_API, 1, "a@x.com") == 0
    assert (budget("project"), budget("user")) == (1000, 100)

    # A storm: half of 20 requests refused.
    assert limiter.try_acquire(_API, 0, "a@x.com", request_count=19) == 0
    limiter.report_rate_limit(_API, "a@x.com", user_scope=False, count=10)
    # More pushback for requests sent before the cut does not cut again.
    late = sample("onyx_source_api_limiter_late_refusals_total", scope="project")
    limiter.report_rate_limit(_API, "a@x.com", user_scope=False, count=10)
    assert (
        sample("onyx_source_api_limiter_late_refusals_total", scope="project")
        == late + 10
    )
    limiter.report_rate_limit(_API, "a@x.com", user_scope=True, count=10)
    assert (budget("project"), budget("user")) == (500, 50)
    assert cuts("project") == project_cuts + 1
    assert sample("onyx_source_api_limiter_ceiling") == 500
    assert cuts("user") == user_cuts + 1
    assert sample("onyx_source_api_limiter_cut_users") == 1

    # After the hold, each request reads the grown share.
    time.sleep(0.45)  # test-flakes: allow the window reads the Redis clock
    assert limiter.try_acquire(_API, 1, "a@x.com") == 0
    assert (budget("project"), budget("user")) == (750, 75)


def test_the_limiter_counts_the_time_callers_wait(tenant_id: str) -> None:
    limiter = RedisSourceApiLimiter(
        tenant_id,
        "google_drive:1",
        {_API: SourceApiBudget(per_credential=100, period_seconds=0.4)},
        source=DocumentSource.GOOGLE_DRIVE,
    )

    def waited() -> float:
        return (
            REGISTRY.get_sample_value(
                "onyx_source_api_limiter_wait_seconds_total",
                {"source": "google_drive", "api": _API},
            )
            or 0.0
        )

    before = waited()
    limiter.acquire(_API, 100)
    assert waited() == before
    limiter.acquire(_API, 100)
    assert 0.2 < waited() - before < 2
