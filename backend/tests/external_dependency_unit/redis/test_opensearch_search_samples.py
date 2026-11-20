"""External dependency tests for the search samples of the admin Service Status page.

The samples go through the real shared cache (Redis), under a test prefix.
"""

import json
import uuid
from collections.abc import Generator

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from ee.onyx.server.service_status import api as service_status_api
from onyx.auth.users import current_user
from onyx.cache.interface import CacheBackend
from onyx.cache.redis_backend import RedisCacheBackend
from onyx.db.enums import Permission
from onyx.db.models import User
from onyx.document_index.opensearch import search_samples
from onyx.document_index.opensearch.constants import OpenSearchSearchType
from onyx.document_index.opensearch.models import (
    SearchActivity,
    SearchResult,
    SearchSample,
)
from onyx.document_index.opensearch.search_samples import (
    flush_search_samples,
    read_search_activity,
    record_search_sample,
)
from onyx.error_handling.exceptions import register_onyx_exception_handlers
from onyx.redis.redis_pool import get_redis_client
from onyx.server.metrics.opensearch_search import (
    observe_opensearch_search,
    track_opensearch_search,
)

MINUTE_MS = 60_000


@pytest.fixture
def cache(monkeypatch: pytest.MonkeyPatch) -> Generator[CacheBackend, None, None]:
    redis = get_redis_client(tenant_id=f"test_search_samples_{uuid.uuid4().hex}")
    backend = RedisCacheBackend(redis)
    monkeypatch.setattr(search_samples, "get_shared_cache_backend", lambda: backend)
    monkeypatch.setattr(search_samples, "RECORDING_ENABLED", True)
    # The tests flush by hand; a background flusher would outlive them.
    monkeypatch.setattr(search_samples, "_start_flusher_locked", lambda: None)
    flush_search_samples()
    yield backend
    backend.delete_prefix(search_samples.SAMPLE_KEY_PREFIX)


def _write(cache: CacheBackend, samples: list[SearchSample]) -> None:
    """Writes samples the way a flush does, as one batch per minute."""
    by_minute: dict[int, list[dict[str, object]]] = {}
    for sample in samples:
        by_minute.setdefault(sample.at_ms // MINUTE_MS, []).append(
            sample.model_dump(mode="json")
        )
    for minute, batch in by_minute.items():
        cache.set_add(
            f"{search_samples.SAMPLE_KEY_PREFIX}:{minute}",
            json.dumps({"id": uuid.uuid4().hex, "samples": batch}),
        )


def _sample(
    at_ms: int, client_ms: float, result: SearchResult = SearchResult.OK
) -> SearchSample:
    return SearchSample(
        at_ms=at_ms,
        client_ms=client_ms,
        server_ms=None if result != SearchResult.OK else int(client_ms * 0.8),
        search_type="hybrid",
        result=result,
    )


def test_recorded_searches_are_read_back(cache: CacheBackend) -> None:  # noqa: ARG001
    with pytest.raises(TimeoutError):
        with track_opensearch_search(OpenSearchSearchType.HYBRID):
            observe_opensearch_search(OpenSearchSearchType.HYBRID, 0.04, 31)
            raise TimeoutError("read timed out")
    with pytest.raises(RuntimeError):
        with track_opensearch_search(OpenSearchSearchType.KEYWORD):
            raise RuntimeError("search_phase_execution_exception")
    flush_search_samples()

    activity: SearchActivity = read_search_activity()
    results = sorted((s.search_type, s.result) for s in activity.samples)
    assert results == [
        ("hybrid", SearchResult.OK),
        ("hybrid", SearchResult.TIMEOUT),
        ("keyword", SearchResult.ERROR),
    ]
    assert activity.p90_ms == 40
    assert activity.total_count == 3
    assert activity.error_count == 2
    assert sum(point.count for point in activity.rate) == 3
    assert len(activity.rate) == search_samples.SAMPLE_WINDOW_MINUTES


