"""The adaptive pool grows its worker limit by one per interval while the
service keeps up, halves it on the pushback its tasks record and holds it
through a cooldown, lets a task add work, and raises the first failure after
the running tasks end."""

import threading
import time
from collections.abc import Callable

import pytest

from onyx.utils import threadpool_concurrency
from onyx.utils.threadpool_concurrency import (
    PUSHBACK_OBSERVER,
    AdaptiveConcurrency,
    AdaptiveTaskPool,
    PushbackObserver,
    record_pushback,
)


def _run_all(
    items: list[int], run: Callable[[int], None], concurrency: AdaptiveConcurrency
) -> None:
    pool = AdaptiveTaskPool(concurrency)
    for item in items:
        pool.add(lambda item=item: run(item))
    pool.run()


def test_the_limit_grows_without_pushback_and_halves_on_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(threadpool_concurrency, "ADAPTIVE_COOLDOWN_SECONDS", 0.0)
    monkeypatch.setattr(threadpool_concurrency, "ADAPTIVE_GROW_INTERVAL_SECONDS", 0.0)
    observer = PushbackObserver()
    concurrency = AdaptiveConcurrency(observer, initial=2, maximum=8)

    concurrency.observe()
    concurrency.observe()
    assert concurrency.limit == 4
    for _ in range(3):
        observer.record()
    concurrency.observe()
    assert concurrency.limit == 2
    concurrency.observe()
    assert concurrency.limit == 3


def test_growth_is_paced_by_time_not_by_calls() -> None:
    concurrency = AdaptiveConcurrency(PushbackObserver(), initial=2, maximum=8)
    for _ in range(50):
        concurrency.observe()
    # One growth step lands at once. The rest wait for the interval.
    assert concurrency.limit == 3


def test_a_cut_holds_through_the_cooldown() -> None:
    observer = PushbackObserver()
    concurrency = AdaptiveConcurrency(observer, initial=4, maximum=8)
    observer.record()
    concurrency.observe()
    assert concurrency.limit == 2
    concurrency.observe()
    concurrency.observe()
    assert concurrency.limit == 2


def test_pushback_recorded_in_a_task_cuts_the_limit() -> None:
    observer = PushbackObserver()
    concurrency = AdaptiveConcurrency(observer, initial=4, maximum=4)
    token = PUSHBACK_OBSERVER.set(observer)
    try:
        _run_all([0], lambda _: record_pushback(), concurrency)
    finally:
        PUSHBACK_OBSERVER.reset(token)
    assert concurrency.limit == 2


def test_tasks_run_within_the_limit_and_a_task_may_add_more() -> None:
    concurrency = AdaptiveConcurrency(PushbackObserver(), initial=2, maximum=2)
    pool = AdaptiveTaskPool(concurrency)
    lock = threading.Lock()
    active = 0
    peak = 0
    seen: list[int] = []

    def run(item: int) -> None:
        nonlocal active, peak
        with lock:
            active += 1
            peak = max(peak, active)
        time.sleep(0.01)
        if item < 5:
            pool.add(lambda: run(item + 5))
        with lock:
            active -= 1
            seen.append(item)

    for item in range(5):
        pool.add(lambda item=item: run(item))
    pool.run()

    assert sorted(seen) == list(range(10))
    assert peak == 2


def test_the_limit_grows_while_long_tasks_run(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(threadpool_concurrency, "ADAPTIVE_GROW_INTERVAL_SECONDS", 0.0)
    monkeypatch.setattr(threadpool_concurrency, "ADAPTIVE_POLL_SECONDS", 0.01)
    concurrency = AdaptiveConcurrency(PushbackObserver(), initial=1, maximum=2)
    second_started = threading.Event()

    def long_task() -> None:
        # Ends only once the second task has started beside it.
        assert second_started.wait(timeout=5)

    _run_all(
        [0, 1],
        lambda item: long_task() if item == 0 else second_started.set(),
        concurrency,
    )

    assert concurrency.limit == 2


def test_the_first_failure_stops_new_work_and_is_raised() -> None:
    concurrency = AdaptiveConcurrency(PushbackObserver(), initial=1, maximum=1)
    seen: list[int] = []

    def run(item: int) -> None:
        seen.append(item)
        if item == 1:
            raise RuntimeError("boom")

    with pytest.raises(RuntimeError, match="boom"):
        _run_all([0, 1, 2, 3], run, concurrency)
    assert seen == [0, 1]
