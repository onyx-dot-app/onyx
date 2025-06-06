import time
from collections.abc import Callable
from collections.abc import Generator
from collections.abc import Iterator
from functools import wraps
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
) -> Callable[[F], F]:
    def decorator(func: F) -> F:
        @wraps(func)
        def wrapped_func(*args: Any, **kwargs: Any) -> Any:
            start_time = time.time()
            user = kwargs.get("user")
            result = func(*args, **kwargs)
            elapsed_time = time.time() - start_time
            elapsed_time_str = f"{elapsed_time:.3f}"
            log_name = func_name or func.__name__
            args_str = f" args={args} kwargs={kwargs}" if include_args else ""
            final_log = f"{log_name}{args_str} took {elapsed_time_str} seconds"
            if debug_only:
                logger.debug(final_log)
            else:
                # These are generally more important logs so the level is a bit higher
                logger.notice(final_log)

            if not print_only:
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
            start_time = time.time()
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
                elapsed_time_str = str(time.time() - start_time)
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
