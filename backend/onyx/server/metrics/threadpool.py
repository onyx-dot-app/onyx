"""Thread pool instrumentation.

Provides an InstrumentedThreadPoolExecutor that wraps submit() to
track task submission, active count, and duration. Also exports a
custom Collector for process-wide thread count.

Metrics:
- onyx_threadpool_tasks_submitted_total: Counter of submitted tasks
- onyx_threadpool_tasks_active: Gauge of currently executing tasks
- onyx_threadpool_task_duration_seconds: Histogram of task execution time
- onyx_process_thread_count: Gauge of total process threads (via psutil)
"""

import os
import time
from collections.abc import Callable
from concurrent.futures import Future
from concurrent.futures import ThreadPoolExecutor
from typing import Any

import psutil
from prometheus_client import Counter
from prometheus_client import Gauge
from prometheus_client import Histogram
from prometheus_client.core import GaugeMetricFamily
from prometheus_client.registry import Collector
from prometheus_client.registry import REGISTRY

from onyx.utils.logger import setup_logger

logger = setup_logger()

_TASKS_SUBMITTED: Counter = Counter(
    "onyx_threadpool_tasks_submitted_total",
    "Total tasks submitted to thread pools",
)

_TASKS_ACTIVE: Gauge = Gauge(
    "onyx_threadpool_tasks_active",
    "Currently executing thread pool tasks",
)

_TASK_DURATION: Histogram = Histogram(
    "onyx_threadpool_task_duration_seconds",
    "Thread pool task execution duration in seconds",
)


_process: psutil.Process | None = None
_process_pid: int | None = None


def _get_process() -> psutil.Process:
    """Return a psutil.Process for the *current* PID.

    Lazily created and invalidated when PID changes (fork).
    Not locked — worst case on a benign race is creating two Process
    objects for the same PID; one gets discarded. The default
    CollectorRegistry serializes collect() calls anyway.
    """
    global _process, _process_pid
    pid = os.getpid()
    if _process is None or _process_pid != pid:
        _process = psutil.Process(pid)
        _process_pid = pid
    return _process


class InstrumentedThreadPoolExecutor(ThreadPoolExecutor):
    """ThreadPoolExecutor subclass that records Prometheus metrics."""

    def submit(
        self,
        fn: Callable[..., Any],
        /,
        *args: Any,
        **kwargs: Any,
    ) -> Future[Any]:
        def _wrapped() -> Any:
            # _wrapped runs inside the thread pool worker, so both the
            # active gauge and the duration timer reflect *execution* time
            # only — queue wait time is excluded.
            _TASKS_ACTIVE.inc()
            start = time.monotonic()
            try:
                return fn(*args, **kwargs)
            finally:
                _TASKS_ACTIVE.dec()
                _TASK_DURATION.observe(time.monotonic() - start)

        # Increment *after* super().submit() so we don't count tasks
        # that fail to submit (e.g. pool already shut down).
        future = super().submit(_wrapped)
        _TASKS_SUBMITTED.inc()
        return future


class ThreadCountCollector(Collector):
    """Reports the process-wide thread count on each Prometheus scrape."""

    def collect(self) -> list[GaugeMetricFamily]:
        family = GaugeMetricFamily(
            "onyx_process_thread_count",
            "Total OS threads in the process",
        )
        try:
            family.add_metric([], _get_process().num_threads())
        except (psutil.Error, OSError):
            logger.warning("Failed to read process thread count", exc_info=True)
            family.add_metric([], 0)
        return [family]

    def describe(self) -> list[GaugeMetricFamily]:
        # Return empty to mark this as an "unchecked" collector.
        # Prometheus checks describe() vs collect() for consistency;
        # returning empty opts out since our metrics are dynamic.
        return []


_thread_collector: ThreadCountCollector | None = None


def setup_threadpool_metrics() -> None:
    """Register the process thread count collector and enable instrumentation.

    Idempotent — safe to call multiple times (e.g. Uvicorn hot-reload).
    Uses try/except on REGISTRY.register() to handle the case where the
    module is reimported (guard resets) but REGISTRY still holds the old
    collector.
    """
    global _thread_collector
    if _thread_collector is not None:
        return

    from onyx.utils.threadpool_concurrency import enable_threadpool_instrumentation

    enable_threadpool_instrumentation()
    collector = ThreadCountCollector()
    try:
        REGISTRY.register(collector)
    except ValueError:
        logger.debug("Thread count collector already registered, skipping")
    _thread_collector = collector
