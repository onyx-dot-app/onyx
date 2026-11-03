"""The embedding rate limiter against a real Redis.

Each test uses a unique tenant, so runs cannot collide. Separate limiter
objects stand in for separate docprocessing pods: they share only Redis.
"""

import time
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch
from uuid import uuid4

import pytest

from onyx.connectors.models import ConnectorStopSignal
from onyx.natural_language_processing.embedding_rate_limit import (
    _WINDOW_KEY,
    EmbeddingRateLimiter,
    EmbeddingWaitTimeoutError,
)
from onyx.redis.redis_pool import get_redis_client

_MODULE = "onyx.natural_language_processing.embedding_rate_limit"


@pytest.fixture(autouse=True)
def _short_retry_interval() -> Iterator[None]:
    """Retry every 0.5s instead of every minute."""
    with (
        patch(f"{_MODULE}._RETRY_INTERVAL_SECONDS", 0.5),
        patch(f"{_MODULE}._RETRY_INTERVAL_JITTER_SECONDS", 0.0),
    ):
        yield


@pytest.fixture
def tenant_id() -> Iterator[str]:
    tenant = f"tenant_test_{uuid4().hex[:12]}"
    yield tenant
    get_redis_client(tenant_id=tenant).delete(_WINDOW_KEY)


def test_window_is_shared_between_workers(tenant_id: str) -> None:
    pod_a = EmbeddingRateLimiter(tenant_id, max_requests=3, period_seconds=10)
    pod_b = EmbeddingRateLimiter(tenant_id, max_requests=3, period_seconds=10)

    assert pod_a._try_acquire() == 0
    assert pod_b._try_acquire() == 0
    assert pod_a._try_acquire() == 0

    wait = pod_b._try_acquire()
    assert 0 < wait <= 10


def test_tenants_have_separate_windows(tenant_id: str) -> None:
    other_tenant = f"tenant_test_{uuid4().hex[:12]}"
    try:
        full = EmbeddingRateLimiter(tenant_id, max_requests=1, period_seconds=10)
        other = EmbeddingRateLimiter(other_tenant, max_requests=1, period_seconds=10)
        assert full._try_acquire() == 0
        assert full._try_acquire() > 0
        assert other._try_acquire() == 0
    finally:
        get_redis_client(tenant_id=other_tenant).delete(_WINDOW_KEY)


def test_acquire_blocks_until_a_slot_frees(tenant_id: str) -> None:
    limiter = EmbeddingRateLimiter(tenant_id, max_requests=2, period_seconds=1)
    limiter.acquire()
    limiter.acquire()

    start = time.monotonic()
    limiter.acquire()
    elapsed = time.monotonic() - start

    # The window frees after 1s; retries come every 0.5s.
    assert 0.9 <= elapsed <= 2


def test_wait_gives_up_at_the_time_limit(tenant_id: str) -> None:
    limiter = EmbeddingRateLimiter(tenant_id, max_requests=1, period_seconds=60)
    limiter.acquire()

    waits: list[float] = []
    start = time.monotonic()
    with (
        patch(f"{_MODULE}._MAX_TOTAL_WAIT_SECONDS", 1.2),
        pytest.raises(EmbeddingWaitTimeoutError),
    ):
        limiter.acquire(on_wait=waits.append)
    # 0.5s retries up to the limit, then the limit check fails.
    assert 1.2 <= time.monotonic() - start <= 2.5
    # The wait is reported even though it ended in a timeout.
    assert len(waits) == 1 and waits[0] >= 1.2


def test_stop_signal_ends_the_wait(tenant_id: str) -> None:
    limiter = EmbeddingRateLimiter(tenant_id, max_requests=1, period_seconds=60)
    limiter.acquire()

    start = time.monotonic()
    with pytest.raises(ConnectorStopSignal):
        limiter.acquire(should_stop=lambda: True)
    assert time.monotonic() - start < 1


def test_concurrent_workers_never_exceed_the_limit(tenant_id: str) -> None:
    def take_slot(_: int) -> float:
        limiter = EmbeddingRateLimiter(tenant_id, max_requests=5, period_seconds=30)
        return limiter._try_acquire()

    with ThreadPoolExecutor(max_workers=20) as pool:
        waits = list(pool.map(take_slot, range(40)))

    assert sum(1 for wait in waits if wait == 0) == 5
