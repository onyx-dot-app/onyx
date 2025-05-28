import contextvars
import threading
import time
from collections.abc import Generator
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor

import pytest

from onyx.utils.threadpool_concurrency import parallel_yield
from onyx.utils.threadpool_concurrency import run_in_background
from onyx.utils.threadpool_concurrency import run_with_timeout
from onyx.utils.threadpool_concurrency import ThreadSafeDict
from onyx.utils.threadpool_concurrency import wait_on_background

# Create a context variable for testing
test_context_var = contextvars.ContextVar("test_var", default="default")


def test_run_with_timeout_completes() -> None:
    """Test that a function that completes within timeout works correctly"""

    def quick_function(x: int) -> int:
        return x * 2

    result = run_with_timeout(1.0, quick_function, x=21)
    assert result == 42


@pytest.mark.parametrize("slow,timeout", [(1, 0.1), (0.3, 0.2)])
def test_run_with_timeout_raises_on_timeout(slow: float, timeout: float) -> None:
    """Test that a function that exceeds timeout raises TimeoutError"""

    def slow_function() -> None:
        time.sleep(slow)  # Sleep for 2 seconds

    with pytest.raises(TimeoutError) as exc_info:
        start = time.time()
        run_with_timeout(timeout, slow_function)  # Set timeout to 0.1 seconds
        end = time.time()
        assert end - start >= timeout
        assert end - start < (slow + timeout) / 2
    assert f"timed out after {timeout} seconds" in str(exc_info.value)


@pytest.mark.filterwarnings("ignore::pytest.PytestUnhandledThreadExceptionWarning")
def test_run_with_timeout_propagates_exceptions() -> None:
    """Test that other exceptions from the function are propagated properly"""

    def error_function() -> None:
        raise ValueError("Test error")

    with pytest.raises(ValueError) as exc_info:
        run_with_timeout(1.0, error_function)

    assert "Test error" in str(exc_info.value)


def test_run_with_timeout_with_args_and_kwargs() -> None:
    """Test that args and kwargs are properly passed to the function"""

    def complex_function(x: int, y: int, multiply: bool = False) -> int:
        if multiply:
            return x * y
        return x + y

    # Test with just positional args
    result1 = run_with_timeout(1.0, complex_function, x=5, y=3)
    assert result1 == 8

    # Test with positional and keyword args
    result2 = run_with_timeout(1.0, complex_function, x=5, y=3, multiply=True)
    assert result2 == 15


def test_run_in_background_and_wait_success() -> None:
    """Test that run_in_background and wait_on_background work correctly for successful execution"""

    def background_function(x: int) -> int:
        time.sleep(0.1)  # Small delay to ensure it's actually running in background
        return x * 2

    # Start the background task
    task = run_in_background(background_function, 21)

    # Verify we can do other work while task is running
    start_time = time.time()
    result = wait_on_background(task)
    elapsed = time.time() - start_time

    assert result == 42
    # sometimes slightly flaky
    assert elapsed >= 0.095  # Verify we actually waited for the sleep


@pytest.mark.filterwarnings("ignore::pytest.PytestUnhandledThreadExceptionWarning")
def test_run_in_background_propagates_exceptions() -> None:
    """Test that exceptions in background tasks are properly propagated"""

    def error_function() -> None:
        time.sleep(0.1)  # Small delay to ensure it's actually running in background
        raise ValueError("Test background error")

    task = run_in_background(error_function)

    with pytest.raises(ValueError) as exc_info:
        wait_on_background(task)

    assert "Test background error" in str(exc_info.value)


def test_run_in_background_with_args_and_kwargs() -> None:
    """Test that args and kwargs are properly passed to the background function"""

    def complex_function(x: int, y: int, multiply: bool = False) -> int:
        time.sleep(0.1)  # Small delay to ensure it's actually running in background
        if multiply:
            return x * y
        return x + y

    # Test with args
    task1 = run_in_background(complex_function, 5, 3)
    result1 = wait_on_background(task1)
    assert result1 == 8

    # Test with args and kwargs
    task2 = run_in_background(complex_function, 5, 3, multiply=True)
    result2 = wait_on_background(task2)
    assert result2 == 15


