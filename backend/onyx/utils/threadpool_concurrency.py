import asyncio
import collections.abc
import concurrent.futures
import contextvars
import copy
import threading
import time
import uuid
from collections import deque
from collections.abc import Callable, Coroutine, Iterator, MutableMapping, Sequence
from concurrent.futures import (
    FIRST_COMPLETED,
    Future,
    ThreadPoolExecutor,
    as_completed,
    wait,
)
from typing import Any, Generic, Protocol, TypeVar, cast, overload

from pydantic import GetCoreSchemaHandler
from pydantic.types import T
from pydantic_core import core_schema

from onyx.utils.logger import setup_logger

logger = setup_logger()

R = TypeVar("R")
KT = TypeVar("KT")  # Key type
VT = TypeVar("VT")  # Value type
_T = TypeVar("_T")  # Default type
_MISSING: object = object()


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

    def get(self, key: KT, default: Any = None) -> Any:  # ty: ignore[invalid-method-override]
        """Get a value with a default, atomically."""
        with self.lock:
            return self._dict.get(key, default)

    def pop(self, key: KT, default: Any = _MISSING) -> Any:
        """Remove and return a value with optional default, atomically."""
        with self.lock:
            if default is _MISSING:
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


ST = TypeVar("ST")  # Set element type


class ThreadSafeSet(Generic[ST]):
    """
    A thread-safe set implementation that uses a lock to ensure thread safety.

    Example usage:
        # Create a thread-safe set
        safe_set: ThreadSafeSet[str] = ThreadSafeSet()

        # Basic operations (atomic)
        safe_set.add("item")
        if "item" in safe_set:
            ...
        safe_set.discard("item")

        # Bulk operations (atomic)
        safe_set.update({"item1", "item2"})

        # Atomic check-and-add (returns True if item was already present)
        was_present = safe_set.check_and_add("item")
    """

    def __init__(self, input_set: set[ST] | None = None) -> None:
        self._set: set[ST] = input_set.copy() if input_set else set()
        self.lock = threading.Lock()

    def __contains__(self, item: ST) -> bool:
        with self.lock:
            return item in self._set

    def __len__(self) -> int:
        with self.lock:
            return len(self._set)

    def __iter__(self) -> Iterator[ST]:
        # Return a snapshot to avoid modification during iteration
        with self.lock:
            return iter(list(self._set))

    @classmethod
    def __get_pydantic_core_schema__(
        cls, source_type: Any, handler: GetCoreSchemaHandler
    ) -> core_schema.CoreSchema:
        return core_schema.no_info_after_validator_function(
            cls.validate, handler(set[ST])
        )

    @classmethod
    def validate(cls, v: Any) -> "ThreadSafeSet[ST]":
        if isinstance(v, set):
            return ThreadSafeSet(v)
        return v

    def __deepcopy__(self, memo: Any) -> "ThreadSafeSet[ST]":
        with self.lock:
            return ThreadSafeSet(copy.deepcopy(self._set))

    def add(self, item: ST) -> None:
        """Add an item to the set atomically."""
        with self.lock:
            self._set.add(item)

    def discard(self, item: ST) -> None:
        """Remove an item if present, atomically."""
        with self.lock:
            self._set.discard(item)

    def remove(self, item: ST) -> None:
        """Remove an item, raise KeyError if not present, atomically."""
        with self.lock:
            self._set.remove(item)

    def clear(self) -> None:
        """Remove all items from the set atomically."""
        with self.lock:
            self._set.clear()

    def copy(self) -> set[ST]:
        """Return a shallow copy of the set atomically."""
        with self.lock:
            return self._set.copy()

    def update(self, *others: set[ST]) -> None:
        """Update the set with items from other sets atomically."""
        with self.lock:
            for other in others:
                self._set.update(other)

    def check_and_add(self, item: ST) -> bool:
        """
        Atomically check if item exists and add it if not.
        Returns True if the item was already present, False if it was added.
        This prevents race conditions in check-then-add patterns.
        """
        with self.lock:
            if item in self._set:
                return True
            self._set.add(item)
            return False


