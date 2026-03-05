"""Unit tests for thread pool instrumentation."""

from unittest.mock import patch

import pytest

from onyx.server.metrics.threadpool import InstrumentedThreadPoolExecutor
from onyx.server.metrics.threadpool import ThreadCountCollector


def test_instrumented_executor_tracks_submissions() -> None:
    """Verify counter increments and gauge tracks active tasks."""
    with (
        patch("onyx.server.metrics.threadpool._TASKS_SUBMITTED") as mock_submitted,
        patch("onyx.server.metrics.threadpool._TASKS_ACTIVE") as mock_active,
        patch("onyx.server.metrics.threadpool._TASK_DURATION") as mock_duration,
    ):

        with InstrumentedThreadPoolExecutor(max_workers=2) as executor:
            future = executor.submit(lambda: 42)
            result = future.result(timeout=5)

        assert result == 42
        mock_submitted.inc.assert_called_once()
        mock_active.inc.assert_called_once()
        mock_active.dec.assert_called_once()
        mock_duration.observe.assert_called_once()

        # Duration should be non-negative
        observed_duration = mock_duration.observe.call_args[0][0]
        assert observed_duration >= 0


def test_instrumented_executor_handles_exceptions() -> None:
    """Verify metrics still fire when the task raises."""
    with (
        patch("onyx.server.metrics.threadpool._TASKS_SUBMITTED") as mock_submitted,
        patch("onyx.server.metrics.threadpool._TASKS_ACTIVE") as mock_active,
        patch("onyx.server.metrics.threadpool._TASK_DURATION") as mock_duration,
    ):

        with InstrumentedThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(lambda: 1 / 0)
            with pytest.raises(ZeroDivisionError):
                future.result(timeout=5)

        # Metrics should still be recorded even on failure
        mock_submitted.inc.assert_called_once()
        mock_active.inc.assert_called_once()
        mock_active.dec.assert_called_once()
        mock_duration.observe.assert_called_once()


def test_thread_count_collector_reports_threads() -> None:
    """Verify the collector returns the process thread count."""
    with patch("onyx.server.metrics.threadpool._process") as mock_process:
        mock_process.num_threads.return_value = 15

        collector = ThreadCountCollector()
        families = collector.collect()

        assert len(families) == 1
        samples = families[0].samples
        assert len(samples) == 1
        assert samples[0].value == 15


def test_thread_count_collector_describe_returns_empty() -> None:
    collector = ThreadCountCollector()
    assert collector.describe() == []