def test_multiple_background_tasks() -> None:
    """Test running multiple background tasks concurrently"""

    def slow_add(x: int, y: int) -> int:
        time.sleep(0.2)  # Make each task take some time
        return x + y

    # Start multiple tasks
    start_time = time.time()
    task1 = run_in_background(slow_add, 1, 2)
    task2 = run_in_background(slow_add, 3, 4)
    task3 = run_in_background(slow_add, 5, 6)

    # Wait for all results
    result1 = wait_on_background(task1)
    result2 = wait_on_background(task2)
    result3 = wait_on_background(task3)
    elapsed = time.time() - start_time

    # Verify results
    assert result1 == 3
    assert result2 == 7
    assert result3 == 11

    # Verify tasks ran in parallel (total time should be ~0.2s, not ~0.6s)
    assert 0.2 <= elapsed < 0.4  # Allow some buffer for test environment variations


def test_thread_safe_dict_basic_operations() -> None:
    """Test basic operations of ThreadSafeDict"""
    d = ThreadSafeDict[str, int]()

    # Test setting and getting
    d["a"] = 1
    assert d["a"] == 1

    # Test get with default
    assert d.get("a", None) == 1
    assert d.get("b", 2) == 2

    # Test deletion
    del d["a"]
    assert "a" not in d

    # Test length
    d["x"] = 10
    d["y"] = 20
    assert len(d) == 2

    # Test iteration
    keys = sorted(d.keys())
    assert keys == ["x", "y"]

    # Test items and values
    assert dict(d.items()) == {"x": 10, "y": 20}
    assert sorted(d.values()) == [10, 20]


def test_thread_safe_dict_concurrent_access() -> None:
    """Test ThreadSafeDict with concurrent access from multiple threads"""
    d = ThreadSafeDict[str, int]()
    num_threads = 10
    iterations = 1000

    def increment_values() -> None:
        for i in range(iterations):
            key = str(i % 5)  # Use 5 different keys
            # Get current value or 0 if not exists, increment, then store
            d.atomic_get_set(key, lambda x: x + 1, 0)

    # Create and start threads
    threads = []
    for _ in range(num_threads):
        t = threading.Thread(target=increment_values)
        threads.append(t)
        t.start()

    # Wait for all threads to complete
    for t in threads:
        t.join()

    # Verify results
    # Each key should have been incremented (num_threads * iterations) / 5 times
    expected_value = (num_threads * iterations) // 5
    for i in range(5):
        assert d[str(i)] == expected_value


def test_thread_safe_dict_bulk_operations() -> None:
    """Test bulk operations of ThreadSafeDict"""
    d = ThreadSafeDict[str, int]()

    # Test update with dict
    d.update({"a": 1, "b": 2})
    assert dict(d.items()) == {"a": 1, "b": 2}

    # Test update with kwargs
    d.update(c=3, d=4)
    assert dict(d.items()) == {"a": 1, "b": 2, "c": 3, "d": 4}

    # Test clear
    d.clear()
    assert len(d) == 0


def test_thread_safe_dict_concurrent_bulk_operations() -> None:
    """Test ThreadSafeDict with concurrent bulk operations"""
    d = ThreadSafeDict[str, int]()
    num_threads = 5

    def bulk_update(start: int) -> None:
        # Each thread updates with its own range of numbers
        updates = {str(i): i for i in range(start, start + 20)}
        d.update(updates)
        time.sleep(0.01)  # Add some delay to increase chance of thread overlap

    # Run updates concurrently
    with ThreadPoolExecutor(max_workers=num_threads) as executor:
        futures = [executor.submit(bulk_update, i * 20) for i in range(num_threads)]
        for future in futures:
            future.result()

    # Verify results
    assert len(d) == num_threads * 20
    # Verify all numbers from 0 to (num_threads * 20) are present
    for i in range(num_threads * 20):
        assert d[str(i)] == i