class CallableProtocol(Protocol):
    def __call__(self, *args: Any, **kwargs: Any) -> Any: ...


def run_functions_tuples_in_parallel(
    functions_with_args: Sequence[tuple[CallableProtocol, tuple[Any, ...]]],
    allow_failures: bool = False,
    max_workers: int | None = None,
    timeout: float | None = None,
    timeout_callback: (
        Callable[[int, CallableProtocol, tuple[Any, ...]], Any] | None
    ) = None,
) -> list[Any]:
    """
    Executes multiple functions in parallel and returns a list of the results for each function.
    This function preserves contextvars across threads, which is important for maintaining
    context like tenant IDs in database sessions.

    Args:
        functions_with_args: List of tuples each containing the function callable and a tuple of arguments.
        allow_failures: if set to True, then the function result will just be None
        max_workers: Max number of worker threads
        timeout: Optional wall-clock timeout in seconds. If any function hasn't completed
            within this time, it will be considered timed out. When timeout is set, threads
            that exceed the timeout will continue running in the background but their results
            will not be awaited. IMPORTANT: because the thread continues to run in the background,
            it can continue to consume resources and updated shared state objects even though the caller
            has moved on.
        timeout_callback: Optional callback for handling timeouts. Called with (index, func, args)
            for each timed-out function. If provided, its return value is used as the result.
            If not provided and allow_failures is False, TimeoutError is raised.
            If not provided and allow_failures is True, None is returned for timed-out functions.

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

    results: list[tuple[int, Any]] = []
    executor = ThreadPoolExecutor(max_workers=workers)

    try:
        # The primary reason for propagating contextvars is to allow acquiring a db session
        # that respects tenant id. Context.run is expected to be low-overhead, but if we later
        # find that it is increasing latency we can make using it optional.
        future_to_index = {
            executor.submit(contextvars.copy_context().run, func, *args): i
            for i, (func, args) in enumerate(functions_with_args)
        }

        if timeout is not None:
            # Wait for completion or timeout
            done, not_done = wait(future_to_index.keys(), timeout=timeout)

            # Process completed futures
            for future in done:
                index = future_to_index[future]
                try:
                    results.append((index, future.result()))
                except Exception as e:
                    logger.exception("Function at index %s failed due to %s", index, e)
                    results.append((index, None))
                    if not allow_failures:
                        raise

            # Process timed-out futures
            for future in not_done:
                index = future_to_index[future]
                func, args = functions_with_args[index]
                logger.warning(
                    "Function at index %s timed out after %s seconds", index, timeout
                )

                if timeout_callback:
                    timeout_result = timeout_callback(index, func, args)
                    results.append((index, timeout_result))
                else:
                    results.append((index, None))
                    if not allow_failures:
                        raise TimeoutError(
                            f"Function at index {index} timed out after {timeout} seconds"
                        )

                # Attempt to cancel (only effective if not yet started)
                future.cancel()
        else:
            for future in as_completed(future_to_index):
                index = future_to_index[future]
                try:
                    results.append((index, future.result()))
                except Exception as e:
                    logger.exception("Function at index %s failed due to %s", index, e)
                    results.append((index, None))

                    if not allow_failures:
                        raise
    finally:
        # When timeout is used, don't wait for timed-out threads to complete
        # (they will continue running in the background)
        # When no timeout, wait for all threads to complete (original behavior)
        executor.shutdown(wait=(timeout is None))

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
                logger.exception("Function with ID %s failed due to %s", result_id, e)
                results[result_id] = None

                if not allow_failures:
                    raise

    return results


def run_async_sync_no_cancel(coro: Coroutine[Any, Any, T]) -> T:
    """
    async-to-sync converter. Basically just executes asyncio.run in a separate thread.
    Which is probably somehow inefficient or not ideal but fine for now.
    """
    context = contextvars.copy_context()

    def _run() -> T:
        return cast(T, context.run(asyncio.run, coro))

    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(_run)
        return future.result()


def start_thread_with_context(
    target: Callable[..., Any],
    *,
    name: str | None = None,
    daemon: bool = False,
    args: tuple[Any, ...] = (),
    kwargs: dict[str, Any] | None = None,
    context: contextvars.Context | None = None,
) -> threading.Thread:
    """Start a thread with an explicit context or a copy of the caller's context.

    Preserve tenant ID, request ID, and trace context across threads.
    """
    ctx: contextvars.Context = (
        context if context is not None else contextvars.copy_context()
    )
    thread = threading.Thread(
        target=lambda: ctx.run(target, *args, **(kwargs or {})),
        name=name,
        daemon=daemon,
    )
    thread.start()
    return thread


def start_thread_future[T](operation: Callable[[], T], *, name: str) -> Future[T]:
    """Start independent work with the caller's context and an observable result."""
    result: Future[T] = Future()
    result.set_running_or_notify_cancel()

    def run() -> None:
        try:
            value: T = operation()
        except BaseException as error:
            result.set_exception(error)
        else:
            result.set_result(value)

    start_thread_with_context(run, name=name, daemon=True)
    return result


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
            f"Function {self.func.__name__} timed out after {self.timeout} seconds"  # ty: ignore[unresolved-attribute]
        )


