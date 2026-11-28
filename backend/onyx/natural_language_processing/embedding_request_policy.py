import asyncio
import time
from collections.abc import Awaitable, Callable, Iterator
from typing import TypeVar

from pydantic import BaseModel, ConfigDict
from tenacity import wait_exponential, wait_random
from tenacity.wait import wait_base

from onyx.natural_language_processing.embedding_providers.errors import (
    is_rate_limit_error,
)
from onyx.natural_language_processing.embedding_rate_limit import (
    EmbeddingRateLimiter,
    EmbeddingWaitTotals,
    wait_sleeps,
)

_T = TypeVar("_T")


class EmbeddingRetryBackoff(BaseModel):
    """Exponential backoff between embedding retries: waits of scale, 2*scale,
    4*scale, ... seconds, capped at max, plus up to 2s of jitter."""

    model_config = ConfigDict(frozen=True)

    scale_seconds: float
    max_seconds: float

    def wait(self) -> wait_base:
        return wait_exponential(
            multiplier=self.scale_seconds, max=self.max_seconds
        ) + wait_random(0, 2)


class EmbeddingRequestPolicy(BaseModel):
    """How embedding requests retry, the rate limit each request waits for,
    and whether a provider rate limit blocks instead of failing."""

    model_config = ConfigDict(strict=True, frozen=True, arbitrary_types_allowed=True)

    retry_backoff: EmbeddingRetryBackoff
    retry_tries: int
    rate_limiter: EmbeddingRateLimiter | None = None
    should_stop: Callable[[], bool] | None = None
    # Indexing blocks on a provider rate limit until the request goes
    # through, so rate limits never fail documents.
    block_on_provider_rate_limit: bool = False
    wait_totals: EmbeddingWaitTotals | None = None

    def send(self, request: Callable[[], _T]) -> _T:
        """Sends one provider request under this policy. The rate limit and
        provider throttling share one wait time limit per request."""
        started_at = time.monotonic()
        throttle_attempt = 0
        while True:
            if self.rate_limiter is not None:
                self.rate_limiter.acquire(
                    self.should_stop, started_at, self._add_rate_limit_wait
                )
            try:
                return request()
            except Exception as e:
                if not (self.block_on_provider_rate_limit and is_rate_limit_error(e)):
                    raise
                start = time.monotonic()
                try:
                    for sleep_seconds in self._throttle_sleeps(
                        throttle_attempt, started_at
                    ):
                        time.sleep(sleep_seconds)
                finally:
                    self._add_provider_throttle_wait(time.monotonic() - start)
                throttle_attempt += 1

    async def send_async(
        self,
        request: Callable[[], Awaitable[_T]],
        takes_rate_limit: bool = True,
    ) -> _T:
        """Sends one provider request under this policy. The rate limit and
        provider throttling share one wait time limit per request. With
        `takes_rate_limit=False`, the request takes the rate limit itself
        (`try_take_rate_limit`)."""
        started_at = time.monotonic()
        throttle_attempt = 0
        while True:
            if takes_rate_limit and self.rate_limiter is not None:
                await self.rate_limiter.acquire_async(
                    self.should_stop, started_at, self._add_rate_limit_wait
                )
            try:
                return await request()
            except Exception as e:
                if not (self.block_on_provider_rate_limit and is_rate_limit_error(e)):
                    raise
                start = time.monotonic()
                try:
                    for sleep_seconds in self._throttle_sleeps(
                        throttle_attempt, started_at
                    ):
                        await asyncio.sleep(sleep_seconds)
                finally:
                    self._add_provider_throttle_wait(time.monotonic() - start)
                throttle_attempt += 1

    def try_take_rate_limit(self) -> bool:
        """Takes a permit of the configured rate limit without waiting. True
        when there is no limit."""
        return self.rate_limiter is None or self.rate_limiter.try_acquire() == 0

    async def wait_for_full_rate_limit_async(
        self, attempt: int, started_at: float
    ) -> None:
        """Waits after `try_take_rate_limit` found the window full."""
        if self.rate_limiter is None:
            return
        start = time.monotonic()
        try:
            for sleep_seconds in self.rate_limiter.full_window_sleeps(
                attempt, started_at, self.should_stop
            ):
                await asyncio.sleep(sleep_seconds)
        finally:
            self._add_rate_limit_wait(time.monotonic() - start)

    def _throttle_sleeps(self, attempt: int, started_at: float) -> Iterator[float]:
        return wait_sleeps(
            "The embedding provider rate-limited the request",
            attempt,
            started_at,
            self.should_stop,
        )

    @property
    def counts_every_request(self) -> bool:
        """Whether this policy sees each HTTP request, so provider SDKs must
        not retry on their own."""
        return self.rate_limiter is not None or self.block_on_provider_rate_limit

    def _add_rate_limit_wait(self, seconds: float) -> None:
        if self.wait_totals is not None:
            self.wait_totals.add_rate_limit_wait(seconds)

    def _add_provider_throttle_wait(self, seconds: float) -> None:
        if self.wait_totals is not None:
            self.wait_totals.add_provider_throttle_wait(seconds)
