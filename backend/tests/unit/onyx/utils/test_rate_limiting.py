import threading
import time

from onyx.utils.rate_limiting import ThreadSafeRateLimiter


def test_rate_limit_basic() -> None:
    """Test that rate limiting works for sequential calls."""
    call_count = 0

    @ThreadSafeRateLimiter(max_calls=2, period=0.5, name="test_basic")
    def func() -> None:
        nonlocal call_count
        call_count += 1

    start = time.monotonic()

    # First 2 calls should be immediate
    func()
    func()
    time_after_first_batch = time.monotonic() - start

    # Third call should be rate-limited (wait ~0.5s)
    func()
    time_after_rate_limited = time.monotonic() - start

    assert call_count == 3
    assert time_after_first_batch < 0.1  # First 2 calls should be fast
    assert time_after_rate_limited >= 0.4  # Third call should wait


def test_rate_limit_thread_safety() -> None:
    """Test that rate limiting works correctly across multiple threads."""
    call_times: list[float] = []
    lock = threading.Lock()

    limiter = ThreadSafeRateLimiter(max_calls=2, period=0.5, name="test_threads")

    def make_call() -> None:
        limiter.acquire()
        with lock:
            call_times.append(time.monotonic())

    # Start 6 threads simultaneously
    threads = [threading.Thread(target=make_call) for _ in range(6)]
    start = time.monotonic()

    for t in threads:
        t.start()
    for t in threads:
        t.join()

    end = time.monotonic()

    # 6 calls with 2 per 0.5s should take at least 1 second
    # (first 2 immediate, next 2 at 0.5s, final 2 at 1.0s)
    assert len(call_times) == 6
    assert end - start >= 0.9  # Allow small timing tolerance

    # Verify calls are properly spaced
    relative_times = sorted([t - start for t in call_times])

    # First 2 calls should be near 0
    assert relative_times[0] < 0.1
    assert relative_times[1] < 0.1

    # Next 2 calls should be around 0.5s
    assert 0.4 <= relative_times[2] <= 0.7
    assert 0.4 <= relative_times[3] <= 0.7

    # Final 2 calls should be around 1.0s
    assert 0.9 <= relative_times[4] <= 1.2
    assert 0.9 <= relative_times[5] <= 1.2


def test_rate_limit_decorator_on_method() -> None:
    """Test that the rate limiter works as a decorator on class methods."""
    limiter = ThreadSafeRateLimiter(max_calls=2, period=0.5, name="test_method")

    class MyClient:
        def __init__(self) -> None:
            self.call_count = 0

        @limiter
        def do_work(self) -> int:
            self.call_count += 1
            return self.call_count

    client = MyClient()
    start = time.monotonic()

    # First 2 calls should be immediate
    assert client.do_work() == 1
    assert client.do_work() == 2
    time_first_batch = time.monotonic() - start

    # Third call should be rate-limited
    assert client.do_work() == 3
    time_after_limited = time.monotonic() - start

    assert time_first_batch < 0.1
    assert time_after_limited >= 0.4


def test_rate_limit_acquire_timeout() -> None:
    """Test that acquire() respects timeout parameter."""
    limiter = ThreadSafeRateLimiter(max_calls=1, period=10.0, name="test_timeout")

    # First acquire should succeed immediately
    assert limiter.acquire(timeout=0.1) is True

    # Second acquire should timeout (slot won't be available for 10s)
    start = time.monotonic()
    assert limiter.acquire(timeout=0.2) is False
    elapsed = time.monotonic() - start

    # Should have waited approximately the timeout duration
    assert 0.15 <= elapsed <= 0.4


def test_rate_limit_sliding_window() -> None:
    """Test that the sliding window correctly expires old calls."""
    limiter = ThreadSafeRateLimiter(max_calls=2, period=0.3, name="test_sliding")

    start = time.monotonic()

    # Use up both slots
    limiter.acquire()
    limiter.acquire()

    # Wait for slots to expire
    time.sleep(0.35)

    # Should be able to acquire again immediately
    limiter.acquire()
    elapsed = time.monotonic() - start

    # Third acquire should happen right after sleep, not delayed further
    assert elapsed < 0.5
