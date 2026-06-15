import functools
import logging
from collections.abc import Callable
from logging import Logger
from typing import Any
from typing import cast
from typing import TypeVar

import requests
from tenacity import before_sleep_log
from tenacity import retry as tenacity_retry
from tenacity import retry_if_exception_type
from tenacity import stop_after_attempt
from tenacity import stop_never
from tenacity import wait_exponential
from tenacity import wait_random
from tenacity.stop import stop_base
from tenacity.wait import wait_base

from onyx.configs.app_configs import REQUEST_TIMEOUT_SECONDS
from onyx.utils.logger import setup_logger

logger = setup_logger()


F = TypeVar("F", bound=Callable[..., Any])


def retry_builder(
    tries: int = 20,
    delay: float = 0.1,
    max_delay: float | None = 60,
    backoff: float = 2,
    jitter: tuple[float, float] | float = 1,
    exceptions: type[Exception] | tuple[type[Exception], ...] = (Exception,),
) -> Callable[[F], F]:
    """Builds a generic wrapper/decorator for calls to external APIs that
    may fail due to rate limiting, flakes, or other reasons. Applies exponential
    backoff with jitter to retry the call."""

    # mirror the semantics of the legacy `retry` package: the n-th wait is
    # `delay * backoff**n` capped at `max_delay`, plus a random jitter
    wait: wait_base = wait_exponential(
        multiplier=delay,
        exp_base=backoff,
        max=max_delay if max_delay is not None else float("inf"),
    )
    if isinstance(jitter, tuple):
        wait = wait + wait_random(jitter[0], jitter[1])
    elif jitter:
        wait = wait + wait_random(0, jitter)

    # `tries=-1` in the legacy `retry` package meant "retry forever"
    stop: stop_base = stop_after_attempt(tries) if tries >= 0 else stop_never

    def retry_with_default(func: F) -> F:
        # `wraps` is intentionally applied *below* the tenacity decorator: it
        # renames the inner function before tenacity captures it, so the
        # `before_sleep_log` warnings name the real call site instead of
        # `wrapped_func`. Final metadata is correct either way (tenacity
        # applies `functools.wraps` to whatever it wraps).
        @tenacity_retry(
            retry=retry_if_exception_type(exceptions),
            wait=wait,
            stop=stop,
            before_sleep=before_sleep_log(cast(Logger, logger), logging.WARNING),
            reraise=True,
        )
        @functools.wraps(func)
        def wrapped_func(*args: list, **kwargs: dict[str, Any]) -> Any:
            return func(*args, **kwargs)

        return cast(F, wrapped_func)

    return retry_with_default


def request_with_retries(
    method: str,
    url: str,
    *,
    data: dict[str, Any] | None = None,
    headers: dict[str, Any] | None = None,
    params: dict[str, Any] | None = None,
    timeout: int = REQUEST_TIMEOUT_SECONDS,
    stream: bool = False,
    tries: int = 8,
    delay: float = 1,
    backoff: float = 2,
) -> requests.Response:
    # jitter=0 + max_delay=None preserves the exact wait curve this function
    # had on the legacy `retry` package: delay * backoff**n, uncapped
    @retry_builder(tries=tries, delay=delay, max_delay=None, backoff=backoff, jitter=0)
    def _make_request() -> requests.Response:
        response = requests.request(
            method=method,
            url=url,
            data=data,
            headers=headers,
            params=params,
            timeout=timeout,
            stream=stream,
        )
        try:
            response.raise_for_status()
        except requests.exceptions.HTTPError:
            logger.exception(
                "Request failed:\n%s",
                {
                    "method": method,
                    "url": url,
                    "data": data,
                    "headers": headers,
                    "params": params,
                    "timeout": timeout,
                    "stream": stream,
                },
            )
            raise
        return response

    return _make_request()
