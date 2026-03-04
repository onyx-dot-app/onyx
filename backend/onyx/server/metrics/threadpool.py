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

_TASKS_SUBMITTED = Counter(
    "onyx_threadpool_tasks_submitted_total",
    "Total tasks submitted to thread pools",
)

_TASKS_ACTIVE = Gauge(
    "onyx_threadpool_tasks_active",
    "Currently executing thread pool tasks",
)

_TASK_DURATION = Histogram(
    "onyx_threadpool_task_duration_seconds",
    "Thread pool task execution duration in seconds",
)

_process = psutil.Process()


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
            _TASKS_ACTIVE.inc()
            start = time.monotonic()
            try:
                return fn(*args, **kwargs)
            finally:
                _TASKS_ACTIVE.dec()
                _TASK_DURATION.observe(time.monotonic() - start)

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
        family.add_metric([], _process.num_threads())
        return [family]

    def describe(self) -> list[GaugeMetricFamily]:
        return []


_thread_collector: ThreadCountCollector | None = None


def setup_threadpool_metrics() -> None:
    """Register the process thread count collector and enable instrumentation.

    Idempotent — safe to call multiple times (e.g. Uvicorn hot-reload).
    """
    global _thread_collector
    if _thread_collector is not None:
        return

    from onyx.utils.threadpool_concurrency import enable_threadpool_instrumentation

    enable_threadpool_instrumentation()
    _thread_collector = ThreadCountCollector()
    REGISTRY.register(_thread_collector)
