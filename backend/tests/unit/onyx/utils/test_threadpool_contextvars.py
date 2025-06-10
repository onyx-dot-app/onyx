import contextvars
import time

from onyx.utils.threadpool_concurrency import FunctionCall
from onyx.utils.threadpool_concurrency import run_functions_in_parallel
from onyx.utils.threadpool_concurrency import run_functions_tuples_in_parallel
from onyx.utils.threadpool_concurrency import run_in_background
from onyx.utils.threadpool_concurrency import run_with_timeout
from onyx.utils.threadpool_concurrency import wait_on_background

# Create a test contextvar
test_var = contextvars.ContextVar("test_var", default="default")


def get_contextvar_value() -> str:
    """Helper function that runs in a thread and returns the contextvar value"""
    # Add a small sleep to ensure we're actually running in a different thread
    time.sleep(0.1)
    return test_var.get()


def test_run_with_timeout_preserves_contextvar() -> None:
    """Test that run_with_timeout preserves contextvar values"""
    # Set a value in the main thread
    test_var.set("test_value")

    # Run function with timeout and verify the value is preserved
    result = run_with_timeout(1.0, get_contextvar_value)
    assert result == "test_value"


def test_run_functions_in_parallel_preserves_contextvar() -> None:
    """Test that run_functions_in_parallel preserves contextvar values"""
    # Set a value in the main thread
    test_var.set("parallel_test")

    # Create multiple function calls
    function_calls = [
        FunctionCall(get_contextvar_value),
        FunctionCall(get_contextvar_value),
    ]

    # Run in parallel and verify all results have the correct value
    results = run_functions_in_parallel(function_calls)

    for result_id, value in results.items():
        assert value == "parallel_test"


def test_run_functions_tuples_preserves_contextvar() -> None:
    """Test that run_functions_tuples_in_parallel preserves contextvar values"""
    # Set a value in the main thread
    test_var.set("tuple_test")

    # Create list of function tuples
    functions_with_args = [
        (get_contextvar_value, ()),
        (get_contextvar_value, ()),
    ]

    # Run in parallel and verify all results have the correct value
    results = run_functions_tuples_in_parallel(functions_with_args)

    for result in results:
        assert result == "tuple_test"


def test_nested_contextvar_modifications() -> None:
    """Test that modifications to contextvars in threads don't affect other threads"""

    def modify_and_return_contextvar(new_value: str) -> tuple[str, str]:
        """Helper that modifies the contextvar and returns both values"""
        original = test_var.get()
        test_var.set(new_value)
        time.sleep(0.1)  # Ensure threads overlap
        return original, test_var.get()

    # Set initial value
    test_var.set("initial")

    # Run multiple functions that modify the contextvar
    functions_with_args = [
        (modify_and_return_contextvar, ("thread1",)),
        (modify_and_return_contextvar, ("thread2",)),
    ]

    results = run_functions_tuples_in_parallel(functions_with_args)

    # Verify each thread saw the initial value and its own modification
    for original, modified in results:
        assert original == "initial"  # Each thread should see the initial value
        assert modified in [
            "thread1",
            "thread2",
        ]  # Each thread should see its own modification

    # Verify the main thread's value wasn't affected
    assert test_var.get() == "initial"


def test_contextvar_isolation_between_runs() -> None:
    """Test that contextvar changes don't leak between separate parallel runs"""

    def set_and_return_contextvar(value: str) -> str:
        test_var.set(value)
        return test_var.get()

    # First run
    test_var.set("first_run")
    first_results = run_functions_tuples_in_parallel(
        [
            (set_and_return_contextvar, ("thread1",)),
            (set_and_return_contextvar, ("thread2",)),
        ]
    )

    # Verify first run results
    assert all(result in ["thread1", "thread2"] for result in first_results)

    # Second run should still see the main thread's value
    assert test_var.get() == "first_run"

    # Second run with different value
    test_var.set("second_run")
    second_results = run_functions_tuples_in_parallel(
        [
            (set_and_return_contextvar, ("thread3",)),
            (set_and_return_contextvar, ("thread4",)),
        ]
    )

    # Verify second run results
    assert all(result in ["thread3", "thread4"] for result in second_results)


def test_run_in_background_preserves_contextvar() -> None:
    """Test that run_in_background preserves contextvar values and modifications are isolated"""

    def modify_and_sleep() -> tuple[str, str]:
        """Modifies contextvar, sleeps, and returns original, modified, and final values"""
        original = test_var.get()
        test_var.set("modified_in_background")
        time.sleep(0.1)  # Ensure we can check main thread during execution
        final = test_var.get()
        return original, final

    # Set initial value in main thread
    token = test_var.set("initial_value")
    try:
        # Start background task
        task = run_in_background(modify_and_sleep)

        # Verify main thread value remains unchanged while task runs
        assert test_var.get() == "initial_value"

        # Get results from background thread
        original, modified = wait_on_background(task)

        # Verify the background thread:
        # 1. Saw the initial value
        assert original == "initial_value"
        # 2. Successfully modified its own copy
        assert modified == "modified_in_background"

        # Verify main thread value is still unchanged after task completion
        assert test_var.get() == "initial_value"
    finally:
        # Clean up
        test_var.reset(token)