def test_thread_safe_dict_atomic_operations() -> None:
    """Test atomic operations with ThreadSafeDict's lock"""
    d = ThreadSafeDict[str, list[int]]()
    d["numbers"] = []

    def append_numbers(start: int) -> None:
        numbers = d["numbers"]
        with d.lock:
            for i in range(start, start + 5):
                numbers.append(i)
                time.sleep(0.001)  # Add delay to increase chance of thread overlap
        d["numbers"] = numbers

    # Run concurrent append operations
    threads = []
    for i in range(4):  # 4 threads, each adding 5 numbers
        t = threading.Thread(target=append_numbers, args=(i * 5,))
        threads.append(t)
        t.start()

    for t in threads:
        t.join()

    # Verify results
    numbers = d["numbers"]
    assert len(numbers) == 20  # 4 threads * 5 numbers each
    assert sorted(numbers) == list(range(20))  # All numbers 0-19 should be present


def test_parallel_yield_basic() -> None:
    """Test that parallel_yield correctly yields values from multiple generators."""

    def make_gen(values: list[int], delay: float) -> Generator[int, None, None]:
        for v in values:
            time.sleep(delay)
            yield v

    # Create generators with different delays
    gen1 = make_gen([1, 4, 7], 0.1)  # Slower generator
    gen2 = make_gen([2, 5, 8], 0.05)  # Faster generator
    gen3 = make_gen([3, 6, 9], 0.15)  # Slowest generator

    # Collect results with timestamps
    results: list[tuple[float, int]] = []
    start_time = time.time()

    for value in parallel_yield([gen1, gen2, gen3]):
        results.append((time.time() - start_time, value))

    # Verify all values were yielded
    assert sorted(v for _, v in results) == list(range(1, 10))

    # Verify that faster generators yielded earlier
    # Group results by generator (values 1,4,7 are gen1, 2,5,8 are gen2, 3,6,9 are gen3)
    gen1_times = [t for t, v in results if v in (1, 4, 7)]
    gen2_times = [t for t, v in results if v in (2, 5, 8)]
    gen3_times = [t for t, v in results if v in (3, 6, 9)]

    # Average times for each generator
    avg_gen1 = sum(gen1_times) / len(gen1_times)
    avg_gen2 = sum(gen2_times) / len(gen2_times)
    avg_gen3 = sum(gen3_times) / len(gen3_times)

    # Verify gen2 (fastest) has lowest average time
    assert avg_gen2 < avg_gen1
    assert avg_gen2 < avg_gen3


def test_parallel_yield_empty_generators() -> None:
    """Test parallel_yield with empty generators."""

    def empty_gen() -> Iterator[int]:
        if False:
            yield 0  # Makes this a generator function

    gens = [empty_gen() for _ in range(3)]
    results = list(parallel_yield(gens))
    assert len(results) == 0


def test_parallel_yield_different_lengths() -> None:
    """Test parallel_yield with generators of different lengths."""

    def make_gen(count: int) -> Iterator[int]:
        for i in range(count):
            yield i
            time.sleep(0.01)  # Small delay to ensure concurrent execution

    gens = [
        make_gen(1),  # Yields: [0]
        make_gen(3),  # Yields: [0, 1, 2]
        make_gen(2),  # Yields: [0, 1]
    ]

    results = list(parallel_yield(gens))
    assert len(results) == 6  # Total number of items from all generators
    assert sorted(results) == [0, 0, 0, 1, 1, 2]


def test_parallel_yield_exception_handling() -> None:
    """Test parallel_yield handles exceptions in generators properly."""

    def failing_gen() -> Iterator[int]:
        yield 1
        raise ValueError("Generator failure")

    def normal_gen() -> Iterator[int]:
        yield 2
        yield 3

    gens = [failing_gen(), normal_gen()]

    with pytest.raises(ValueError, match="Generator failure"):
        list(parallel_yield(gens))


def test_parallel_yield_non_blocking() -> None:
    """Test parallel_yield with non-blocking generators (simple ranges)."""

    def range_gen(start: int, end: int) -> Iterator[int]:
        for i in range(start, end):
            yield i

    # Create three overlapping ranges
    gens = [range_gen(0, 100), range_gen(100, 200), range_gen(200, 300)]

    results = list(parallel_yield(gens))

    # Verify no values are missing
    assert len(results) == 300  # Should have all values from 0 to 299
    assert sorted(results) == list(range(300))
