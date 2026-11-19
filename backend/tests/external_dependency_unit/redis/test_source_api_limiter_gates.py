"""The per-process gates of the source-API limiter, the bounded work of one
try, and the stored share, against a real Redis.

Each test uses a unique tenant, so runs cannot collide."""

import threading
import time
from collections.abc import Callable, Iterator
from uuid import uuid4

import pytest

from onyx.configs.constants import DocumentSource
from onyx.connectors import source_api_limiter
from onyx.connectors.models import ConnectorStopSignal
from onyx.connectors.source_api_limiter import RedisSourceApiLimiter, SourceApiBudget
from onyx.redis import redis_rate_window
from onyx.redis.redis_pool import get_redis_client
from onyx.redis.redis_rate_window import (
    RateWindow,
    RedisRateWindows,
    WindowStart,
    stored_share_key,
)

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


def _eval_calls() -> int:
    """The scripts that the test Redis ran, for all clients."""
    stats = get_redis_client(tenant_id="tenant_stats").info("commandstats")
    return sum(
        int(stats.get(name, {}).get("calls", 0))
        for name in ("cmdstat_eval", "cmdstat_evalsha")
    )


# The stored share (Fix 2: no start storm at the full budget).


def test_a_window_with_no_stored_share_starts_at_its_start_share(
    windows: RedisRateWindows,
) -> None:
    window = RateWindow(key="w", limit=100, period_seconds=10, start_share=0.25)

    first = windows.try_acquire_with_shares([window], cost=25)

    assert (first.wait_seconds, first.shares, first.starts) == (
        0,
        [0.25],
        [WindowStart.COLD],
    )
    # A quarter of the limit is taken: the window is full.
    later = windows.try_acquire_with_shares([window], cost=1)
    assert later.wait_seconds > 0
    assert later.starts == [WindowStart.NONE]


def test_a_window_with_no_start_share_starts_at_its_full_limit(
    windows: RedisRateWindows,
) -> None:
    window = RateWindow(key="w", limit=100, period_seconds=10)
    result = windows.try_acquire_with_shares([window], cost=100)
    assert (result.wait_seconds, result.shares, result.starts) == (
        0,
        [1.0],
        [WindowStart.NONE],
    )


def test_a_new_run_starts_from_the_share_stored_at_the_last_cut(
    tenant_id: str, windows: RedisRateWindows
) -> None:
    window = RateWindow(key="w", limit=1000, period_seconds=10, start_share=0.5)
    assert windows.try_acquire_with_shares([window], cost=0, requests=100).shares == [
        0.5
    ]
    # A storm: Google refused 70 of 100 requests. The cut stores its share.
    cut = windows.report_refusals(window, count=70)
    assert cut.applied
    client = get_redis_client(tenant_id=tenant_id)
    stored = client.get(stored_share_key(window))
    assert stored is not None and float(stored) == cut.share
    assert client.pttl(stored_share_key(window)) > 600_000

    # The window's state expires with the run. The stored share stays.
    client.delete("w:log", "w:meta", "w:queue", "w:seen")
    restarted = windows.try_acquire_with_shares([window], cost=0)

    assert restarted.starts == [WindowStart.STORED]
    assert restarted.shares == [cut.share]
    # The service accepted the stored share, so the window grows slowly
    # from it.
    assert float(client.hget("w:meta", "ceiling") or 0) == cut.share


