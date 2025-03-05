import contextvars
import threading
import uuid
from collections.abc import Callable
from concurrent.futures import as_completed
from concurrent.futures import ThreadPoolExecutor
from typing import Any
from typing import Generic
from typing import TypeVar

from onyx.utils.logger import setup_logger

logger = setup_logger()

R = TypeVar("R")


def run_functions_tuples_in_parallel(
    functions_with_args: list[tuple[Callable, tuple]],
    allow_failures: bool = False,
    max_workers: int | None = None,
) -> list[Any]:
    """
    Executes multiple functions in parallel and returns a list of the results for each function.

    Args:
        functions_with_args: List of tuples each containing the function callable and a tuple of arguments.
        allow_failures: if set to True, then the function result will just be None
        max_workers: Max number of worker threads

    Returns:
        dict: A dictionary mapping function names to their results or error messages.
    """
    workers = (
        min(max_workers, len(functions_with_args))
        if max_workers is not None
        else len(functions_with_args)
    )

    if workers <= 0:
        return []

    results = []
    with ThreadPoolExecutor(max_workers=workers) as executor:
        # The primary reason for propagating contextvars is to allow acquiring a db session
        # that respects tenant id. Context.run is expected to be low-overhead, but if we later
        # find that it is increasing latency we can make using it optional.
        future_to_index = {
            executor.submit(contextvars.copy_context().run, func, *args): i
            for i, (func, args) in enumerate(functions_with_args)
        }

        for future in as_completed(future_to_index):
            index = future_to_index[future]
            try:
                results.append((index, future.result()))
            except Exception as e:
                logger.exception(f"Function at index {index} failed due to {e}")
                results.append((index, None))

                if not allow_failures:
                    raise

    results.sort(key=lambda x: x[0])
    return [result for index, result in results]


class FunctionCall(Generic[R]):
    """
    Container for run_functions_in_parallel, fetch the results from the output of
    run_functions_in_parallel via the FunctionCall.result_id.
    """

    def __init__(
        self, func: Callable[..., R], args: tuple = (), kwargs: dict | None = None
    ):
        self.func = func
        self.args = args
        self.kwargs = kwargs if kwargs is not None else {}
        self.result_id = str(uuid.uuid4())

    def execute(self) -> R:
        return self.func(*self.args, **self.kwargs)


def run_functions_in_parallel(
    function_calls: list[FunctionCall],
    allow_failures: bool = False,
) -> dict[str, Any]:
    """
    Executes a list of FunctionCalls in parallel and stores the results in a dictionary where the keys
    are the result_id of the FunctionCall and the values are the results of the call.
    """
    results: dict[str, Any] = {}

    if len(function_calls) == 0:
        return results

    with ThreadPoolExecutor(max_workers=len(function_calls)) as executor:
        future_to_id = {
            executor.submit(
                contextvars.copy_context().run, func_call.execute
            ): func_call.result_id
            for func_call in function_calls
        }

        for future in as_completed(future_to_id):
            result_id = future_to_id[future]
            try:
                results[result_id] = future.result()
            except Exception as e:
                logger.exception(f"Function with ID {result_id} failed due to {e}")
                results[result_id] = None

                if not allow_failures:
                    raise

    return results


class TimeoutThread(threading.Thread, Generic[R]):
    def __init__(
        self, timeout: float, func: Callable[..., R], *args: Any, **kwargs: Any
    ):
        super().__init__()
        self.timeout = timeout
        self.func = func
        self.args = args
        self.kwargs = kwargs
        self.exception: Exception | None = None

    def run(self) -> None:
        try:
            self.result = self.func(*self.args, **self.kwargs)
        except Exception as e:
            self.exception = e

    def end(self) -> None:
        raise TimeoutError(
            f"Function {self.func.__name__} timed out after {self.timeout} seconds"
        )


def run_with_timeout(
    timeout: float, func: Callable[..., R], *args: Any, **kwargs: Any
) -> R:
    """
    Executes a function with a timeout. If the function doesn't complete within the specified
    timeout, raises TimeoutError.
    """
    context = contextvars.copy_context()
    task = TimeoutThread(timeout, context.run, func, *args, **kwargs)
    task.start()
    task.join(timeout)

    if task.exception is not None:
        raise task.exception
    if task.is_alive():
        task.end()

    return task.result


# NOTE: this function should really only be used when run_functions_tuples_in_parallel is
# difficult to use. It's up to the programmer to call wait_on_background on the thread after
# the code you want to run in parallel is finished. As with all python thread parallelism,
# this is only useful for I/O bound tasks.
def run_in_background(
    func: Callable[..., R], *args: Any, **kwargs: Any
) -> TimeoutThread[R]:
    """
    Runs a function in a background thread. Returns a TimeoutThread object that can be used
    to wait for the function to finish with wait_on_background.
    """
    context = contextvars.copy_context()
    # Timeout not used in the non-blocking case
    task = TimeoutThread(-1, context.run, func, *args, **kwargs)
    task.start()
    return task


def wait_on_background(task: TimeoutThread[R]) -> R:
    """
    Used in conjunction with run_in_background. blocks until the task is finished,
    then returns the result of the task.
    """
    task.join()

    if task.exception is not None:
        raise task.exception

    return task.result
