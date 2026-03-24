"""Generic Celery task lifecycle Prometheus metrics.

Provides signal handlers that track task started/completed/failed counts,
active task gauge, and task duration histograms. These fire for ALL tasks
on the worker — no per-connector enrichment (see indexing_task_metrics.py
for that).

Usage in a worker app module:
    from onyx.server.metrics.celery_task_metrics import (
        on_celery_task_prerun,
        on_celery_task_postrun,
    )
    # Call from the worker's existing signal handlers
"""

import time

from celery import Task
from prometheus_client import Counter
from prometheus_client import Gauge
from prometheus_client import Histogram

from onyx.utils.logger import setup_logger

logger = setup_logger()

TASK_STARTED = Counter(
    "onyx_celery_task_started_total",
    "Total Celery tasks started",
    ["task_name", "queue"],
)

TASK_COMPLETED = Counter(
    "onyx_celery_task_completed_total",
    "Total Celery tasks completed",
    ["task_name", "queue", "outcome"],
)

TASK_DURATION = Histogram(
    "onyx_celery_task_duration_seconds",
    "Celery task execution duration in seconds",
    ["task_name", "queue"],
    buckets=[1, 5, 15, 30, 60, 120, 300, 600, 1800, 3600],
)

TASKS_ACTIVE = Gauge(
    "onyx_celery_tasks_active",
    "Currently executing Celery tasks",
    ["task_name", "queue"],
)

# task_id → monotonic start time
_task_start_times: dict[str, float] = {}


def _get_task_labels(task: Task) -> dict[str, str]:
    """Extract task_name and queue labels from a Celery Task instance."""
    task_name = task.name or "unknown"
    queue = "unknown"
    try:
        delivery_info = task.request.delivery_info
        if delivery_info:
            queue = delivery_info.get("routing_key") or "unknown"
    except AttributeError:
        pass
    return {"task_name": task_name, "queue": queue}


def on_celery_task_prerun(
    task_id: str | None,
    task: Task | None,
) -> None:
    """Record task start. Call from the worker's task_prerun signal handler."""
    if task is None or task_id is None:
        return

    try:
        labels = _get_task_labels(task)
        TASK_STARTED.labels(**labels).inc()
        TASKS_ACTIVE.labels(**labels).inc()
        _task_start_times[task_id] = time.monotonic()
    except Exception:
        logger.debug("Failed to record celery task prerun metrics", exc_info=True)


def on_celery_task_postrun(
    task_id: str | None,
    task: Task | None,
    state: str | None,
) -> None:
    """Record task completion. Call from the worker's task_postrun signal handler."""
    if task is None or task_id is None:
        return

    try:
        labels = _get_task_labels(task)
        outcome = "success" if state == "SUCCESS" else "failure"
        TASK_COMPLETED.labels(**labels, outcome=outcome).inc()
        TASKS_ACTIVE.labels(**labels).dec()

        start = _task_start_times.pop(task_id, None)
        if start is not None:
            TASK_DURATION.labels(**labels).observe(time.monotonic() - start)
    except Exception:
        logger.debug("Failed to record celery task postrun metrics", exc_info=True)