def test_the_window_stores_its_share_when_it_grows(
    tenant_id: str, windows: RedisRateWindows, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(redis_rate_window, "GROW_INTERVAL_SECONDS", 0.1)
    window = RateWindow(key="w", limit=1000, period_seconds=10, start_share=0.25)
    assert windows.try_acquire_with_shares([window], cost=0).shares == [0.25]

    time.sleep(0.15)  # test-flakes: allow the window reads the Redis clock
    grown = windows.try_acquire_with_shares([window], cost=0).shares[0]

    assert grown == 0.3
    stored = get_redis_client(tenant_id=tenant_id).get(stored_share_key(window))
    assert stored is not None and float(stored) == grown


def test_the_google_budgets_start_the_project_window_at_a_quarter(
    tenant_id: str,
) -> None:
    budget = source_api_limiter.GOOGLE_DRIVE_BUDGETS["drive"].model_copy(
        update={"per_credential": 600, "per_user": 600, "count_requests": True}
    )
    limiter = RedisSourceApiLimiter(
        tenant_id,
        f"google_drive:{uuid4().hex}",
        {_API: budget},
        source=DocumentSource.GOOGLE_DRIVE,
    )
    project = limiter.credential_window(_API)
    user = limiter.user_window(_API, "a@x.com")
    assert project is not None and project.start_share == 0.25
    # Only the project window starts low; the user windows and the guards
    # start at their limit.
    assert user is not None and user.start_share is None

    # 600 a minute is 100 in each 10 s window; a cold start allows 25.
    taken = sum(1 for _ in range(40) if limiter.try_acquire(_API, 1, "a@x.com") == 0)
    assert taken == 25


# Bounded work for each try.


def test_the_wait_is_found_without_reading_the_whole_log(
    windows: RedisRateWindows,
) -> None:
    """A window that holds many requests after a cut answers with the time
    when enough of them leave, with a few reads of the log."""
    window = RateWindow(key="w", limit=50_000, period_seconds=2)
    for _ in range(100):
        assert windows.try_acquire([window], cost=1) == 0
    time.sleep(0.5)  # test-flakes: allow two groups of requests apart in time
    for _ in range(100):
        assert windows.try_acquire([window], cost=300) == 0
    # A storm cut takes the share to the floor of 0.1: 5,000 units are
    # allowed, and the log holds 30,100.
    windows.report_refusals(window, count=10_000)
    assert windows.try_acquire_with_shares([window], cost=0).shares == [0.1]

    wait = windows.try_acquire([window], cost=10)

    # The first 100 requests free only 100 units: the caller waits for the
    # second group, which leaves 2 s after it came.
    assert 1.2 < wait <= 2.0


def test_the_wait_reads_a_log_of_the_older_form(
    tenant_id: str, windows: RedisRateWindows
) -> None:
    """Requests logged by the code before this one have no running count of
    units. The wait then counts one unit for each of them."""
    client = get_redis_client(tenant_id=tenant_id)
    window = RateWindow(key="w", limit=3, period_seconds=10)
    now_ms = int(time.time() * 1000)
    client.zadd("w:log", {f"{now_ms}:1:1": now_ms, f"{now_ms + 1}:2:1": now_ms + 1})
    client.zadd("w:log", {f"{now_ms + 2}:3:1": now_ms + 2})
    client.hset("w:meta", "total", 3)

    wait = windows.try_acquire([window], cost=1)

    assert 9 < wait <= 10


# The gates: one Redis waiter for each process and class.


def _limiter(
    tenant_id: str,
    limit: int,
    period_seconds: float,
    per_user: int | None = None,
    should_stop: Callable[[], bool] | None = None,
) -> RedisSourceApiLimiter:
    return RedisSourceApiLimiter(
        tenant_id,
        "google_drive:1",
        {
            _API: SourceApiBudget(
                per_credential=limit,
                per_user=per_user,
                period_seconds=period_seconds,
            )
        },
        should_stop,
        source=DocumentSource.GOOGLE_DRIVE,
    )


def test_the_threads_of_one_process_hold_one_place_in_redis(
    tenant_id: str,
) -> None:
    stop = threading.Event()
    limiter = _limiter(tenant_id, limit=1, period_seconds=30, should_stop=stop.is_set)
    limiter.acquire(_API, 1)
    window = limiter.credential_window(_API)
    assert window is not None
    client = get_redis_client(tenant_id=tenant_id)

    def call(bulk: bool) -> None:
        try:
            limiter.acquire(_API, 1, bulk=bulk)
        except ConnectorStopSignal:
            pass

    threads = [
        threading.Thread(target=call, args=(index % 4 != 0,)) for index in range(40)
    ]
    for thread in threads:
        thread.start()
    queued: list[int] = []
    for _ in range(20):
        time.sleep(0.05)  # test-flakes: allow the threads take their places
        queued.append(client.zcard(f"{window.key}:queue"))
    stop.set()
    for thread in threads:
        thread.join(timeout=10)

    # 40 threads wait: one place for the bulk class and one for the others.
    assert max(queued) == 2, queued
    assert all(not thread.is_alive() for thread in threads)


def test_a_waiting_process_tries_about_once_for_each_slot(tenant_id: str) -> None:
    """The head of a gate sleeps until Redis says its slot is due, and the
    other threads do not call Redis. Before the gates, each of the 50 threads
    tried again whenever its own wait ended."""
    stop = threading.Event()
    limiter = _limiter(tenant_id, limit=1, period_seconds=0.25, should_stop=stop.is_set)
    taken: list[float] = []
    lock = threading.Lock()

    def call() -> None:
        while not stop.is_set():
            try:
                limiter.acquire(_API, 1, bulk=True)
            except ConnectorStopSignal:
                return
            with lock:
                taken.append(time.monotonic())

    before = _eval_calls()
    threads = [threading.Thread(target=call) for _ in range(50)]
    for thread in threads:
        thread.start()
    stop.wait(2.0)
    stop.set()
    calls = _eval_calls() - before
    for thread in threads:
        thread.join(timeout=10)

    # About 8 slots in 2 s. Each slot costs a few tries: the try that waits,
    # the try that takes it, and the try of the next head.
    assert 5 <= len(taken) <= 10, len(taken)
    assert calls <= 6 * len(taken) + 10, (calls, len(taken))


def test_the_calls_of_a_gate_take_their_slots_in_turn(tenant_id: str) -> None:
    limiter = _limiter(tenant_id, limit=5, period_seconds=0.3)
    done: list[int] = []
    lock = threading.Lock()

    def call(index: int) -> None:
        limiter.acquire(_API, 1, bulk=True)
        with lock:
            done.append(index)

    started = time.monotonic()
    threads = [threading.Thread(target=call, args=(index,)) for index in range(30)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=30)

    # 30 calls at 5 in each 0.3 s window: about 1.5 s, and none is lost.
    assert sorted(done) == list(range(30))
    assert 1.2 < time.monotonic() - started < 5


def test_a_call_that_only_its_user_blocks_does_not_hold_up_the_gate(
    tenant_id: str,
) -> None:
    stop = threading.Event()
    limiter = _limiter(
        tenant_id,
        limit=1000,
        period_seconds=30,
        per_user=1,
        should_stop=stop.is_set,
    )
    # User A's window is full for 30 s.
    limiter.acquire(_API, 1, "a@x.com")
    blocked = threading.Thread(
        target=lambda: pytest.raises(
            ConnectorStopSignal, limiter.acquire, _API, 1, "a@x.com", bulk=True
        )
    )
    blocked.start()
    time.sleep(0.2)  # test-flakes: allow user A's call to wait first

    started = time.monotonic()
    limiter.acquire(_API, 1, "b@x.com", bulk=True)
    elapsed = time.monotonic() - started
    stop.set()
    blocked.join(timeout=10)

    assert elapsed < 1, elapsed


def test_a_call_behind_the_head_still_takes_its_slot_after_the_longest_wait(
    tenant_id: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(source_api_limiter, "MAX_WAIT_SECONDS", 0.4)
    limiter = _limiter(tenant_id, limit=1, period_seconds=30)
    limiter.acquire(_API, 1)
    durations: list[float] = []
    lock = threading.Lock()

    def call() -> None:
        started = time.monotonic()
        limiter.acquire(_API, 1, bulk=True)
        with lock:
            durations.append(time.monotonic() - started)

    threads = [threading.Thread(target=call) for _ in range(5)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=10)

    assert len(durations) == 5
    assert all(0.4 <= duration < 3 for duration in durations), durations
