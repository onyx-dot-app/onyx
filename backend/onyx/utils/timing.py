import time
from collections.abc import Callable
from collections.abc import Generator
from collections.abc import Iterator
from functools import wraps
from inspect import signature
from typing import Any
from typing import cast
from typing import TypeVar

from onyx.utils.logger import setup_logger
from onyx.utils.telemetry import optional_telemetry
from onyx.utils.telemetry import RecordType

logger = setup_logger()

F = TypeVar("F", bound=Callable)
FG = TypeVar("FG", bound=Callable[..., Generator | Iterator])


def log_function_time(
    func_name: str | None = None,
    print_only: bool = False,
    debug_only: bool = False,
    include_args: bool = False,
    include_args_subset: dict[str, Callable[[Any], Any]] | None = None,
) -> Callable[[F], F]:
    """Decorates a function to log the time it takes to execute.

    Args:
        func_name: The name of the function to log. If None uses func.__name__.
            Defaults to None.
        print_only: If False, also sends the log to telemetry. Defaults to
            False.
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
        @wraps(func)
        def wrapped_func(*args: Any, **kwargs: Any) -> Any:
            # Elapsed time should use monotonic.
            start_time = time.monotonic()
            result = func(*args, **kwargs)
            elapsed_time = time.monotonic() - start_time
            elapsed_time_str = f"{elapsed_time:.3f}"
            log_name = func_name or func.__name__
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
                # These are generally more important logs so the level is a bit
                # higher.
                logger.notice(final_log)

            if not print_only:
                user = kwargs.get("user")
                optional_telemetry(
                    record_type=RecordType.LATENCY,
                    data={"function": log_name, "latency": str(elapsed_time_str)},
                    user_id=str(user.id) if user else "Unknown",
                )

            return result

        return cast(F, wrapped_func)

    return decorator


def log_generator_function_time(
    func_name: str | None = None, print_only: bool = False
) -> Callable[[FG], FG]:
    def decorator(func: FG) -> FG:
        @wraps(func)
        def wrapped_func(*args: Any, **kwargs: Any) -> Any:
            start_time = time.monotonic()
            user = kwargs.get("user")
            gen = func(*args, **kwargs)
            try:
                value = next(gen)
                while True:
                    yield value
                    value = next(gen)
            except StopIteration:
                pass
            finally:
                elapsed_time_str = f"{time.monotonic() - start_time:.3f}"
                log_name = func_name or func.__name__
                logger.info(f"{log_name} took {elapsed_time_str} seconds")
                if not print_only:
                    optional_telemetry(
                        record_type=RecordType.LATENCY,
                        data={"function": log_name, "latency": str(elapsed_time_str)},
                        user_id=str(user.id) if user else "Unknown",
                    )

        return cast(FG, wrapped_func)

    return decorator
