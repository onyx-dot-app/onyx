import asyncio
import random
import threading
import time
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import AsyncExitStack, asynccontextmanager
from functools import partial
from typing import TypeVar

from pydantic import BaseModel, ConfigDict

from onyx.connectors.models import ConnectorStopSignal
from onyx.natural_language_processing.embedding_providers.errors import (
    is_rate_limit_error,
)
from onyx.natural_language_processing.embedding_request_policy import (
    EmbeddingRequestPolicy,
)
from onyx.utils.adaptive_semaphore import AdaptiveSemaphore
from shared_configs.configs import (
    VERTEXAI_EMBEDDING_INITIAL_CONCURRENCY,
    VERTEXAI_EMBEDDING_MAX_CONCURRENCY,
)

_T = TypeVar("_T")

_TRANSIENT_STATUSES: frozenset[int] = frozenset({500, 502, 503, 504})


class VertexRetrySettings(BaseModel):
    model_config = ConfigDict(frozen=True)

    stop_check_interval_seconds: float = 5.0
    backoff_base_seconds: float = 0.25
    backoff_max_seconds: float = 16.0
    # After this, the request policy takes over the rate limit with its own,
    # longer schedule.
    rate_limit_retry_budget_seconds: float = 60.0
    transient_error_tries: int = 3

    def backoff(self, attempt: int) -> float:
        ceiling = min(self.backoff_max_seconds, self.backoff_base_seconds * 2**attempt)
        return ceiling / 2 + random.uniform(0, ceiling / 2)


def is_transient_vertex_error(error: BaseException) -> bool:
    # Timeouts are not transient: each one already waited the full timeout.
    import aiohttp
    from google.genai import errors as genai_errors

    if isinstance(error, genai_errors.ServerError):
        return error.code in _TRANSIENT_STATUSES
    return isinstance(error, aiohttp.ClientConnectionError)


class _SlotRetries:
    """Resends happen inside the slot: a free slot would go to a new request
    that the provider refuses too."""

    def __init__(
        self, settings: VertexRetrySettings, policy: EmbeddingRequestPolicy
    ) -> None:
        self._settings = settings
        self._policy = policy
        self._indexing = policy.block_on_provider_rate_limit
        # A configured rate limiter must see every request.
        self._retries_rate_limits = self._indexing and policy.rate_limiter is None
        self._rate_limit_deadline = (
            time.monotonic() + settings.rate_limit_retry_budget_seconds
        )
        self._rate_limits = 0
        self._transient_failures = 0

    def wait_before_resend(
        self, error: Exception, limit: AdaptiveSemaphore
    ) -> float | None:
        if is_rate_limit_error(error):
            limit.record_rate_limit()
            return self._rate_limit_wait()
        if self._indexing and is_transient_vertex_error(error):
            return self._transient_error_wait()
        return None

    def _rate_limit_wait(self) -> float | None:
        if (
            not self._retries_rate_limits
            or time.monotonic() >= self._rate_limit_deadline
        ):
            return None
        wait = self._settings.backoff(self._rate_limits)
        self._rate_limits += 1
        if self._policy.wait_totals is not None:
            self._policy.wait_totals.add_provider_throttle_wait(wait)
        return wait

    def _transient_error_wait(self) -> float | None:
        self._transient_failures += 1
        if self._transient_failures >= self._settings.transient_error_tries:
            return None
        return self._settings.backoff(self._transient_failures - 1)


class VertexRequestScheduler:
    def __init__(
        self,
        *,
        max_concurrency: int,
        initial_concurrency: int,
        settings: VertexRetrySettings | None = None,
    ) -> None:
        self._max_concurrency = max_concurrency
        self._initial_concurrency = min(initial_concurrency, max_concurrency)
        self._settings = settings or VertexRetrySettings()
        self._process_limit = AdaptiveSemaphore(
            initial=max_concurrency, minimum=max_concurrency, maximum=max_concurrency
        )
        self._model_limits: dict[str, AdaptiveSemaphore] = {}
        self._lock = threading.Lock()

    @property
    def process_limit(self) -> AdaptiveSemaphore:
        return self._process_limit

    def model_limit(self, project_location_model: str) -> AdaptiveSemaphore:
        # Vertex counts quota per project and base model.
        with self._lock:
            limit = self._model_limits.get(project_location_model)
            if limit is None:
                limit = AdaptiveSemaphore(
                    initial=self._initial_concurrency,
                    minimum=1,
                    maximum=self._max_concurrency,
                )
                self._model_limits[project_location_model] = limit
            return limit

    async def send(
        self,
        project_location_model: str,
        request: Callable[[], Awaitable[_T]],
        policy: EmbeddingRequestPolicy,
    ) -> _T:
        limit = self.model_limit(project_location_model)
        # Outside the policy, so its wait limit does not count the slot wait.
        async with self._slot(limit, policy.should_stop):
            return await policy.send_async(
                partial(self._send_in_slot, request, limit, policy)
            )

    @asynccontextmanager
    async def _slot(
        self,
        limit: AdaptiveSemaphore,
        should_stop: Callable[[], bool] | None,
    ) -> AsyncIterator[None]:
        async with AsyncExitStack() as stack:
            for each in (limit, self._process_limit):
                await self._acquire_unless_stopped(each, should_stop)
                stack.callback(each.release)
            yield

    async def _acquire_unless_stopped(
        self,
        limit: AdaptiveSemaphore,
        should_stop: Callable[[], bool] | None,
    ) -> None:
        while True:
            try:
                await asyncio.wait_for(
                    limit.acquire(),
                    timeout=self._settings.stop_check_interval_seconds,
                )
                return
            except TimeoutError:
                if should_stop is not None and should_stop():
                    raise ConnectorStopSignal(
                        "Stop signal while waiting to embed"
                    ) from None

    async def _send_in_slot(
        self,
        request: Callable[[], Awaitable[_T]],
        limit: AdaptiveSemaphore,
        policy: EmbeddingRequestPolicy,
    ) -> _T:
        retries = _SlotRetries(self._settings, policy)
        while True:
            try:
                result = await request()
            except Exception as e:
                wait = retries.wait_before_resend(e, limit)
                if wait is None:
                    raise
                if policy.should_stop is not None and policy.should_stop():
                    raise ConnectorStopSignal(
                        "Stop signal while waiting to embed"
                    ) from e
                await asyncio.sleep(wait)
                continue
            limit.record_success()
            return result


VERTEX_SCHEDULER = VertexRequestScheduler(
    max_concurrency=VERTEXAI_EMBEDDING_MAX_CONCURRENCY,
    initial_concurrency=VERTEXAI_EMBEDDING_INITIAL_CONCURRENCY,
)
