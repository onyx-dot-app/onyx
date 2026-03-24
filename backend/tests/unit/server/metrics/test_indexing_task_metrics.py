"""Tests for per-connector indexing task Prometheus metrics."""

from unittest.mock import MagicMock
from unittest.mock import patch

import pytest

from onyx.server.metrics.indexing_task_metrics import _connector_cache
from onyx.server.metrics.indexing_task_metrics import _indexing_start_times
from onyx.server.metrics.indexing_task_metrics import ConnectorInfo
from onyx.server.metrics.indexing_task_metrics import INDEXING_TASK_COMPLETED
from onyx.server.metrics.indexing_task_metrics import INDEXING_TASK_DURATION
from onyx.server.metrics.indexing_task_metrics import INDEXING_TASK_STARTED
from onyx.server.metrics.indexing_task_metrics import on_indexing_task_postrun
from onyx.server.metrics.indexing_task_metrics import on_indexing_task_prerun


@pytest.fixture(autouse=True)
def reset_state() -> None:  # type: ignore
    """Clear caches and state between tests."""
    _connector_cache.clear()
    _indexing_start_times.clear()
    yield  # type: ignore
    _connector_cache.clear()
    _indexing_start_times.clear()


def _make_task(name: str) -> MagicMock:
    task = MagicMock()
    task.name = name
    return task


def _mock_db_lookup(
    source: str = "google_drive", name: str = "My Google Drive"
) -> tuple:
    """Return (session_patch, cc_pair_patch) context managers for DB mocking."""
    mock_cc_pair = MagicMock()
    mock_cc_pair.name = name
    mock_cc_pair.connector.source.value = source

    session_patch = patch("onyx.db.engine.sql_engine.get_session_with_current_tenant")
    cc_pair_patch = patch(
        "onyx.db.connector_credential_pair.get_connector_credential_pair_from_id",
        return_value=mock_cc_pair,
    )
    return session_patch, cc_pair_patch


class TestIndexingTaskPrerun:
    def test_skips_non_indexing_task(self) -> None:
        task = _make_task("some_other_task")
        kwargs = {"cc_pair_id": 1, "tenant_id": "public"}
        on_indexing_task_prerun("task-1", task, kwargs)
        assert "task-1" not in _indexing_start_times

    def test_emits_started_for_docfetching(self) -> None:
        # Pre-populate cache to avoid DB lookup
        _connector_cache[42] = ConnectorInfo(
            source="google_drive", name="My Google Drive"
        )

        task = _make_task("connector_doc_fetching_task")
        kwargs = {"cc_pair_id": 42, "tenant_id": "tenant-1"}

        before = INDEXING_TASK_STARTED.labels(
            task_name="connector_doc_fetching_task",
            source="google_drive",
            tenant_id="tenant-1",
            cc_pair_id="42",
            connector_name="My Google Drive",
        )._value.get()

        on_indexing_task_prerun("task-1", task, kwargs)

        after = INDEXING_TASK_STARTED.labels(
            task_name="connector_doc_fetching_task",
            source="google_drive",
            tenant_id="tenant-1",
            cc_pair_id="42",
            connector_name="My Google Drive",
        )._value.get()

        assert after == before + 1
        assert "task-1" in _indexing_start_times

    def test_emits_started_for_docprocessing(self) -> None:
        _connector_cache[10] = ConnectorInfo(source="slack", name="Slack Connector")

        task = _make_task("docprocessing_task")
        kwargs = {"cc_pair_id": 10, "tenant_id": "public"}

        on_indexing_task_prerun("task-2", task, kwargs)
        assert "task-2" in _indexing_start_times

    def test_cache_hit_avoids_db_call(self) -> None:
        _connector_cache[42] = ConnectorInfo(
            source="confluence", name="Engineering Confluence"
        )

        task = _make_task("connector_doc_fetching_task")
        kwargs = {"cc_pair_id": 42, "tenant_id": "public"}

        # No DB patches needed — cache should be used
        on_indexing_task_prerun("task-1", task, kwargs)
        assert "task-1" in _indexing_start_times

    def test_db_lookup_on_cache_miss(self) -> None:
        """On first encounter of a cc_pair_id, does a DB lookup and caches."""
        mock_cc_pair = MagicMock()
        mock_cc_pair.name = "Notion Workspace"
        mock_cc_pair.connector.source.value = "notion"

        mock_session = MagicMock()
        mock_session.__enter__ = MagicMock(return_value=MagicMock())
        mock_session.__exit__ = MagicMock(return_value=False)

        with (
            patch(
                "onyx.server.metrics.indexing_task_metrics._resolve_connector"
            ) as mock_resolve,
        ):
            mock_resolve.return_value = ConnectorInfo(
                source="notion", name="Notion Workspace"
            )

            task = _make_task("connector_doc_fetching_task")
            kwargs = {"cc_pair_id": 77, "tenant_id": "public"}

            on_indexing_task_prerun("task-1", task, kwargs)
            mock_resolve.assert_called_once_with(77)

    def test_missing_cc_pair_returns_unknown(self) -> None:
        """When _resolve_connector can't find the cc_pair, uses 'unknown'."""
        with patch(
            "onyx.server.metrics.indexing_task_metrics._resolve_connector"
        ) as mock_resolve:
            mock_resolve.return_value = ConnectorInfo(source="unknown", name="unknown")

            task = _make_task("connector_doc_fetching_task")
            kwargs = {"cc_pair_id": 999, "tenant_id": "public"}

            on_indexing_task_prerun("task-1", task, kwargs)
            assert "task-1" in _indexing_start_times

    def test_skips_when_cc_pair_id_missing(self) -> None:
        task = _make_task("connector_doc_fetching_task")
        kwargs = {"tenant_id": "public"}
        on_indexing_task_prerun("task-1", task, kwargs)
        assert "task-1" not in _indexing_start_times

    def test_db_error_does_not_crash(self) -> None:
        with patch(
            "onyx.server.metrics.indexing_task_metrics._resolve_connector",
            side_effect=Exception("DB down"),
        ):
            task = _make_task("connector_doc_fetching_task")
            kwargs = {"cc_pair_id": 1, "tenant_id": "public"}
            # Should not raise
            on_indexing_task_prerun("task-1", task, kwargs)


