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
        max_retries = 5
        starting_delay = 5
        backoff = 2
        max_delay = 600

        for attempt in range(max_retries):
            try:
                return confluence_call(*args, **kwargs)
            except HTTPError as e:
                # Check if the response or headers are None to avoid potential AttributeError
                if e.response is None or e.response.headers is None:
                    logger.warning("HTTPError with `None` as response or as headers")
                    raise e

                retry_after_header = e.response.headers.get("Retry-After")
                if (
                    e.response.status_code == 429
                    or RATE_LIMIT_MESSAGE_LOWERCASE in e.response.text.lower()
                ):
                    retry_after = None
                    if retry_after_header is not None:
                        try:
                            retry_after = int(retry_after_header)
                        except ValueError:
                            pass

                    if retry_after is not None:
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
            except AttributeError as e:
                # Some error within the Confluence library, unclear why it fails.
                # Users reported it to be intermittent, so just retry
                logger.warning(f"Confluence Internal Error, retrying... {e}")
                delay = min(starting_delay * (backoff**attempt), max_delay)
                time.sleep(delay)

                if attempt == max_retries - 1:
                    raise e

    return cast(F, wrapped_call)
