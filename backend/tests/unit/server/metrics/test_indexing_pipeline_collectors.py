"""Tests for indexing pipeline Prometheus collectors."""

import threading
import time
from collections.abc import Callable, Iterator
from unittest.mock import MagicMock, patch

import pytest
from prometheus_client.core import GaugeMetricFamily

import onyx.server.metrics.indexing_pipeline as indexing_pipeline
from onyx.server.metrics.indexing_pipeline import QueueDepthCollector, _CachedCollector


@pytest.fixture(autouse=True)
def _mock_broker_client() -> Iterator[None]:
    """Patch celery_get_broker_client for all collector tests."""
    with patch(
        "onyx.server.metrics.indexing_pipeline.celery_get_broker_client",
        return_value=MagicMock(),
    ):
        yield


class _GatedCollector(_CachedCollector):
    """Collection blocks until ``release`` is set, so a stall can be staged."""

    def __init__(self, cache_ttl: float, collect_timeout: float) -> None:
        super().__init__(cache_ttl=cache_ttl, collect_timeout=collect_timeout)
        self.release = threading.Event()
        self.calls = 0

    def _collect_fresh(self) -> list[GaugeMetricFamily]:
        self.calls += 1
        # Bounded so a never-released gate cannot hang the executor thread at exit.
        self.release.wait(timeout=5)
        gauge = GaugeMetricFamily("gated", "gated")
        gauge.add_metric([], self.calls)
        return [gauge]


def _wait_until(predicate: Callable[[], bool], timeout: float = 2.0) -> None:
    deadline = time.monotonic() + timeout
    while not predicate():
        assert time.monotonic() < deadline, "condition not met in time"
        time.sleep(0.005)


def _inflight_done(collector: _CachedCollector) -> bool:
    return collector._inflight is not None and collector._inflight.done()


class TestCachedCollector:
    def test_scrape_during_stalled_collection_returns_stale_at_once(self) -> None:
        collector = _GatedCollector(cache_ttl=60, collect_timeout=2.0)
        starter_results: list[list[GaugeMetricFamily]] = []
        starter = threading.Thread(
            target=lambda: starter_results.append(collector.collect())
        )
        starter.start()
        _wait_until(lambda: collector._inflight is not None)

        began = time.monotonic()
        during_stall = collector.collect()
        elapsed = time.monotonic() - began

        # No cache yet and a collection in flight: empty, without waiting on it.
        assert during_stall == []
        assert elapsed < 0.5
        starter.join(timeout=4)
        assert starter_results == [[]]
        assert collector.calls == 1

        # The late result is banked by the next scrape rather than re-collected.
        collector.release.set()
        _wait_until(lambda: _inflight_done(collector))
        banked = collector.collect()
        assert banked[0].samples[0].value == 1
        assert collector.calls == 1
        collector._executor.shutdown(wait=False)

    def test_stall_warning_is_throttled(self) -> None:
        collector = _GatedCollector(cache_ttl=60, collect_timeout=0.1)
        assert collector.collect() == []  # starter times out and warns

        def stall_lines_from(scrapes: int) -> int:
            with patch.object(indexing_pipeline.logger, "warning") as warning:
                for _ in range(scrapes):
                    assert collector.collect() == []
            return sum(
                1 for call in warning.call_args_list if "still running" in call.args[0]
            )

        # The starter's own warning opened the window, so nothing more is logged.
        assert stall_lines_from(3) == 0
        # Once the window has passed, exactly one line per window.
        collector._last_stall_log -= indexing_pipeline._STALL_WARNING_INTERVAL
        assert stall_lines_from(3) == 1
        collector.release.set()
        collector._executor.shutdown(wait=False)


class TestQueueDepthCollector:
    def test_returns_empty_when_factory_not_set(self) -> None:
        collector = QueueDepthCollector()
        assert collector.collect() == []

    def test_returns_empty_describe(self) -> None:
        collector = QueueDepthCollector()
        assert collector.describe() == []

    def test_collects_queue_depths(self) -> None:
        collector = QueueDepthCollector(cache_ttl=0)
        collector.set_celery_app(MagicMock())

        with (
            patch(
                "onyx.server.metrics.indexing_pipeline.celery_get_queue_length",
                return_value=5,
            ),
            patch(
                "onyx.server.metrics.indexing_pipeline.celery_get_unacked_task_ids",
                return_value={"task-1", "task-2"},
            ),
        ):
            families = collector.collect()

        assert len(families) == 3
        depth_family = families[0]
        unacked_family = families[1]
        age_family = families[2]

        assert depth_family.name == "onyx_queue_depth"
        assert len(depth_family.samples) > 0
        for sample in depth_family.samples:
            assert sample.value == 5

        assert unacked_family.name == "onyx_queue_unacked"
        unacked_labels = {s.labels["queue"] for s in unacked_family.samples}
        assert "docfetching" in unacked_labels
        assert "docprocessing" in unacked_labels

        assert age_family.name == "onyx_queue_oldest_task_age_seconds"
        for sample in unacked_family.samples:
            assert sample.value == 2

    def test_handles_redis_error_gracefully(self) -> None:
        collector = QueueDepthCollector(cache_ttl=0)
        MagicMock()
        collector.set_celery_app(MagicMock())

        with patch(
            "onyx.server.metrics.indexing_pipeline.celery_get_queue_length",
            side_effect=Exception("connection lost"),
        ):
            families = collector.collect()

        # Returns stale cache (empty on first call)
        assert families == []

    def test_caching_returns_stale_within_ttl(self) -> None:
        collector = QueueDepthCollector(cache_ttl=60)
        MagicMock()
        collector.set_celery_app(MagicMock())

        with (
            patch(
                "onyx.server.metrics.indexing_pipeline.celery_get_queue_length",
                return_value=5,
            ),
            patch(
                "onyx.server.metrics.indexing_pipeline.celery_get_unacked_task_ids",
                return_value=set(),
            ),
        ):
            first = collector.collect()

        # Second call within TTL should return cached result without calling Redis
        with patch(
            "onyx.server.metrics.indexing_pipeline.celery_get_queue_length",
            side_effect=Exception("should not be called"),
        ):
            second = collector.collect()

        assert first is second  # Same object, from cache

    def test_error_returns_stale_cache(self) -> None:
        collector = QueueDepthCollector(cache_ttl=0)
        MagicMock()
        collector.set_celery_app(MagicMock())

        # First call succeeds
        with (
            patch(
                "onyx.server.metrics.indexing_pipeline.celery_get_queue_length",
                return_value=10,
            ),
            patch(
                "onyx.server.metrics.indexing_pipeline.celery_get_unacked_task_ids",
                return_value=set(),
            ),
        ):
            good_result = collector.collect()

        assert len(good_result) == 3
        assert good_result[0].samples[0].value == 10

        # Second call fails — should return stale cache, not empty
        with patch(
            "onyx.server.metrics.indexing_pipeline.celery_get_queue_length",
            side_effect=Exception("Redis down"),
        ):
            stale_result = collector.collect()

        assert stale_result is good_result
