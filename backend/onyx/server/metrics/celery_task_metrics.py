"""Generic Celery task lifecycle Prometheus metrics.

Provides signal handlers that track task started/completed/failed counts,
active task gauge, task duration histograms, and retry/reject/revoke counts.
These fire for ALL tasks on the worker — no per-connector enrichment
(see indexing_task_metrics.py for that).

Usage in a worker app module:
    from onyx.server.metrics.celery_task_metrics import (
        on_celery_task_prerun,
        on_celery_task_postrun,
        on_celery_task_retry,
        on_celery_task_revoked,
        on_celery_task_rejected,
    )
    # Call from the worker's existing signal handlers
"""

import threading
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

TASK_RETRIED = Counter(
    "onyx_celery_task_retried_total",
    "Total Celery tasks retried",
    ["task_name", "queue"],
)

TASK_REVOKED = Counter(
    "onyx_celery_task_revoked_total",
    "Total Celery tasks revoked (cancelled)",
    ["task_name"],
)

TASK_REJECTED = Counter(
    "onyx_celery_task_rejected_total",
    "Total Celery tasks rejected by worker",
    ["task_name"],
)

# task_id → (monotonic start time, metric labels)
_task_start_times: dict[str, tuple[float, dict[str, str]]] = {}

# Lock protecting _task_start_times — prerun, postrun, and eviction may
# run concurrently on thread-pool workers.
_task_start_times_lock = threading.Lock()

# Entries older than this are evicted on each prerun to prevent unbounded
# growth when tasks are killed (SIGTERM, OOM) and postrun never fires.
_MAX_START_TIME_AGE_SECONDS = 3600  # 1 hour


def _evict_stale_start_times() -> None:
    """Remove _task_start_times entries older than _MAX_START_TIME_AGE_SECONDS.

    Must be called while holding _task_start_times_lock.
    """
    now = time.monotonic()
    stale_ids = [
        tid
        for tid, (start, _labels) in _task_start_times.items()
        if now - start > _MAX_START_TIME_AGE_SECONDS
    ]
    for tid in stale_ids:
        entry = _task_start_times.pop(tid, None)
        if entry is not None:
            _labels = entry[1]
            # Decrement active gauge for evicted tasks — these tasks were
            # started but never completed (killed, OOM, etc.).
            active_gauge = TASKS_ACTIVE.labels(**_labels)
            if active_gauge._value.get() > 0:
                active_gauge.dec()


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
        with _task_start_times_lock:
            _evict_stale_start_times()
            _task_start_times[task_id] = (time.monotonic(), labels)
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

        # Guard against going below 0 if postrun fires without a matching
        # prerun (e.g. after a worker restart or stale entry eviction).
        active_gauge = TASKS_ACTIVE.labels(**labels)
        if active_gauge._value.get() > 0:
            active_gauge.dec()

        with _task_start_times_lock:
            entry = _task_start_times.pop(task_id, None)
        if entry is not None:
            start_time, _stored_labels = entry
            TASK_DURATION.labels(**labels).observe(time.monotonic() - start_time)
    except Exception:
        logger.debug("Failed to record celery task postrun metrics", exc_info=True)


def on_celery_task_retry(
    _task_id: str | None,
    task: Task | None,
) -> None:
    """Record task retry. Call from the worker's task_retry signal handler."""
    if task is None:
        return
    try:
        labels = _get_task_labels(task)
        TASK_RETRIED.labels(**labels).inc()
    except Exception:
        logger.debug("Failed to record celery task retry metrics", exc_info=True)


def on_celery_task_revoked(
    _task_id: str | None,
    task_name: str | None = None,
) -> None:
    """Record task revocation. The revoked signal doesn't provide a Task
    instance, only the task name via sender."""
    if task_name is None:
        return
    try:
        TASK_REVOKED.labels(task_name=task_name).inc()
    except Exception:
        logger.debug("Failed to record celery task revoked metrics", exc_info=True)


def on_celery_task_rejected(
    _task_id: str | None,
    task_name: str | None = None,
) -> None:
    """Record task rejection."""
    if task_name is None:
        return
    try:
        TASK_REJECTED.labels(task_name=task_name).inc()
    except Exception:
        logger.debug("Failed to record celery task rejected metrics", exc_info=True)
