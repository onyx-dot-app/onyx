"""The shared rate windows and the source-API limiter against a real Redis.

Each test uses a unique tenant, so runs cannot collide. Separate limiter
objects, and a separate process, stand in for separate worker pods: they share
only Redis."""

import subprocess
import sys
import time
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

import pytest

from onyx.background.indexing import source_api_limiter
from onyx.background.indexing.source_api_limiter import (
    RedisSourceApiLimiter,
    SourceApiBudget,
)
from onyx.connectors.models import ConnectorStopSignal
from onyx.redis import redis_rate_window
from onyx.redis.redis_pool import get_redis_client
from onyx.redis.redis_rate_window import RateWindow, RedisRateWindows

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

    time.sleep(wait + 0.05)

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


def test_a_cut_halves_the_window_once_for_each_burst_and_grows_back(
    windows: RedisRateWindows, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(redis_rate_window, "CUT_HOLD_SECONDS", 0.3)
    monkeypatch.setattr(redis_rate_window, "GROW_INTERVAL_SECONDS", 0.1)
    monkeypatch.setattr(redis_rate_window, "GROW_STEP", 0.25)
    window = RateWindow(key="w", limit=100, period_seconds=0.2)

    assert windows.cut(window) == 0.5
    # More pushback in the same burst does not cut again.
    assert windows.cut(window) == 0.5
    assert windows.try_acquire([window], cost=50) == 0
    assert windows.try_acquire([window], cost=1) > 0

    # After the hold, the share grows by one step for each interval.
    time.sleep(0.45)
    assert windows.try_acquire([window], cost=75) == 0
    time.sleep(0.25)
    assert windows.try_acquire([window], cost=100) == 0
    assert windows.cut(window) == 0.5


def test_a_cut_stops_at_the_lowest_share(
    windows: RedisRateWindows, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(redis_rate_window, "CUT_HOLD_SECONDS", 0.0)
    window = RateWindow(key="w", limit=100, period_seconds=10)
    shares = [windows.cut(window) for _ in range(6)]
    assert shares == [0.5, 0.25, 0.125, 0.1, 0.1, 0.1]


def test_two_processes_share_one_budget(tenant_id: str) -> None:
    """Another process spends 800 of 1000 units. This process then has 200."""
    code = (
        "from onyx.background.indexing.source_api_limiter import "
        "RedisSourceApiLimiter, SourceApiBudget\n"
        f"limiter = RedisSourceApiLimiter({tenant_id!r}, 'google_drive:1', "
        "{'drive': SourceApiBudget(per_credential=1000, per_user=None, "
        "period_seconds=10)})\n"
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

    # Google answered 403 userRateLimitExceeded for user A.
    limiter.report_rate_limit(_API, "a@x.com", user_scope=True)

    assert limiter.try_acquire(_API, 500, "a@x.com") == 0
    assert limiter.try_acquire(_API, 100, "a@x.com") > 0
    assert limiter.try_acquire(_API, 1000, "b@x.com") == 0


def test_a_project_cut_slows_every_user(tenant_id: str) -> None:
    limiter = _limiter(tenant_id, per_credential=1000, per_user=1000)

    limiter.report_rate_limit(_API, "a@x.com", user_scope=False)

    assert limiter.try_acquire(_API, 300, "a@x.com") == 0
    assert limiter.try_acquire(_API, 200, "b@x.com") == 0
    assert limiter.try_acquire(_API, 100, "c@x.com") > 0


def test_the_requests_model_counts_each_call_as_one(tenant_id: str) -> None:
    limiter = _limiter(tenant_id, per_credential=2, per_user=None, count_requests=True)
    assert limiter.try_acquire(_API, 200, "a@x.com") == 0
    assert limiter.try_acquire(_API, 5, "a@x.com") == 0
    assert limiter.try_acquire(_API, 5, "a@x.com") > 0


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
    )
    limiter.acquire(_API, 100)
    with pytest.raises(ConnectorStopSignal):
        limiter.acquire(_API, 100)


def test_a_call_goes_on_after_the_longest_wait(
    tenant_id: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(source_api_limiter, "MAX_WAIT_SECONDS", 0.3)
    limiter = _limiter(tenant_id, per_credential=100, per_user=None)
    limiter.acquire(_API, 100)
    started = time.monotonic()
    limiter.acquire(_API, 100)
    assert 0.3 <= time.monotonic() - started < 3
