import time

import pytest

from onyx.utils.threadpool_concurrency import run_with_timeout


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
