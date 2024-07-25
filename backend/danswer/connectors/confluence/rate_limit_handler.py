import time
from collections.abc import Callable
from typing import Any
from typing import cast
from typing import TypeVar

from requests import HTTPError

from danswer.utils.logger import setup_logger

logger = setup_logger()


F = TypeVar("F", bound=Callable[..., Any])


RATE_LIMIT_MESSAGE_LOWERCASE = "Rate limit exceeded".lower()


class ConfluenceRateLimitError(Exception):
    pass


def make_confluence_call_handle_rate_limit(confluence_call: F) -> F:
    def wrapped_call(*args: list[Any], **kwargs: Any) -> Any:
        starting_delay = 5
        backoff = 2
        max_delay = 600

        for attempt in range(10):
            try:
                return confluence_call(*args, **kwargs)
            except HTTPError as e:
                if (
                    e.response.status_code == 429
                    or RATE_LIMIT_MESSAGE_LOWERCASE in e.response.text.lower()
                ):
                    retry_after = None
                    try:
                        retry_after = int(e.response.headers.get("Retry-After"))
                    except (ValueError, TypeError):
                        pass

                    if retry_after:
                        logger.warning(
                            f"Rate limit hit. Retrying after {retry_after} seconds..."
                        )
                        time.sleep(retry_after)
                    else:
                        logger.warning(
                            "Rate limit hit. Retrying with exponential backoff..."
                        )
                        delay = min(starting_delay * (backoff**attempt), max_delay)
                        time.sleep(delay)
                else:
                    # re-raise, let caller handle
                    raise

    return cast(F, wrapped_call)