def test_nothing_is_recorded_when_recording_is_off(
    cache: CacheBackend,  # noqa: ARG001
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Off on multi-tenant, without a vector DB, and on the PostgreSQL cache.
    monkeypatch.setattr(search_samples, "RECORDING_ENABLED", False)
    record_search_sample("hybrid", 0.01, 5, SearchResult.OK)
    flush_search_samples()
    assert read_search_activity().total_count == 0


def test_forked_child_gets_a_free_lock_and_an_empty_buffer(
    cache: CacheBackend,  # noqa: ARG001
) -> None:
    record_search_sample("hybrid", 0.01, 5, SearchResult.OK)
    inherited_lock = search_samples._buffer.lock
    # The fork happens while the parent's flusher holds the lock.
    with inherited_lock:
        search_samples._reset_buffer_after_fork()
        assert search_samples._buffer.lock is not inherited_lock
        assert search_samples._buffer.lock.acquire(blocking=False)
        search_samples._buffer.lock.release()
    assert search_samples._buffer.samples == []


def test_activity_window_rate_and_percentiles(cache: CacheBackend) -> None:
    # 30 seconds into a minute, so the current minute is partial.
    now_ms = 1_800_000_030_000
    first_minute_ms = (
        now_ms // MINUTE_MS - search_samples.SAMPLE_WINDOW_MINUTES + 1
    ) * MINUTE_MS
    _write(
        cache,
        [
            # Before the first whole minute: outside the window.
            _sample(first_minute_ms - 1, 5),
            _sample(first_minute_ms, 5),
            # 20 fast searches two minutes ago, and one slow search now.
            *(_sample(now_ms - 2 * MINUTE_MS + i, 10 + i) for i in range(20)),
            _sample(now_ms - 1, 50_000, SearchResult.TIMEOUT),
        ],
    )
    activity = read_search_activity(now_ms)
    assert activity.total_count == 22
    assert activity.error_count == 1
    # Percentiles cover the successful searches only, not the 50 s timeout.
    assert activity.p90_ms == 27
    assert len(activity.rate) == search_samples.SAMPLE_WINDOW_MINUTES
    assert activity.rate[0].minute_ms == first_minute_ms
    assert activity.rate[0].count == 1
    minutes = {point.minute_ms: point for point in activity.rate}
    busy = minutes[(now_ms - 2 * MINUTE_MS) // MINUTE_MS * MINUTE_MS]
    assert (busy.count, busy.error_count, busy.seconds) == (20, 0, 60)
    assert (busy.p10_ms, busy.p90_ms) == (11, 27)
    last = activity.rate[-1]
    # The current minute counts only the seconds so far.
    assert (last.count, last.error_count, last.seconds) == (1, 1, 30)
    assert (last.p10_ms, last.p90_ms) == (None, None)
    # Every fast search fits under the per-minute cap, and the timeout is listed.
    assert len(activity.samples) == 22
    assert activity.samples[-1].result == SearchResult.TIMEOUT
    assert not activity.sampled


def test_listed_searches_are_capped(
    cache: CacheBackend,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(search_samples, "MAX_RETURNED_SAMPLES", 8)
    now_ms = 1_800_000_000_000
    fast = [_sample(now_ms - 5 * MINUTE_MS + i * 100, 20) for i in range(500)]
    slow = [_sample(now_ms - 4 * MINUTE_MS + i, 4000) for i in range(10)]
    failed = [
        _sample(now_ms - 3 * MINUTE_MS + i, 60_000, SearchResult.ERROR)
        for i in range(5)
    ]
    _write(cache, fast + slow + failed)

    activity = read_search_activity(now_ms)
    assert activity.total_count == 515
    # Above the cap, the latest slow or failed searches are kept.
    assert activity.sampled
    notable = [s for s in activity.samples if s.client_ms > 20]
    assert [s.at_ms for s in notable] == [s.at_ms for s in (slow + failed)[-8:]]
    # The 500 fast searches of one minute are cut to a random few, the same
    # few on every read.
    typical = [s.at_ms for s in activity.samples if s.client_ms == 20]
    assert len(typical) == search_samples.MAX_TYPICAL_SAMPLES_PER_MINUTE
    assert typical == sorted(typical)
    again = read_search_activity(now_ms)
    assert [s.at_ms for s in again.samples if s.client_ms == 20] == typical


def test_a_minute_over_the_batch_cap_is_marked_partial(
    cache: CacheBackend,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    now_ms = 1_800_000_030_000
    minute_ms = now_ms // MINUTE_MS * MINUTE_MS
    _write(cache, [_sample(minute_ms + 1, 20)])
    assert not read_search_activity(now_ms).partial
    # Three batches in one minute, as three processes would write them.
    _write(cache, [_sample(minute_ms + 2, 20)])
    _write(cache, [_sample(minute_ms + 3, 20)])
    monkeypatch.setattr(search_samples, "MAX_BATCHES_PER_MINUTE", 2)
    activity = read_search_activity(now_ms)
    # The counts cover only part of the minute, and the response says so.
    assert activity.partial
    assert activity.total_count == 2


def test_searches_endpoint(
    cache: CacheBackend,  # noqa: ARG001
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(service_status_api, "MULTI_TENANT", False)
    record_search_sample("hybrid", 0.02, 15, SearchResult.OK)
    flush_search_samples()
    app = FastAPI()
    register_onyx_exception_handlers(app)
    app.include_router(service_status_api.router)
    user = User(
        id=uuid.uuid4(),
        effective_permissions=[Permission.FULL_ADMIN_PANEL_ACCESS.value],
    )
    app.dependency_overrides[current_user] = lambda: user
    url = "/admin/service-status/opensearch/searches"
    with TestClient(app) as browser:
        response = browser.get(url)
        assert response.status_code == 200
        assert response.json()["total_count"] == 1
        assert response.json()["slow_p90_ms"] == search_samples.SLOW_P90_MS
        user.effective_permissions = []
        assert browser.get(url).status_code == 403
