import multiprocessing
from collections.abc import Callable
from typing import Any
from typing import TypeVar

T = TypeVar("T")


def run_with_timeout(task: Callable[..., T], timeout: int, kwargs: dict[str, Any]) -> T:
    # Use multiprocessing to prevent a thread from blocking the main thread
    with multiprocessing.Pool(processes=1) as pool:
        async_result = pool.apply_async(task, kwds=kwargs)
        try:
            # Wait at most timeout seconds for the function to complete
            result = async_result.get(timeout=timeout)
            return result
        except multiprocessing.TimeoutError:
            raise TimeoutError(f"Function timed out after {timeout} seconds")
