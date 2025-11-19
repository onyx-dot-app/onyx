import random
from typing import cast
from typing import Optional

from redis import Redis
from slack_sdk.http_retry.handler import RetryHandler
from slack_sdk.http_retry.request import HttpRequest
from slack_sdk.http_retry.response import HttpResponse
from slack_sdk.http_retry.state import RetryState

from onyx.utils.logger import setup_logger

logger = setup_logger()


class OnyxRedisSlackRetryHandler(RetryHandler):
    """
    This class uses Redis to share a rate limit among multiple threads.

    As currently implemented, this code is already surrounded by a lock in Redis
    via an override of _perform_urllib_http_request in OnyxSlackWebClient.

    This just sets the desired retry delay with TTL in redis. In conjunction with
    a custom subclass of the client, the value is read and obeyed prior to an API call
    and also serialized.

    Another way to do this is just to do exponential backoff. Might be easier?

    Adapted from slack's RateLimitErrorRetryHandler.
    """

    """RetryHandler that does retries for rate limited errors."""

    def __init__(
        self,
        max_retry_count: int,
        delay_key: str,
        r: Redis,
    ):
        """
        delay_lock: the redis key to use with RedisLock (to synchronize access to delay_key)
        delay_key: the redis key containing a shared TTL
        """
        super().__init__(max_retry_count=max_retry_count)
        self._redis: Redis = r
        self._delay_key = delay_key

    def _can_retry(
        self,
        *,
        state: RetryState,
        request: HttpRequest,
        response: Optional[HttpResponse] = None,
        error: Optional[Exception] = None,
    ) -> bool:
        return response is not None and response.status_code == 429

    def prepare_for_next_attempt(
        self,
        *,
        state: RetryState,
        request: HttpRequest,
        response: Optional[HttpResponse] = None,
        error: Optional[Exception] = None,
    ) -> None:
        """As initially designed by the SDK authors, this function is responsible for
        the wait to retry ... aka we actually sleep in this function.

        This doesn't work well with multiple clients because every thread is unaware
        of the current retry value until it actually calls the endpoint.

        We're combining this with an actual subclass of the slack web client so
        that the delay is used BEFORE calling an API endpoint. The subclassed client
        has already taken the lock in redis when this method is called.
        """
        ttl_ms: int | None = None

        retry_after_value: str | None = None
        retry_after_header_name: Optional[str] = None
        duration_s: float = 1.0  # seconds

        if response is None:
            # NOTE(rkuo): this logic comes from RateLimitErrorRetryHandler.
            # This reads oddly, as if the caller itself could raise the exception.
            # We don't have the luxury of changing this.
            if error:
                raise error

            return

        state.next_attempt_requested = True  # this signals the caller to retry

        # calculate wait duration based on retry-after + some jitter
        for k in response.headers.keys():
            if k.lower() == "retry-after":
                retry_after_header_name = k
                break

        try:
            if retry_after_header_name is None:
                # This situation usually does not arise. Just in case.
                raise ValueError(
                    "OnyxRedisSlackRetryHandler.prepare_for_next_attempt: retry-after header name is None"
                )

            retry_after_header_value = response.headers.get(retry_after_header_name)
            if not retry_after_header_value:
                raise ValueError(
                    "OnyxRedisSlackRetryHandler.prepare_for_next_attempt: retry-after header value is None"
                )

            # Handle case where header value might be a list
            retry_after_value = (
                retry_after_header_value[0]
                if isinstance(retry_after_header_value, list)
                else retry_after_header_value
            )

            retry_after_value_int = int(
                retry_after_value
            )  # will raise ValueError if somehow we can't convert to int
            jitter = retry_after_value_int * 0.25 * random.random()
            duration_s = retry_after_value_int + jitter
        except ValueError:
            duration_s += random.random()

        # Read and extend the ttl
        ttl_ms = cast(int, self._redis.pttl(self._delay_key))
        if ttl_ms < 0:  # negative values are error status codes ... see docs
            ttl_ms = 0
        ttl_ms_new = ttl_ms + int(duration_s * 1000.0)
        self._redis.set(self._delay_key, "1", px=ttl_ms_new)

        logger.warning(
            f"OnyxRedisSlackRetryHandler.prepare_for_next_attempt setting delay: "
            f"current_attempt={state.current_attempt} "
            f"retry-after={retry_after_value} "
            f"{ttl_ms_new=}"
        )

        state.increment_current_attempt()
