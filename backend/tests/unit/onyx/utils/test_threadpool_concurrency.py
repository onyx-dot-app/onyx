import contextvars
import time

import pytest

from onyx.utils.threadpool_concurrency import run_in_background
from onyx.utils.threadpool_concurrency import run_with_timeout
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
    assert elapsed >= 0.1  # Verify we actually waited for the sleep


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
