from collections.abc import Callable
from logging import Logger
from typing import Any
from typing import cast
from typing import TypeVar

from retry import retry

from danswer.utils.logger import setup_logger

logger = setup_logger()


F = TypeVar("F", bound=Callable[..., Any])


def retry_builder(
    tries: int = 10,
    delay: float = 0.1,
    max_delay: float | None = None,
    backoff: float = 2,
    jitter: tuple[float, float] | float = 1,
) -> Callable[[F], F]:
    """Builds a generic wrapper/decorator for calls to external APIs that
    may fail due to rate limiting, flakes, or other reasons. Applies exponential
    backoff with jitter to retry the call."""

    def retry_with_default(func: F) -> F:
        @retry(
            tries=tries,
            delay=delay,
            max_delay=max_delay,
            backoff=backoff,
            jitter=jitter,
            logger=cast(Logger, logger),
        )
        def wrapped_func(*args: list, **kwargs: dict[str, Any]) -> Any:
            return func(*args, **kwargs)

        return cast(F, wrapped_func)

    return retry_with_default
