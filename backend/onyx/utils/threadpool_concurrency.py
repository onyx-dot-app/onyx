import asyncio
import collections.abc
import concurrent
import contextvars
import copy
import threading
import uuid
from collections.abc import Awaitable
from collections.abc import Callable
from collections.abc import Iterator
from collections.abc import MutableMapping
from collections.abc import Sequence
from concurrent.futures import as_completed
from concurrent.futures import FIRST_COMPLETED
from concurrent.futures import Future
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import wait
from typing import Any
from typing import cast
from typing import Generic
from typing import overload
from typing import Protocol
from typing import TypeVar

from pydantic import GetCoreSchemaHandler
from pydantic.types import T
from pydantic_core import core_schema

from onyx.utils.logger import setup_logger

logger = setup_logger()

R = TypeVar("R")
KT = TypeVar("KT")  # Key type
VT = TypeVar("VT")  # Value type
_T = TypeVar("_T")  # Default type


class ThreadSafeDict(MutableMapping[KT, VT]):
    """
    A thread-safe dictionary implementation that uses a lock to ensure thread safety.
    Implements the MutableMapping interface to provide a complete dictionary-like interface.

    Example usage:
        # Create a thread-safe dictionary
        safe_dict: ThreadSafeDict[str, int] = ThreadSafeDict()

        # Basic operations (atomic)
        safe_dict["key"] = 1
        value = safe_dict["key"]
        del safe_dict["key"]

        # Bulk operations (atomic)
        safe_dict.update({"key1": 1, "key2": 2})
    """

    def __init__(self, input_dict: dict[KT, VT] | None = None) -> None:
        self._dict: dict[KT, VT] = input_dict or {}
        self.lock = threading.Lock()

    def __getitem__(self, key: KT) -> VT:
        with self.lock:
            return self._dict[key]

    def __setitem__(self, key: KT, value: VT) -> None:
        with self.lock:
            self._dict[key] = value

    def __delitem__(self, key: KT) -> None:
        with self.lock:
            del self._dict[key]

    def __iter__(self) -> Iterator[KT]:
        # Return a snapshot of keys to avoid potential modification during iteration
        with self.lock:
            return iter(list(self._dict.keys()))

    def __len__(self) -> int:
        with self.lock:
            return len(self._dict)

    @classmethod
    def __get_pydantic_core_schema__(
        cls, source_type: Any, handler: GetCoreSchemaHandler
    ) -> core_schema.CoreSchema:
        return core_schema.no_info_after_validator_function(
            cls.validate, handler(dict[KT, VT])
        )

    @classmethod
    def validate(cls, v: Any) -> "ThreadSafeDict[KT, VT]":
        if isinstance(v, dict):
            return ThreadSafeDict(v)
        return v

    def __deepcopy__(self, memo: Any) -> "ThreadSafeDict[KT, VT]":
        return ThreadSafeDict(copy.deepcopy(self._dict))

    def clear(self) -> None:
        """Remove all items from the dictionary atomically."""
        with self.lock:
            self._dict.clear()

    def copy(self) -> dict[KT, VT]:
        """Return a shallow copy of the dictionary atomically."""
        with self.lock:
            return self._dict.copy()

    @overload
    def get(self, key: KT) -> VT | None: ...

    @overload
    def get(self, key: KT, default: VT | _T) -> VT | _T: ...

    def get(self, key: KT, default: Any = None) -> Any:
        """Get a value with a default, atomically."""
        with self.lock:
            return self._dict.get(key, default)

    def pop(self, key: KT, default: Any = None) -> Any:
        """Remove and return a value with optional default, atomically."""
        with self.lock:
            if default is None:
                return self._dict.pop(key)
            return self._dict.pop(key, default)

    def setdefault(self, key: KT, default: VT) -> VT:
        """Set a default value if key is missing, atomically."""
        with self.lock:
            return self._dict.setdefault(key, default)

    def update(self, *args: Any, **kwargs: VT) -> None:
        """Update the dictionary atomically from another mapping or from kwargs."""
        with self.lock:
            self._dict.update(*args, **kwargs)

    def items(self) -> collections.abc.ItemsView[KT, VT]:
        """Return a view of (key, value) pairs atomically."""
        with self.lock:
            return collections.abc.ItemsView(self)

    def keys(self) -> collections.abc.KeysView[KT]:
        """Return a view of keys atomically."""
        with self.lock:
            return collections.abc.KeysView(self)

    def values(self) -> collections.abc.ValuesView[VT]:
        """Return a view of values atomically."""
        with self.lock:
            return collections.abc.ValuesView(self)

    @overload
    def atomic_get_set(
        self, key: KT, value_callback: Callable[[VT], VT], default: VT
    ) -> tuple[VT, VT]: ...

    @overload
    def atomic_get_set(
        self, key: KT, value_callback: Callable[[VT | _T], VT], default: VT | _T
    ) -> tuple[VT | _T, VT]: ...

    def atomic_get_set(
        self, key: KT, value_callback: Callable[[Any], VT], default: Any = None
    ) -> tuple[Any, VT]:
        """Replace a value from the dict with a function applied to the previous value, atomically.

        Returns:
            A tuple of the previous value and the new value.
        """
        with self.lock:
            val = self._dict.get(key, default)
            new_val = value_callback(val)
            self._dict[key] = new_val
            return val, new_val


