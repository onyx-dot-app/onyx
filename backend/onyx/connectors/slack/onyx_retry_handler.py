import math
import random
import time
from typing import cast
from typing import Optional

from redis import Redis
from redis.lock import Lock as RedisLock
from slack_sdk.http_retry.handler import RetryHandler
from slack_sdk.http_retry.request import HttpRequest
from slack_sdk.http_retry.response import HttpResponse
from slack_sdk.http_retry.state import RetryState

from onyx.utils.logger import setup_logger

logger = setup_logger()


class OnyxRedisSlackRetryHandler(RetryHandler):
    """Another way to do this is just to do exponential backoff. Might be easier."""

    LOCK_TTL = 60  # used to serialize access to the retry TTL
    LOCK_BLOCKING_TIMEOUT = 60  # how long to wait for the lock

    """RetryHandler that does retries for rate limited errors."""

    def __init__(
        self,
        max_retry_count: int,
        delay_lock: str,
        delay_key: str,
        r: Redis,
    ):
        """

        delay_lock: the redis key to use with RedisLock (to synchronize access to delay_key)
        delay_key: the redis key containing a shared TTL
        """
        super().__init__(max_retry_count=max_retry_count)
        self._redis: Redis = r
        self._delay_lock = delay_lock
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
        """it seems this function is responsible for the wait to retry"""

        if response is None:
            if error:
                raise error

            return

        state.next_attempt_requested = True  # this signals the caller to retry

        # calculate wait duration based on retry-after + some jitter
        duration_s = 1.0  # seconds

        retry_after_header_name: Optional[str] = None
        for k in response.headers.keys():
            if k.lower() == "retry-after":
                retry_after_header_name = k
                break

        if retry_after_header_name is None:
            # This situation usually does not arise. Just in case.
            duration_s += random.random()
        else:
            retry_after_value = response.headers.get(retry_after_header_name)
            if not retry_after_value:
                duration_s += random.random()
            else:
                retry_after_value_int = int(retry_after_value[0])
                jitter = retry_after_value_int * 0.25 * random.random()
                duration_s = math.ceil(retry_after_value_int + jitter)

        # lock and extend the ttl
        lock: RedisLock = self._redis.lock(
            self._delay_key,
            timeout=OnyxRedisSlackRetryHandler.LOCK_TTL,
            thread_local=False,
        )

        acquired = lock.acquire(
            blocking_timeout=OnyxRedisSlackRetryHandler.LOCK_BLOCKING_TIMEOUT / 2
        )

        ttl_ms: int | None = None

        try:
            if acquired:
                # if we can get the lock, then read and extend the ttl
                ttl_ms = cast(int, self._redis.pttl("retry-after"))
                ttl_ms_new = ttl_ms + int(duration_s * 1000.0)
                self._redis.set("retry-after", "1", px=ttl_ms_new)
            else:
                # if we can't get the lock, just go ahead.
                # TODO: if we know our actual parallelism, multiplying by that
                # would be a pretty good idea
                ttl_ms_new = int(duration_s * 1000.0)
        finally:
            if acquired:
                lock.release()

        logger.warning(
            f"Slack rate limited: current_shared_delay_ms={ttl_ms} new_shared_delay_ms={ttl_ms_new}"
        )

        # TODO: would be good to take an event var and sleep in short increments to
        # allow for a clean exit / exception
        time.sleep(ttl_ms_new / 1000.0)

        state.increment_current_attempt()
