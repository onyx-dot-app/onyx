import asyncio
import threading
from unittest.mock import patch

import pytest

from onyx.utils.adaptive_semaphore import AdaptiveSemaphore


def test_limit_holds_across_threads_and_loops() -> None:
    semaphore = AdaptiveSemaphore(initial=3, minimum=1, maximum=3)
    acquired = threading.Semaphore(0)
    release_all = threading.Event()

    async def one() -> None:
        await semaphore.acquire()
        try:
            acquired.release()
            await asyncio.to_thread(release_all.wait, 10)
        finally:
            semaphore.release()

    async def many() -> None:
        await asyncio.gather(*(one() for _ in range(5)))

    threads = [threading.Thread(target=asyncio.run, args=(many(),)) for _ in range(4)]
    for thread in threads:
        thread.start()

    try:
        for _ in range(3):
            assert acquired.acquire(timeout=10)
        assert semaphore.in_flight == 3
        assert not acquired.acquire(timeout=0.2)
    finally:
        release_all.set()
        for thread in threads:
            thread.join(timeout=10)
    assert semaphore.in_flight == 0


def test_slow_start_then_additive_increase() -> None:
    semaphore = AdaptiveSemaphore(initial=2, minimum=1, maximum=100)
    for _ in range(4):
        semaphore.record_success()
    assert semaphore.limit == 6

    semaphore.record_rate_limit()
    assert semaphore.limit == 4  # 6 * 0.7
    for _ in range(4):
        semaphore.record_success()
    assert semaphore.limit == 5  # additive: +1 per `limit` successes


def test_rate_limits_cut_once_per_cooldown() -> None:
    semaphore = AdaptiveSemaphore(
        initial=50, minimum=1, maximum=100, decrease_cooldown_seconds=60
    )
    # A clock below the cooldown must not hide the first cut.
    with patch("onyx.utils.adaptive_semaphore.time.monotonic", return_value=1.0):
        for _ in range(10):
            semaphore.record_rate_limit()
    assert semaphore.limit == 35


def test_limit_stays_within_bounds() -> None:
    semaphore = AdaptiveSemaphore(
        initial=2, minimum=2, maximum=4, decrease_cooldown_seconds=0
    )
    for _ in range(10):
        semaphore.record_rate_limit()
    assert semaphore.limit == 2
    for _ in range(100):
        semaphore.record_success()
    assert semaphore.limit == 4


def test_cancelled_waiter_gives_back_its_slot() -> None:
    semaphore = AdaptiveSemaphore(initial=1, minimum=1, maximum=1)

    async def scenario() -> None:
        await semaphore.acquire()
        waiter = asyncio.create_task(semaphore.acquire())
        await asyncio.sleep(0)  # test-flakes: allow yields once so the waiter queues
        waiter.cancel()
        with pytest.raises(asyncio.CancelledError):
            await waiter
        semaphore.release()
        await asyncio.wait_for(semaphore.acquire(), timeout=1)
        semaphore.release()

    asyncio.run(scenario())
    assert semaphore.in_flight == 0


@pytest.mark.parametrize("grant_arrives_before_the_cancel", [False, True])
def test_slot_granted_then_cancelled_is_given_back(
    grant_arrives_before_the_cancel: bool,
) -> None:
    semaphore = AdaptiveSemaphore(initial=1, minimum=1, maximum=1)

    async def scenario() -> None:
        await semaphore.acquire()
        waiter = asyncio.create_task(semaphore.acquire())
        await asyncio.sleep(0)  # test-flakes: allow yields once so the waiter queues
        semaphore.release()  # grants the waiter its slot before it runs
        if grant_arrives_before_the_cancel:
            # The waiter's future has its result, but the waiter has not run.
            await asyncio.sleep(0)  # test-flakes: allow yields once so the grant runs
        waiter.cancel()
        with pytest.raises(asyncio.CancelledError):
            await waiter
        await asyncio.wait_for(semaphore.acquire(), timeout=1)
        semaphore.release()

    asyncio.run(scenario())
    assert semaphore.in_flight == 0
