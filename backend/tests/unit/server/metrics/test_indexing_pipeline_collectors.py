"""Tests for indexing pipeline Prometheus collectors."""

from datetime import datetime
from datetime import timedelta
from datetime import timezone
from unittest.mock import MagicMock
from unittest.mock import patch

import pytest

from onyx.server.metrics.indexing_pipeline import ConnectorHealthCollector
from onyx.server.metrics.indexing_pipeline import IndexAttemptCollector
from onyx.server.metrics.indexing_pipeline import QueueDepthCollector


class TestQueueDepthCollector:
    def test_returns_empty_when_factory_not_set(self) -> None:
        collector = QueueDepthCollector()
        assert collector.collect() == []

    def test_returns_empty_describe(self) -> None:
        collector = QueueDepthCollector()
        assert collector.describe() == []

    def test_collects_queue_depths(self) -> None:
        collector = QueueDepthCollector(cache_ttl=0)
        mock_redis = MagicMock()
        collector.set_redis_factory(lambda: mock_redis)

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
        mock_redis = MagicMock()
        collector.set_redis_factory(lambda: mock_redis)

        with patch(
            "onyx.server.metrics.indexing_pipeline.celery_get_queue_length",
            side_effect=Exception("connection lost"),
        ):
            families = collector.collect()

        # Returns stale cache (empty on first call)
        assert families == []

    def test_caching_returns_stale_within_ttl(self) -> None:
        collector = QueueDepthCollector(cache_ttl=60)
        mock_redis = MagicMock()
        collector.set_redis_factory(lambda: mock_redis)

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

    def test_factory_called_each_scrape(self) -> None:
        """Verify the Redis factory is called on each fresh collect, not cached."""
        collector = QueueDepthCollector(cache_ttl=0)
        factory = MagicMock(return_value=MagicMock())
        collector.set_redis_factory(factory)

        with (
            patch(
                "onyx.server.metrics.indexing_pipeline.celery_get_queue_length",
                return_value=0,
            ),
            patch(
                "onyx.server.metrics.indexing_pipeline.celery_get_unacked_task_ids",
                return_value=set(),
            ),
        ):
            collector.collect()
            collector.collect()

        assert factory.call_count == 2

    def test_error_returns_stale_cache(self) -> None:
        collector = QueueDepthCollector(cache_ttl=0)
        mock_redis = MagicMock()
        collector.set_redis_factory(lambda: mock_redis)

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


class TestIndexAttemptCollector:
    def test_returns_empty_when_not_configured(self) -> None:
        collector = IndexAttemptCollector()
        assert collector.collect() == []

    def test_returns_empty_describe(self) -> None:
        collector = IndexAttemptCollector()
        assert collector.describe() == []

    @patch("onyx.db.engine.tenant_utils.get_all_tenant_ids")
    @patch("onyx.db.engine.sql_engine.get_session_with_current_tenant")
    def test_collects_index_attempts(
        self,
        mock_get_session: MagicMock,
        mock_get_tenants: MagicMock,
    ) -> None:
        collector = IndexAttemptCollector(cache_ttl=0)
        collector.configure()

        mock_get_tenants.return_value = ["public"]

        mock_session = MagicMock()
        mock_get_session.return_value.__enter__ = MagicMock(return_value=mock_session)
        mock_get_session.return_value.__exit__ = MagicMock(return_value=False)

        from onyx.db.enums import IndexingStatus

        mock_row = (
            IndexingStatus.IN_PROGRESS,
            MagicMock(value="web"),
            81,
            "Table Tennis Blade Guide",
            2,
        )
        mock_session.query.return_value.join.return_value.join.return_value.filter.return_value.group_by.return_value.all.return_value = [
            mock_row
        ]

        families = collector.collect()
        assert len(families) == 1
        assert families[0].name == "onyx_index_attempts_active"
        assert len(families[0].samples) == 1
        sample = families[0].samples[0]
        assert sample.labels == {
            "status": "in_progress",
            "source": "web",
            "tenant_id": "public",
            "connector_name": "Table Tennis Blade Guide",
            "cc_pair_id": "81",
        }
        assert sample.value == 2

    @patch("onyx.db.engine.tenant_utils.get_all_tenant_ids")
    def test_handles_db_error_gracefully(
        self,
        mock_get_tenants: MagicMock,
    ) -> None:
        collector = IndexAttemptCollector(cache_ttl=0)
        collector.configure()

        mock_get_tenants.side_effect = Exception("DB down")
        families = collector.collect()
        # No stale cache, so returns empty
        assert families == []

    @patch("onyx.db.engine.tenant_utils.get_all_tenant_ids")
    def test_skips_none_tenant_ids(
        self,
        mock_get_tenants: MagicMock,
    ) -> None:
        collector = IndexAttemptCollector(cache_ttl=0)
        collector.configure()

        mock_get_tenants.return_value = [None]
        families = collector.collect()
        assert len(families) == 1  # Returns the gauge family, just with no samples
        assert len(families[0].samples) == 0