class CallableProtocol(Protocol):
    def __call__(self, *args: Any, **kwargs: Any) -> Any: ...


def run_functions_tuples_in_parallel(
    functions_with_args: Sequence[tuple[CallableProtocol, tuple[Any, ...]]],
    allow_failures: bool = False,
    max_workers: int | None = None,
) -> list[Any]:
    """
    Executes multiple functions in parallel and returns a list of the results for each function.
    This function preserves contextvars across threads, which is important for maintaining
    context like tenant IDs in database sessions.

    Args:
        functions_with_args: List of tuples each containing the function callable and a tuple of arguments.
        allow_failures: if set to True, then the function result will just be None
        max_workers: Max number of worker threads

    Returns:
        list: A list of results from each function, in the same order as the input functions.
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
                results.append((index, None))  # type: ignore

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


def run_async_sync_no_cancel(coro: Awaitable[T]) -> T:
    """
    async-to-sync converter. Basically just executes asyncio.run in a separate thread.
    Which is probably somehow inefficient or not ideal but fine for now.
    """
    context = contextvars.copy_context()
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
        future: concurrent.futures.Future[T] = executor.submit(
            context.run, asyncio.run, coro  # type: ignore[arg-type]
        )
        return future.result()


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

    return task.result  # type: ignore


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
    task = TimeoutThread(-1, context.run, func, *args, **kwargs)  # type: ignore
    task.start()
    return cast(TimeoutThread[R], task)


def wait_on_background(task: TimeoutThread[R]) -> R:
    """
    Used in conjunction with run_in_background. blocks until the task is finished,
    then returns the result of the task.
    """
    task.join()

    if task.exception is not None:
        raise task.exception

    return task.result


def _next_or_none(ind: int, gen: Iterator[R]) -> tuple[int, R | None]:
    return ind, next(gen, None)


def parallel_yield(gens: list[Iterator[R]], max_workers: int = 10) -> Iterator[R]:
    """
    Runs the list of generators with thread-level parallelism, yielding
    results as available. The asynchronous nature of this yielding means
    that stopping the returned iterator early DOES NOT GUARANTEE THAT NO
    FURTHER ITEMS WERE PRODUCED by the input gens. Only use this function
    if you are consuming all elements from the generators OR it is acceptable
    for some extra generator code to run and not have the result(s) yielded.
    """
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_to_index: dict[Future[tuple[int, R | None]], int] = {
            executor.submit(_next_or_none, ind, gen): ind
            for ind, gen in enumerate(gens)
        }

        next_ind = len(gens)
        while future_to_index:
            done, _ = wait(future_to_index, return_when=FIRST_COMPLETED)
            for future in done:
                ind, result = future.result()
                if result is not None:
                    yield result
                    future_to_index[executor.submit(_next_or_none, ind, gens[ind])] = (
                        next_ind
                    )
                    next_ind += 1
                del future_to_index[future]


def parallel_yield_from_funcs(
    funcs: list[Callable[..., R]],
    max_workers: int = 10,
) -> Iterator[R]:
    """
    Runs the list of functions with thread-level parallelism, yielding
    results as available. The asynchronous nature of this yielding means
    that stopping the returned iterator early DOES NOT GUARANTEE THAT NO
    FURTHER ITEMS WERE PRODUCED by the input funcs. Only use this function
    if you are consuming all elements from the functions OR it is acceptable
    for some extra function code to run and not have the result(s) yielded.
    """

    def func_wrapper(func: Callable[[], R]) -> Iterator[R]:
        yield func()

    yield from parallel_yield(
        [func_wrapper(func) for func in funcs], max_workers=max_workers
    )
