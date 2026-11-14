"""The adaptive pool grows its worker limit by one per interval while the
service keeps up and halves it on pushback. A cut applies to the next task
start. A task can return follow-up tasks. A drain stops new starts and returns
when nothing runs. The first failure is raised after the running tasks end."""

import contextvars
import threading
import time
from collections.abc import Iterator

import pytest

from onyx.utils import threadpool_concurrency
from onyx.utils.threadpool_concurrency import (
    PUSHBACK_OBSERVER,
    AdaptiveConcurrency,
    AdaptiveTask,
    AdaptiveTaskPool,
    PushbackObserver,
    record_pushback,
)

_TEST_VAR: contextvars.ContextVar[str] = contextvars.ContextVar(
    "adaptive_pool_test_var", default="unset"
)


@pytest.fixture
def no_pacing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(threadpool_concurrency, "ADAPTIVE_COOLDOWN_SECONDS", 0.0)
    monkeypatch.setattr(threadpool_concurrency, "ADAPTIVE_GROW_INTERVAL_SECONDS", 0.0)
    monkeypatch.setattr(threadpool_concurrency, "ADAPTIVE_POLL_SECONDS", 0.01)


@pytest.mark.usefixtures("no_pacing")
def test_the_limit_halves_on_pushback_and_recovers() -> None:
    observer = PushbackObserver()
    concurrency = AdaptiveConcurrency(observer, initial=2, maximum=8)

    concurrency.observe()
    concurrency.observe()
    assert concurrency.limit == 4
    for _ in range(3):
        observer.record()
    concurrency.observe()
    # One burst of pushback is one cut, however many hits it has.
    assert concurrency.limit == 2
    concurrency.observe()
    assert concurrency.limit == 3


def test_growth_is_paced_by_time_not_by_calls() -> None:
    now = 100.0
    concurrency = AdaptiveConcurrency(
        PushbackObserver(), initial=2, maximum=8, clock=lambda: now
    )
    # The initial limit holds for the first interval.
    for _ in range(50):
        concurrency.observe()
    assert concurrency.limit == 2
    now += threadpool_concurrency.ADAPTIVE_GROW_INTERVAL_SECONDS
    for _ in range(50):
        concurrency.observe()
    assert concurrency.limit == 3
    now += threadpool_concurrency.ADAPTIVE_GROW_INTERVAL_SECONDS
    concurrency.observe()
    assert concurrency.limit == 4


def test_a_cut_holds_through_the_cooldown() -> None:
    observer = PushbackObserver()
    concurrency = AdaptiveConcurrency(observer, initial=4, maximum=8)
    observer.record()
    concurrency.observe()
    assert concurrency.limit == 2
    concurrency.observe()
    assert concurrency.limit == 2


def test_the_limit_stays_between_one_and_the_maximum() -> None:
    observer = PushbackObserver()
    concurrency = AdaptiveConcurrency(observer, initial=500, maximum=4)
    assert concurrency.limit == 4
    for _ in range(5):
        observer.record()
        concurrency.observe()
    assert concurrency.limit == 1


def test_a_cut_applies_to_the_next_task_start() -> None:
    """Short tasks, as one page each. Pushback comes while the first eight
    run. Each later task starts with no more than the cut limit running."""
    observer = PushbackObserver()
    concurrency = AdaptiveConcurrency(observer, initial=8, maximum=8)
    pool = AdaptiveTaskPool(concurrency)
    lock = threading.Lock()
    first_wave = threading.Barrier(8, timeout=5)
    active = 0
    peak_after_cut = 0

    def page(index: int) -> None:
        nonlocal active, peak_after_cut
        with lock:
            active += 1
            if index >= 8:
                peak_after_cut = max(peak_after_cut, active)
        if index < 8:
            first_wave.wait()
            if index == 0:
                record_pushback()
        time.sleep(0.02)
        with lock:
            active -= 1

    token = PUSHBACK_OBSERVER.set(observer)
    try:
        for index in range(40):
            pool.add(lambda index=index: page(index))
        pool.run()
    finally:
        PUSHBACK_OBSERVER.reset(token)

    # The cooldown holds the limit at 4 for the whole run.
    assert concurrency.limit == 4
    assert 0 < peak_after_cut <= 4


class _PushbackAfterFirstStart(PushbackObserver):
    """Reports pushback at the second read: a task of the batch that is
    starting saw it."""

    def __init__(self) -> None:
        super().__init__()
        self.reads = 0

    def take_hits(self) -> int:
        self.reads += 1
        return 1 if self.reads == 2 else 0


def test_pushback_cuts_the_batch_that_is_starting() -> None:
    concurrency = AdaptiveConcurrency(_PushbackAfterFirstStart(), initial=8, maximum=8)
    pool = AdaptiveTaskPool(concurrency)
    lock = threading.Lock()
    active = 0
    peak = 0

    def page() -> None:
        nonlocal active, peak
        with lock:
            active += 1
            peak = max(peak, active)
        time.sleep(0.05)
        with lock:
            active -= 1

    for _ in range(8):
        pool.add(page)
    pool.run()

    assert concurrency.limit == 4
    assert peak <= 4


