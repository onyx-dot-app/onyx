import inspect
import threading
import time
from collections.abc import Callable, Generator, Iterator
from functools import wraps
from inspect import signature
from typing import Any, TypeVar, cast

from onyx.utils.logger import setup_logger

logger = setup_logger()

F = TypeVar("F", bound=Callable)
FG = TypeVar("FG", bound=Callable[..., Generator | Iterator])


def log_function_time(
    func_name: str | None = None,
    debug_only: bool = False,
    include_args: bool = False,
    include_args_subset: dict[str, Callable[[Any], Any]] | None = None,
) -> Callable[[F], F]:
    """Decorates a function to log the time it takes to execute.

    Args:
        func_name: The name of the function to log. If None uses func.__name__.
            Defaults to None.
        debug_only: If True, logs at the debug level. If False, logs at the
            notice level. Defaults to False.
        include_args: Whether to include the full args and kwargs in the log.
            Clobbers include_args_subset if True. Defaults to False.
        include_args_subset: An optional dict mapping arg names to callables to
            apply the arg value before logging. Only args supplied in the dict
            will be logged. Clobbered by include_args if True. Defaults to None.

    Returns:
        The decorated function.
    """

    def decorator(func: F) -> F:
        def _log_elapsed(start_time: float, *args: Any, **kwargs: Any) -> None:
            elapsed_time_str = f"{time.monotonic() - start_time:.3f}"
            log_name = func_name or func.__name__  # ty: ignore[unresolved-attribute]
            args_str = ""
            if include_args:
                args_str = f" args={args} kwargs={kwargs}"
            elif include_args_subset:
                sig = signature(func)
                bind = sig.bind(*args, **kwargs)
                bind.apply_defaults()
                for arg in include_args_subset:
                    if arg in bind.arguments:
                        arg_val = include_args_subset[arg](bind.arguments[arg])
                        args_str += f" {arg}={arg_val}"
            final_log = f"{log_name}{args_str} took {elapsed_time_str} seconds."
            if debug_only:
                logger.debug(final_log)
            else:
                logger.notice(final_log)

        if inspect.iscoroutinefunction(func):

            @wraps(func)
            async def wrapped_async(*args: Any, **kwargs: Any) -> Any:
                start_time = time.monotonic()
                result = await func(*args, **kwargs)
                _log_elapsed(start_time, *args, **kwargs)
                return result

            return cast(F, wrapped_async)

        @wraps(func)
        def wrapped_func(*args: Any, **kwargs: Any) -> Any:
            start_time = time.monotonic()
            result = func(*args, **kwargs)
            _log_elapsed(start_time, *args, **kwargs)
            return result

        return cast(F, wrapped_func)

    return decorator


def log_generator_function_time(func_name: str | None = None) -> Callable[[FG], FG]:
    def decorator(func: FG) -> FG:
        @wraps(func)
        def wrapped_func(*args: Any, **kwargs: Any) -> Any:
            start_time = time.monotonic()
            try:
                # `yield from` delegates send/throw/close to the inner generator,
                # so its own finally (cleanup) runs synchronously when an exception
                # is thrown in — making this safe to stack under @contextmanager.
                # The parenthesized form also propagates the generator's return value.
                return (yield from func(*args, **kwargs))
            finally:
                elapsed_time_str = f"{time.monotonic() - start_time:.3f}"
                log_name = func_name or func.__name__  # ty: ignore[unresolved-attribute]
                logger.info("%s took %s seconds", log_name, elapsed_time_str)

        return cast(FG, wrapped_func)

    return decorator


class PausableClock:
    """Monotonic time that stands still while paused.

    Bounds and durations that waiting for a person must not use up read it.
    A wait on `deadline - now()` that times out during a pause rechecks and
    waits again, so it ends after the active time the bound allows.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._paused_seconds = 0.0
        self._paused_since: float | None = None

    def now(self) -> float:
        """Monotonic seconds less the time spent paused."""
        with self._lock:
            now = time.monotonic()
            return now - self._paused_at(now)

    @property
    def paused_seconds(self) -> float:
        with self._lock:
            return self._paused_at(time.monotonic())

    def _paused_at(self, now: float) -> float:
        """Seconds spent paused up to `now`. The caller holds the lock."""
        since = self._paused_since
        return self._paused_seconds + (0.0 if since is None else now - since)

    def set_paused(self, paused: bool) -> None:
        with self._lock:
            if paused and self._paused_since is None:
                self._paused_since = time.monotonic()
            elif not paused and self._paused_since is not None:
                self._paused_seconds += time.monotonic() - self._paused_since
                self._paused_since = None
