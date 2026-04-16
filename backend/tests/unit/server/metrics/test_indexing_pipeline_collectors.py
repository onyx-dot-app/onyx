"""Tests for indexing pipeline Prometheus collectors."""

from collections.abc import Iterator
from unittest.mock import MagicMock
from unittest.mock import patch

import pytest

from onyx.server.metrics.indexing_pipeline import QueueDepthCollector


@pytest.fixture(autouse=True)
def _mock_broker_client() -> Iterator[None]:
    """Patch celery_get_broker_client for all collector tests."""
    with patch(
        "onyx.server.metrics.indexing_pipeline.celery_get_broker_client",
        return_value=MagicMock(),
    ):
        yield


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
