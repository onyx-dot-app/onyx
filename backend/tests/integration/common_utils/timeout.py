# import multiprocessing
# from collections.abc import Callable
# from typing import Any
# from typing import TypeVar

# T = TypeVar("T")


# def run_with_timeout_multiproc(
#     task: Callable[..., T], timeout: int, kwargs: dict[str, Any]
# ) -> T:
#     # Use multiprocessing to prevent a thread from blocking the main thread
#     with multiprocessing.Pool(processes=1) as pool:
#         async_result = pool.apply_async(task, kwds=kwargs)
#         try:
#             # Wait at most timeout seconds for the function to complete
#             result = async_result.get(timeout=timeout)
#             return result
#         except multiprocessing.TimeoutError:
#             raise TimeoutError(f"Function timed out after {timeout} seconds")


import multiprocessing
import traceback
from collections.abc import Callable
from multiprocessing import Queue
from typing import Any
from typing import TypeVar

T = TypeVar("T")


def _multiproc_wrapper(
    task: Callable[..., T], kwargs: dict[str, Any], q: Queue
) -> None:
    try:
        result = task(**kwargs)
        q.put(("success", result))
    except Exception:
        q.put(("error", traceback.format_exc()))


def run_with_timeout_multiproc(
    task: Callable[..., T], timeout: int, kwargs: dict[str, Any]
) -> T:
    ctx = multiprocessing.get_context("spawn")
    q: Queue = ctx.Queue()
    p = ctx.Process(
        target=_multiproc_wrapper,
        args=(
            task,
            kwargs,
            q,
        ),
    )
    p.start()
    p.join(timeout)

    if p.is_alive():
        p.terminate()
        raise TimeoutError(f"{task.__name__} timed out after {timeout} seconds")

    if not q.empty():
        status, result = q.get()
        if status == "success":
            return result
        else:
            raise RuntimeError(f"{task.__name__} failed:\n{result}")
    else:
        raise RuntimeError(f"{task.__name__} returned no result")