class TestIndexingTaskPostrun:
    def test_skips_non_indexing_task(self) -> None:
        task = _make_task("some_other_task")
        kwargs = {"cc_pair_id": 1, "tenant_id": "public"}
        on_indexing_task_postrun("task-1", task, kwargs, "SUCCESS")
        # Should not raise

    def test_emits_completed_and_duration(self) -> None:
        _connector_cache[42] = ConnectorInfo(
            source="google_drive", name="Marketing Drive"
        )

        task = _make_task("docprocessing_task")
        kwargs = {"cc_pair_id": 42, "tenant_id": "public"}

        # Simulate prerun
        on_indexing_task_prerun("task-1", task, kwargs)

        before_completed = INDEXING_TASK_COMPLETED.labels(
            task_name="docprocessing_task",
            source="google_drive",
            tenant_id="public",
            cc_pair_id="42",
            connector_name="Marketing Drive",
            outcome="success",
        )._value.get()

        before_duration = INDEXING_TASK_DURATION.labels(
            task_name="docprocessing_task",
            source="google_drive",
            tenant_id="public",
        )._sum.get()

        on_indexing_task_postrun("task-1", task, kwargs, "SUCCESS")

        after_completed = INDEXING_TASK_COMPLETED.labels(
            task_name="docprocessing_task",
            source="google_drive",
            tenant_id="public",
            cc_pair_id="42",
            connector_name="Marketing Drive",
            outcome="success",
        )._value.get()

        after_duration = INDEXING_TASK_DURATION.labels(
            task_name="docprocessing_task",
            source="google_drive",
            tenant_id="public",
        )._sum.get()

        assert after_completed == before_completed + 1
        assert after_duration > before_duration

    def test_failure_outcome(self) -> None:
        _connector_cache[42] = ConnectorInfo(source="slack", name="Slack")

        task = _make_task("connector_doc_fetching_task")
        kwargs = {"cc_pair_id": 42, "tenant_id": "public"}

        on_indexing_task_prerun("task-1", task, kwargs)

        before = INDEXING_TASK_COMPLETED.labels(
            task_name="connector_doc_fetching_task",
            source="slack",
            tenant_id="public",
            cc_pair_id="42",
            connector_name="Slack",
            outcome="failure",
        )._value.get()

        on_indexing_task_postrun("task-1", task, kwargs, "FAILURE")

        after = INDEXING_TASK_COMPLETED.labels(
            task_name="connector_doc_fetching_task",
            source="slack",
            tenant_id="public",
            cc_pair_id="42",
            connector_name="Slack",
            outcome="failure",
        )._value.get()

        assert after == before + 1

    def test_handles_postrun_without_prerun(self) -> None:
        """Postrun for an indexing task without a matching prerun should not crash."""
        _connector_cache[42] = ConnectorInfo(source="slack", name="Slack")

        task = _make_task("docprocessing_task")
        kwargs = {"cc_pair_id": 42, "tenant_id": "public"}

        # No prerun — should still emit completed counter, just skip duration
        on_indexing_task_postrun("task-1", task, kwargs, "SUCCESS")
