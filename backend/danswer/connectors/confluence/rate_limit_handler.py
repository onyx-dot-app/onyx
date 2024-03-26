from collections.abc import Callable
from typing import Any
from typing import cast
from typing import TypeVar

from requests import HTTPError
from retry import retry


F = TypeVar("F", bound=Callable[..., Any])


RATE_LIMIT_MESSAGE_LOWERCASE = "Rate limit exceeded".lower()


class ConfluenceRateLimitError(Exception):
    pass


def make_confluence_call_handle_rate_limit(confluence_call: F) -> F:
    @retry(
        exceptions=ConfluenceRateLimitError,
        tries=10,
        delay=1,
        max_delay=600,  # 10 minutes
        backoff=2,
        jitter=1,
    )
    def wrapped_call(*args: list[Any], **kwargs: Any) -> Any:
        try:
            return confluence_call(*args, **kwargs)
        except HTTPError as e:
            if (
                e.response.status_code == 429
                or RATE_LIMIT_MESSAGE_LOWERCASE in e.response.text.lower()
            ):
                raise ConfluenceRateLimitError()
            raise

    return cast(F, wrapped_call)
