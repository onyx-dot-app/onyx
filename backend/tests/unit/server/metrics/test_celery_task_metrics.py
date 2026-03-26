"""Tests for generic Celery task lifecycle Prometheus metrics."""

from collections.abc import Iterator
from unittest.mock import MagicMock

import pytest

from onyx.server.metrics.celery_task_metrics import _task_start_times
from onyx.server.metrics.celery_task_metrics import on_celery_task_postrun
from onyx.server.metrics.celery_task_metrics import on_celery_task_prerun
from onyx.server.metrics.celery_task_metrics import TASK_COMPLETED
from onyx.server.metrics.celery_task_metrics import TASK_DURATION
from onyx.server.metrics.celery_task_metrics import TASK_STARTED
from onyx.server.metrics.celery_task_metrics import TASKS_ACTIVE


@pytest.fixture(autouse=True)
def reset_metrics() -> Iterator[None]:
    """Clear metric state between tests."""
    _task_start_times.clear()
    yield
    _task_start_times.clear()


def _make_task(name: str = "test_task", queue: str = "test_queue") -> MagicMock:
    task = MagicMock()
    task.name = name
    task.request = MagicMock()
    task.request.delivery_info = {"routing_key": queue}
    return task


class TestCeleryTaskPrerun:
    def test_increments_started_and_active(self) -> None:
        task = _make_task()
        before_started = TASK_STARTED.labels(
            task_name="test_task", queue="test_queue"
        )._value.get()
        before_active = TASKS_ACTIVE.labels(
            task_name="test_task", queue="test_queue"
        )._value.get()

        on_celery_task_prerun("task-1", task)

        after_started = TASK_STARTED.labels(
            task_name="test_task", queue="test_queue"
        )._value.get()
        after_active = TASKS_ACTIVE.labels(
            task_name="test_task", queue="test_queue"
        )._value.get()

        assert after_started == before_started + 1
        assert after_active == before_active + 1

    def test_records_start_time(self) -> None:
        task = _make_task()
        on_celery_task_prerun("task-1", task)
        assert "task-1" in _task_start_times

    def test_noop_when_task_is_none(self) -> None:
        on_celery_task_prerun("task-1", None)
        assert "task-1" not in _task_start_times

    def test_noop_when_task_id_is_none(self) -> None:
        task = _make_task()
        on_celery_task_prerun(None, task)
        # Should not crash

    def test_handles_missing_delivery_info(self) -> None:
        task = _make_task()
        task.request.delivery_info = None
        on_celery_task_prerun("task-1", task)
        assert "task-1" in _task_start_times


class TestCeleryTaskPostrun:
    def test_increments_completed_success(self) -> None:
        task = _make_task()
        on_celery_task_prerun("task-1", task)

        before = TASK_COMPLETED.labels(
            task_name="test_task", queue="test_queue", outcome="success"
        )._value.get()

        on_celery_task_postrun("task-1", task, "SUCCESS")

        after = TASK_COMPLETED.labels(
            task_name="test_task", queue="test_queue", outcome="success"
        )._value.get()
        assert after == before + 1

    def test_increments_completed_failure(self) -> None:
        task = _make_task()
        on_celery_task_prerun("task-1", task)

        before = TASK_COMPLETED.labels(
            task_name="test_task", queue="test_queue", outcome="failure"
        )._value.get()

        on_celery_task_postrun("task-1", task, "FAILURE")

        after = TASK_COMPLETED.labels(
            task_name="test_task", queue="test_queue", outcome="failure"
        )._value.get()
        assert after == before + 1

    def test_decrements_active(self) -> None:
        task = _make_task()
        on_celery_task_prerun("task-1", task)

        active_before = TASKS_ACTIVE.labels(
            task_name="test_task", queue="test_queue"
        )._value.get()

        on_celery_task_postrun("task-1", task, "SUCCESS")

        active_after = TASKS_ACTIVE.labels(
            task_name="test_task", queue="test_queue"
        )._value.get()
        assert active_after == active_before - 1

    def test_observes_duration(self) -> None:
        task = _make_task()
        on_celery_task_prerun("task-1", task)

        before_count = TASK_DURATION.labels(
            task_name="test_task", queue="test_queue"
        )._sum.get()

        on_celery_task_postrun("task-1", task, "SUCCESS")

        after_count = TASK_DURATION.labels(
            task_name="test_task", queue="test_queue"
        )._sum.get()
        # Duration should have increased (at least slightly)
        assert after_count > before_count

    def test_cleans_up_start_time(self) -> None:
        task = _make_task()
        on_celery_task_prerun("task-1", task)
        assert "task-1" in _task_start_times

        on_celery_task_postrun("task-1", task, "SUCCESS")
        assert "task-1" not in _task_start_times

    def test_noop_when_task_is_none(self) -> None:
        on_celery_task_postrun("task-1", None, "SUCCESS")

    def test_handles_missing_start_time(self) -> None:
        """Postrun without prerun should not crash."""
        task = _make_task()
        on_celery_task_postrun("task-1", task, "SUCCESS")
        # Should not raise
