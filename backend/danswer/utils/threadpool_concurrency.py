import uuid
from collections.abc import Callable
from concurrent.futures import as_completed
from concurrent.futures import ThreadPoolExecutor
from typing import Any
from typing import Generic
from typing import TypeVar

from danswer.utils.logger import setup_logger

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
        future_to_index = {
            executor.submit(func, *args): i
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
    results = {}

    with ThreadPoolExecutor(max_workers=len(function_calls)) as executor:
        future_to_id = {
            executor.submit(func_call.execute): func_call.result_id
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