def run_with_timeout(
    timeout: float, func: Callable[..., R], *args: Any, **kwargs: Any
) -> R:
    """
    Executes a function with a timeout. If the function doesn't complete within
    the specified timeout, raises TimeoutError.
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
        future_to_index: dict[Future[tuple[int, R | None]], int] = (  # ty: ignore[invalid-assignment]
            {
                # The caller's context rides along, as in the rest of this
                # module: the tenant id and the log prefix live in contextvars.
                executor.submit(
                    contextvars.copy_context().run, _next_or_none, ind, gen
                ): ind
                for ind, gen in enumerate(gens)
            }
        )

        next_ind = len(gens)
        while future_to_index:
            done, _ = wait(future_to_index, return_when=FIRST_COMPLETED)
            for future in done:
                ind, result = future.result()
                if result is not None:
                    yield result
                    future_to_index[
                        executor.submit(
                            contextvars.copy_context().run,
                            _next_or_none,
                            ind,
                            gens[ind],
                        )
                    ] = next_ind  # ty: ignore[invalid-assignment]
                    next_ind += 1
                del future_to_index[future]


def drain(
    items: Sequence[_T], listing: Callable[[_T], Iterator[R]], workers: int
) -> Iterator[R]:
    """Every item listed, ``workers`` at a time, each worker taking the next
    item off a shared queue so a slow item holds back only its own worker."""
    if workers <= 1 or len(items) <= 1:
        for item in items:
            yield from listing(item)
        return
    queue: deque[_T] = deque(items)

    def worker() -> Iterator[R]:
        while True:
            try:
                item = queue.popleft()
            except IndexError:
                return
            yield from listing(item)

    yield from parallel_yield(
        [worker() for _ in range(min(workers, len(items)))], max_workers=workers
    )


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


class PushbackObserver:
    """Counts the pushback a service's retry wrappers waited out, rate limits
    and server errors alike, for an ``AdaptiveConcurrency`` pacing the work.
    Set it in ``PUSHBACK_OBSERVER`` for the span of the work. Threads this
    module starts inherit it."""

    def __init__(self) -> None:
        self._hits = 0
        self._lock = threading.Lock()

    def record(self) -> None:
        with self._lock:
            self._hits += 1

    def take_hits(self) -> int:
        with self._lock:
            hits, self._hits = self._hits, 0
            return hits


PUSHBACK_OBSERVER: contextvars.ContextVar[PushbackObserver | None] = (
    contextvars.ContextVar("pushback_observer", default=None)
)


def record_pushback() -> None:
    """For a retry wrapper to call when the service it talks to pushed back."""
    observer = PUSHBACK_OBSERVER.get()
    if observer is not None:
        observer.record()


# Workers a fresh adaptive run starts with: enough to make progress, few
# enough that a rate-limited tenant is not hammered before the first signal.
ADAPTIVE_INITIAL_WORKERS = 16
# Each worker is a thread holding its own API client, so the cap bounds memory
# as much as request rate. Pushback, not this cap, should be what stops growth.
ADAPTIVE_MAX_WORKERS = 128
# After a cut, hold the lower limit this long before growing again, so one
# burst of pushback is not answered with a burst of new workers.
ADAPTIVE_COOLDOWN_SECONDS = 5.0
# Growth is paced by time, not by finished tasks: a few huge tasks must not
# pin the limit at its start while they run.
ADAPTIVE_GROW_INTERVAL_SECONDS = 0.25
# How long the pool waits for a task to end before it looks for new work,
# which bounds the delay between a task adding work and that work starting.
ADAPTIVE_POLL_SECONDS = 0.25


class AdaptiveConcurrency:
    """A worker limit that climbs by one per interval while the service keeps
    up and halves on each burst of pushback, so a job settles near the rate
    the service allows without a fixed guess. Workers call ``observe`` as they
    make progress, and the pool calls it on every poll."""

    def __init__(
        self,
        observer: PushbackObserver,
        initial: int = ADAPTIVE_INITIAL_WORKERS,
        maximum: int = ADAPTIVE_MAX_WORKERS,
    ) -> None:
        self._observer = observer
        self._maximum = maximum
        self._limit = max(1, min(initial, maximum))
        self._cooldown_until = 0.0
        self._next_growth = 0.0
        self._lock = threading.Lock()

    @property
    def limit(self) -> int:
        with self._lock:
            return self._limit

    def observe(self) -> None:
        """Cut on pushback, else grow by one once per interval after any cooldown."""
        hits = self._observer.take_hits()
        now = time.monotonic()
        with self._lock:
            if hits:
                self._limit = max(1, self._limit // 2)
                self._cooldown_until = now + ADAPTIVE_COOLDOWN_SECONDS
                self._next_growth = self._cooldown_until
                logger.info(
                    "Adaptive concurrency: %s pushback hits, workers down to %s",
                    hits,
                    self._limit,
                )
                return
            if now < self._next_growth or self._limit >= self._maximum:
                return
            self._limit += 1
            self._next_growth = now + ADAPTIVE_GROW_INTERVAL_SECONDS


class AdaptiveTaskPool:
    """Runs zero-argument tasks with as many workers as an
    ``AdaptiveConcurrency`` allows at each moment. A task may ``add`` more
    tasks while it runs, so work can split itself as it discovers its size.
    The first failure stops new work and is raised once the running tasks
    end."""

    def __init__(self, concurrency: AdaptiveConcurrency) -> None:
        self._concurrency = concurrency
        self._pending: deque[Callable[[], None]] = deque()
        self._lock = threading.Lock()

    def add(self, task: Callable[[], None]) -> None:
        with self._lock:
            self._pending.append(task)

    def run(self) -> None:
        running: set[Future[None]] = set()
        failure: BaseException | None = None
        while True:
            while failure is None and len(running) < self._concurrency.limit:
                with self._lock:
                    task = self._pending.popleft() if self._pending else None
                if task is None:
                    break
                running.add(start_thread_future(task, name="adaptive"))
            if not running:
                with self._lock:
                    if failure is not None or not self._pending:
                        break
                continue
            done, _ = concurrent.futures.wait(
                running,
                timeout=ADAPTIVE_POLL_SECONDS,
                return_when=concurrent.futures.FIRST_COMPLETED,
            )
            for future in done:
                running.discard(future)
                error = future.exception()
                if error is not None and failure is None:
                    failure = error
            # Every poll, not only a task's end, so the limit keeps moving
            # while long tasks run.
            self._concurrency.observe()
        if failure is not None:
            raise failure