class TestConnectorHealthCollector:
    def test_returns_empty_when_not_configured(self) -> None:
        collector = ConnectorHealthCollector()
        assert collector.collect() == []

    def test_returns_empty_describe(self) -> None:
        collector = ConnectorHealthCollector()
        assert collector.describe() == []

    @patch("onyx.db.engine.tenant_utils.get_all_tenant_ids")
    @patch("onyx.db.engine.sql_engine.get_session_with_current_tenant")
    def test_collects_connector_health(
        self,
        mock_get_session: MagicMock,
        mock_get_tenants: MagicMock,
    ) -> None:
        collector = ConnectorHealthCollector(cache_ttl=0)
        collector.configure()

        mock_get_tenants.return_value = ["public"]

        mock_session = MagicMock()
        mock_get_session.return_value.__enter__ = MagicMock(return_value=mock_session)
        mock_get_session.return_value.__exit__ = MagicMock(return_value=False)

        now = datetime.now(tz=timezone.utc)
        last_success = now - timedelta(hours=2)

        mock_status = MagicMock(value="ACTIVE")
        mock_source = MagicMock(value="google_drive")
        # Row: (id, status, in_error, last_success, name, source)
        mock_row = (
            42,
            mock_status,
            True,  # in_repeated_error_state
            last_success,
            "My GDrive Connector",
            mock_source,
        )
        mock_session.query.return_value.join.return_value.all.return_value = [mock_row]

        # Mock the index attempt queries (error counts + docs counts)
        mock_session.query.return_value.filter.return_value.group_by.return_value.all.return_value = (
            []
        )

        families = collector.collect()

        assert len(families) == 6
        names = {f.name for f in families}
        assert names == {
            "onyx_connector_last_success_age_seconds",
            "onyx_connector_in_error_state",
            "onyx_connectors_by_status",
            "onyx_connectors_in_error_total",
            "onyx_connector_docs_indexed",
            "onyx_connector_error_count",
        }

        staleness = next(
            f for f in families if f.name == "onyx_connector_last_success_age_seconds"
        )
        assert len(staleness.samples) == 1
        assert staleness.samples[0].value == pytest.approx(7200, abs=5)

        error_state = next(
            f for f in families if f.name == "onyx_connector_in_error_state"
        )
        assert error_state.samples[0].value == 1.0

        by_status = next(f for f in families if f.name == "onyx_connectors_by_status")
        assert by_status.samples[0].labels == {
            "tenant_id": "public",
            "status": "ACTIVE",
        }
        assert by_status.samples[0].value == 1

        error_total = next(
            f for f in families if f.name == "onyx_connectors_in_error_total"
        )
        assert error_total.samples[0].value == 1

    @patch("onyx.db.engine.tenant_utils.get_all_tenant_ids")
    @patch("onyx.db.engine.sql_engine.get_session_with_current_tenant")
    def test_skips_staleness_when_no_last_success(
        self,
        mock_get_session: MagicMock,
        mock_get_tenants: MagicMock,
    ) -> None:
        collector = ConnectorHealthCollector(cache_ttl=0)
        collector.configure()

        mock_get_tenants.return_value = ["public"]

        mock_session = MagicMock()
        mock_get_session.return_value.__enter__ = MagicMock(return_value=mock_session)
        mock_get_session.return_value.__exit__ = MagicMock(return_value=False)

        mock_status = MagicMock(value="INITIAL_INDEXING")
        mock_source = MagicMock(value="slack")
        mock_row = (
            10,
            mock_status,
            False,
            None,  # no last_successful_index_time
            0,
            mock_source,
        )
        mock_session.query.return_value.join.return_value.all.return_value = [mock_row]

        families = collector.collect()

        staleness = next(
            f for f in families if f.name == "onyx_connector_last_success_age_seconds"
        )
        assert len(staleness.samples) == 0

    @patch("onyx.db.engine.tenant_utils.get_all_tenant_ids")
    def test_handles_db_error_gracefully(
        self,
        mock_get_tenants: MagicMock,
    ) -> None:
        collector = ConnectorHealthCollector(cache_ttl=0)
        collector.configure()

        mock_get_tenants.side_effect = Exception("DB down")
        families = collector.collect()
        assert families == []
