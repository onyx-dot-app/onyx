from __future__ import annotations

import time
from collections.abc import Callable
from typing import Any
from typing import TypeVar

from onyx.connectors.cross_connector_utils.rate_limit_wrapper import (
    rate_limit_builder,
)
from onyx.connectors.cross_connector_utils.rate_limit_wrapper import (
    RateLimitTriedTooManyTimesError,
)
from onyx.utils.logger import setup_logger

logger = setup_logger()

T = TypeVar("T")

# HubSpot exposes a ten second rolling window (x-hubspot-ratelimit-interval-milliseconds)
# with a maximum of 190 requests, and a per-second limit of 19 requests.
_HUBSPOT_TEN_SECOND_LIMIT = 190
_HUBSPOT_TEN_SECOND_PERIOD = 10  # seconds
_HUBSPOT_SECONDLY_LIMIT = 19
_HUBSPOT_SECONDLY_PERIOD = 1  # second
_DEFAULT_SLEEP_SECONDS = 10
_SLEEP_PADDING_SECONDS = 1.0
_MAX_RATE_LIMIT_RETRIES = 5


def _extract_header(headers: Any, key: str) -> str | None:
    if headers is None:
        return None

    getter = getattr(headers, "get", None)
    if callable(getter):
        value = getter(key)
        if value is not None:
            return value

    if isinstance(headers, dict):
        value = headers.get(key)
        if value is not None:
            return value

    return None


def is_rate_limit_error(exception: Exception) -> bool:
    status = getattr(exception, "status", None)
    if status == 429:
        return True

    headers = getattr(exception, "headers", None)
    if headers is not None:
        remaining = _extract_header(headers, "x-hubspot-ratelimit-remaining")
        if remaining == "0":
            return True
        secondly_remaining = _extract_header(
            headers, "x-hubspot-ratelimit-secondly-remaining"
        )
        if secondly_remaining == "0":
            return True

    message = str(exception)
    return "RATE_LIMIT" in message or "Too Many Requests" in message


def get_rate_limit_retry_delay_seconds(exception: Exception) -> float:
    headers = getattr(exception, "headers", None)

    retry_after = _extract_header(headers, "Retry-After")
    if retry_after:
        try:
            return float(retry_after) + _SLEEP_PADDING_SECONDS
        except ValueError:
            logger.debug(
                "Failed to parse Retry-After header '%s' as float", retry_after
            )

    interval_ms = _extract_header(headers, "x-hubspot-ratelimit-interval-milliseconds")
    if interval_ms:
        try:
            return float(interval_ms) / 1000.0 + _SLEEP_PADDING_SECONDS
        except ValueError:
            logger.debug(
                "Failed to parse x-hubspot-ratelimit-interval-milliseconds '%s' as float",
                interval_ms,
            )

    secondly_limit = _extract_header(headers, "x-hubspot-ratelimit-secondly")
    if secondly_limit:
        try:
            per_second = max(float(secondly_limit), 1.0)
            return (1.0 / per_second) + _SLEEP_PADDING_SECONDS
        except ValueError:
            logger.debug(
                "Failed to parse x-hubspot-ratelimit-secondly '%s' as float",
                secondly_limit,
            )

    return _DEFAULT_SLEEP_SECONDS + _SLEEP_PADDING_SECONDS


class HubSpotRateLimiter:
    def __init__(
        self,
        *,
        ten_second_limit: int = _HUBSPOT_TEN_SECOND_LIMIT,
        ten_second_period: int = _HUBSPOT_TEN_SECOND_PERIOD,
        secondly_limit: int = _HUBSPOT_SECONDLY_LIMIT,
        secondly_period: int = _HUBSPOT_SECONDLY_PERIOD,
        max_retries: int = _MAX_RATE_LIMIT_RETRIES,
    ) -> None:
        self._max_retries = max_retries

        @rate_limit_builder(max_calls=secondly_limit, period=secondly_period)
        @rate_limit_builder(max_calls=ten_second_limit, period=ten_second_period)
        def _execute(callable_: Callable[[], T]) -> T:
            return callable_()

        self._execute = _execute

    def call(self, func: Callable[..., T], *args: Any, **kwargs: Any) -> T:
        attempts = 0

        while True:
            try:
                return self._execute(lambda: func(*args, **kwargs))
            except Exception as exc:  # pylint: disable=broad-except
                if not is_rate_limit_error(exc):
                    raise

                attempts += 1
                if attempts > self._max_retries:
                    raise RateLimitTriedTooManyTimesError(
                        "Exceeded configured HubSpot rate limit retries"
                    ) from exc

                wait_time = get_rate_limit_retry_delay_seconds(exc)
                logger.notice(
                    "HubSpot rate limit reached. Sleeping %.2f seconds before retrying.",
                    wait_time,
                )
                time.sleep(wait_time)
