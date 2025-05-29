import threading
import time
from typing import Any
from typing import cast
from typing import Dict
from urllib.request import Request

from redis import Redis
from redis.lock import Lock as RedisLock
from slack_sdk import WebClient

from onyx.connectors.slack.utils import ONYX_SLACK_LOCK_BLOCKING_TIMEOUT
from onyx.connectors.slack.utils import ONYX_SLACK_LOCK_TOTAL_BLOCKING_TIMEOUT
from onyx.connectors.slack.utils import ONYX_SLACK_LOCK_TTL
from onyx.utils.logger import setup_logger

logger = setup_logger()


class OnyxSlackWebClient(WebClient):
    """Use in combination with the Onyx Retry Handler.

    This client wrapper enforces a proper retry delay through redis BEFORE the api call
    so that multiple clients can synchronize and rate limit properly.

    The retry handler writes the correct delay value to redis so that it is can be used
    by this wrapper.

    """

    def __init__(
        self, delay_lock: str, delay_key: str, r: Redis, *args: Any, **kwargs: Any
    ) -> None:
        super().__init__(*args, **kwargs)
        self._delay_key = delay_key
        self._delay_lock = delay_lock
        self._redis: Redis = r
        self.num_requests: int = 0
        self._lock = threading.Lock()

    def _perform_urllib_http_request(
        self, *, url: str, args: Dict[str, Dict[str, Any]]
    ) -> Dict[str, Any]:
        """By locking around the base class method, we ensure that both the delay from
        Redis and parsing/writing of retry values to Redis are handled properly in
        one place"""
        # lock and extend the ttl
        lock: RedisLock = self._redis.lock(
            self._delay_lock,
            timeout=ONYX_SLACK_LOCK_TTL,
        )

        # try to acquire the lock
        start = time.monotonic()
        while True:
            acquired = lock.acquire(blocking_timeout=ONYX_SLACK_LOCK_BLOCKING_TIMEOUT)
            if acquired:
                break

            # if we couldn't acquire the lock but it exists, there's at least some activity
            # so keep trying...
            if self._redis.exists(self._delay_lock):
                continue

            if time.monotonic() - start > ONYX_SLACK_LOCK_TOTAL_BLOCKING_TIMEOUT:
                raise RuntimeError(
                    f"OnyxSlackWebClient._perform_urllib_http_request - "
                    f"timed out waiting for lock: {ONYX_SLACK_LOCK_TOTAL_BLOCKING_TIMEOUT=}"
                )

        try:
            result = super()._perform_urllib_http_request(url=url, args=args)
        finally:
            if lock.owned():
                lock.release()
            else:
                logger.warning(
                    "OnyxSlackWebClient._perform_urllib_http_request lock not owned on release"
                )

        time.monotonic() - start
        # logger.info(
        #     f"OnyxSlackWebClient._perform_urllib_http_request: Releasing lock: {elapsed=}"
        # )

        return result

    def _perform_urllib_http_request_internal(
        self,
        url: str,
        req: Request,
    ) -> Dict[str, Any]:
        """Overrides the internal method which is mostly the direct call to
        urllib/urlopen ... so this is a good place to perform our delay."""

        # read and execute the delay
        delay_ms = cast(int, self._redis.pttl(self._delay_key))
        if delay_ms < 0:  # negative values are error status codes ... see docs
            delay_ms = 0

        if delay_ms > 0:
            logger.warning(
                f"OnyxSlackWebClient._perform_urllib_http_request_internal delay: "
                f"{delay_ms=} "
                f"{self.num_requests=}"
            )

            time.sleep(delay_ms / 1000.0)

        result = super()._perform_urllib_http_request_internal(url, req)

        with self._lock:
            self.num_requests += 1

        # the delay key should have naturally expired by this point
        return result