def test_a_task_can_return_follow_up_tasks() -> None:
    concurrency = AdaptiveConcurrency(PushbackObserver(), initial=2, maximum=2)
    pool = AdaptiveTaskPool(concurrency)
    lock = threading.Lock()
    active = 0
    peak = 0
    seen: list[tuple[int, int]] = []

    def page(shard: int, page_number: int) -> list[AdaptiveTask] | None:
        nonlocal active, peak
        with lock:
            active += 1
            peak = max(peak, active)
        time.sleep(0.005)
        with lock:
            active -= 1
            seen.append((shard, page_number))
        if page_number < 2:
            return [lambda: page(shard, page_number + 1)]
        return None

    for shard in range(4):
        pool.add(lambda shard=shard: page(shard, 0))
    pool.run()

    assert sorted(seen) == [(shard, n) for shard in range(4) for n in range(3)]
    assert peak == 2
    assert pool.pending_count == 0


def test_drain_stops_new_starts_and_returns_with_nothing_running() -> None:
    concurrency = AdaptiveConcurrency(PushbackObserver(), initial=3, maximum=3)
    pool = AdaptiveTaskPool(concurrency)
    lock = threading.Lock()
    active = 0
    started = 0

    def page() -> list[AdaptiveTask]:
        nonlocal active, started
        with lock:
            active += 1
            started += 1
            if started == 3:
                pool.drain()
        time.sleep(0.02)
        with lock:
            active -= 1
        return [page]

    for _ in range(6):
        pool.add(page)
    pool.run()

    assert active == 0
    # The first three tasks ran. Their follow-ups and the other three wait.
    assert started == 3
    assert pool.pending_count == 6


def test_the_limit_is_readable_and_starts_the_next_pool() -> None:
    observer = PushbackObserver()
    first = AdaptiveTaskPool(AdaptiveConcurrency(observer, initial=8, maximum=8))
    token = PUSHBACK_OBSERVER.set(observer)
    try:
        first.add(record_pushback)
        first.run()
    finally:
        PUSHBACK_OBSERVER.reset(token)
    assert first.limit == 4

    second = AdaptiveTaskPool(AdaptiveConcurrency(PushbackObserver(), first.limit, 8))
    assert second.limit == 4


def test_context_variables_reach_worker_threads() -> None:
    observer = PushbackObserver()
    concurrency = AdaptiveConcurrency(observer, initial=2, maximum=2)
    pool = AdaptiveTaskPool(concurrency)
    seen: list[tuple[str, bool]] = []

    def task() -> list[AdaptiveTask]:
        seen.append((_TEST_VAR.get(), PUSHBACK_OBSERVER.get() is observer))
        # A follow-up starts from the pool's thread and gets the same context.
        return [lambda: seen.append((_TEST_VAR.get(), True))]

    var_token = _TEST_VAR.set("tenant-a")
    observer_token = PUSHBACK_OBSERVER.set(observer)
    try:
        pool.add(task)
        pool.run()
    finally:
        PUSHBACK_OBSERVER.reset(observer_token)
        _TEST_VAR.reset(var_token)

    assert seen == [("tenant-a", True), ("tenant-a", True)]


@pytest.mark.usefixtures("no_pacing")
def test_the_limit_grows_while_long_tasks_run() -> None:
    concurrency = AdaptiveConcurrency(PushbackObserver(), initial=1, maximum=2)
    pool = AdaptiveTaskPool(concurrency)
    second_started = threading.Event()

    def long_task() -> None:
        # Ends only after the second task starts beside it.
        if not second_started.wait(timeout=5):
            raise RuntimeError("the second task did not start")

    pool.add(long_task)
    pool.add(second_started.set)
    pool.run()

    assert concurrency.limit == 2


def test_the_first_failure_stops_new_work_and_is_raised() -> None:
    concurrency = AdaptiveConcurrency(PushbackObserver(), initial=1, maximum=1)
    pool = AdaptiveTaskPool(concurrency)
    seen: list[int] = []

    def run(item: int) -> None:
        seen.append(item)
        if item == 1:
            raise RuntimeError("boom")

    for item in range(4):
        pool.add(lambda item=item: run(item))
    with pytest.raises(RuntimeError, match="boom"):
        pool.run()
    assert seen == [0, 1]


def test_a_failing_follow_up_generator_waits_for_running_tasks() -> None:
    concurrency = AdaptiveConcurrency(PushbackObserver(), initial=2, maximum=2)
    pool = AdaptiveTaskPool(concurrency)
    slow_task_ended = threading.Event()
    started: list[str] = []

    def slow() -> None:
        started.append("slow")
        time.sleep(0.2)
        slow_task_ended.set()

    def follow_ups() -> Iterator[AdaptiveTask]:
        started.append("generator")
        raise RuntimeError("boom")
        yield slow

    pool.add(slow)
    pool.add(follow_ups)
    pool.add(lambda: started.append("late"))
    with pytest.raises(RuntimeError, match="boom"):
        pool.run()

    # The pool raised only after the running task ended, and started nothing
    # after the failure.
    assert slow_task_ended.is_set()
    assert "late" not in started


def test_worker_threads_are_reused() -> None:
    concurrency = AdaptiveConcurrency(PushbackObserver(), initial=2, maximum=2)
    pool = AdaptiveTaskPool(concurrency)
    threads: set[int] = set()
    lock = threading.Lock()

    def page() -> None:
        with lock:
            threads.add(threading.get_ident())

    for _ in range(20):
        pool.add(page)
    pool.run()

    assert len(threads) <= 2
