"""Automated deep profiling via tracemalloc, GC stats, and object counting.

When ENABLE_DEEP_PROFILING is true, this module:
1. Starts tracemalloc with 10-frame depth
2. Periodically snapshots allocations and computes diffs
3. Exports top allocation sites, GC stats, and object type counts to Prometheus

All data flows to /metrics automatically — no manual endpoints needed.

Metrics:
- onyx_tracemalloc_top_bytes: Bytes by top source locations
- onyx_tracemalloc_top_count: Allocation count by top source locations
- onyx_tracemalloc_delta_bytes: Growth since previous snapshot
- onyx_tracemalloc_total_bytes: Total traced memory
- onyx_gc_collections_total: GC collections per generation
- onyx_gc_collected_total: Objects collected per generation
- onyx_gc_uncollectable_total: Uncollectable objects per generation
- onyx_object_type_count: Live object count by type
"""

import asyncio
import gc
import os
import tracemalloc
from collections import Counter
from typing import Any

from prometheus_client.core import CounterMetricFamily
from prometheus_client.core import GaugeMetricFamily
from prometheus_client.registry import Collector
from prometheus_client.registry import REGISTRY

from onyx.configs.app_configs import DEEP_PROFILING_SNAPSHOT_INTERVAL_SECONDS
from onyx.configs.app_configs import DEEP_PROFILING_TOP_N_ALLOCATIONS
from onyx.configs.app_configs import DEEP_PROFILING_TOP_N_TYPES
from onyx.utils.logger import setup_logger

logger = setup_logger()

_snapshot_task: asyncio.Task[None] | None = None

# Mutable state updated by the periodic snapshot task, read by the collector
_current_top_stats: list[tracemalloc.Statistic] = []
_current_delta_stats: list[tracemalloc.StatisticDiff] = []
_current_total_bytes: int = 0
_current_object_type_counts: list[tuple[str, int]] = []
_previous_snapshot: tracemalloc.Snapshot | None = None


_cwd: str = os.getcwd()


def _strip_path(filename: str) -> str:
    """Convert absolute paths to relative for low-cardinality labels."""
    # Strip site-packages prefix
    for marker in ("site-packages/", "dist-packages/"):
        idx = filename.find(marker)
        if idx != -1:
            return filename[idx + len(marker) :]
    # Strip cwd
    if filename.startswith(_cwd):
        return filename[len(_cwd) :].lstrip("/")
    return filename


async def _snapshot_loop(interval: float) -> None:
    """Periodically take tracemalloc snapshots and compute diffs."""
    global _previous_snapshot, _current_top_stats, _current_delta_stats
    global _current_total_bytes, _current_object_type_counts

    while True:
        await asyncio.sleep(interval)
        try:
            if not tracemalloc.is_tracing():
                continue

            snapshot = tracemalloc.take_snapshot()
            snapshot = snapshot.filter_traces(
                (
                    tracemalloc.Filter(False, "<frozen importlib._bootstrap>"),
                    tracemalloc.Filter(False, "<frozen importlib._bootstrap_external>"),
                    tracemalloc.Filter(False, tracemalloc.__file__),
                )
            )

            all_stats = snapshot.statistics("lineno")
            _current_top_stats = all_stats[:DEEP_PROFILING_TOP_N_ALLOCATIONS]

            if _previous_snapshot is not None:
                _current_delta_stats = snapshot.compare_to(
                    _previous_snapshot, "lineno"
                )[:DEEP_PROFILING_TOP_N_ALLOCATIONS]
            else:
                _current_delta_stats = []

            _current_total_bytes = sum(stat.size for stat in all_stats)
            _previous_snapshot = snapshot

            # Object type counting — done here (amortized by snapshot interval)
            # instead of on every /metrics scrape, since gc.get_objects() is O(n)
            # over all live objects and holds the GIL.
            counts: Counter[str] = Counter()
            for obj in gc.get_objects():
                counts[type(obj).__name__] += 1
            _current_object_type_counts = counts.most_common(DEEP_PROFILING_TOP_N_TYPES)
        except Exception:
            logger.warning(
                "Error in deep profiling snapshot loop, skipping iteration",
                exc_info=True,
            )


class DeepProfilingCollector(Collector):
    """Exports tracemalloc, GC, and object type metrics on each scrape."""

    def collect(self) -> list[Any]:
        families: list[Any] = []

        # --- tracemalloc allocation sites ---
        top_bytes = GaugeMetricFamily(
            "onyx_tracemalloc_top_bytes",
            "Bytes allocated by top source locations",
            labels=["source"],
        )
        top_count = GaugeMetricFamily(
            "onyx_tracemalloc_top_count",
            "Allocation count by top source locations",
            labels=["source"],
        )
        for stat in _current_top_stats:
            source = (
                f"{_strip_path(stat.traceback[0].filename)}:{stat.traceback[0].lineno}"
            )
            top_bytes.add_metric([source], stat.size)
            top_count.add_metric([source], stat.count)
        families.extend([top_bytes, top_count])

        # --- tracemalloc deltas ---
        delta_bytes = GaugeMetricFamily(
            "onyx_tracemalloc_delta_bytes",
            "Allocation growth since previous snapshot",
            labels=["source"],
        )
        for diff_stat in _current_delta_stats:
            if diff_stat.size_diff > 0:
                source = f"{_strip_path(diff_stat.traceback[0].filename)}:{diff_stat.traceback[0].lineno}"
                delta_bytes.add_metric([source], diff_stat.size_diff)
        families.append(delta_bytes)

        # --- tracemalloc total ---
        total = GaugeMetricFamily(
            "onyx_tracemalloc_total_bytes",
            "Total traced memory in bytes",
        )
        total.add_metric([], _current_total_bytes)
        families.append(total)

        # --- GC stats ---
        gc_collections = CounterMetricFamily(
            "onyx_gc_collections_total",
            "GC collections per generation",
            labels=["generation"],
        )
        gc_collected = CounterMetricFamily(
            "onyx_gc_collected_total",
            "Objects collected per generation",
            labels=["generation"],
        )
        gc_uncollectable = CounterMetricFamily(
            "onyx_gc_uncollectable_total",
            "Uncollectable objects per generation",
            labels=["generation"],
        )
        for i, stats in enumerate(gc.get_stats()):
            gen = str(i)
            gc_collections.add_metric([gen], stats["collections"])
            gc_collected.add_metric([gen], stats["collected"])
            gc_uncollectable.add_metric([gen], stats["uncollectable"])
        families.extend([gc_collections, gc_collected, gc_uncollectable])

        # --- Object type counts (cached from snapshot loop) ---
        type_count = GaugeMetricFamily(
            "onyx_object_type_count",
            "Live object count by type",
            labels=["type"],
        )
        for type_name, count in _current_object_type_counts:
            type_count.add_metric([type_name], count)
        families.append(type_count)

        return families

    def describe(self) -> list[Any]:
        return []


_collector: DeepProfilingCollector | None = None


def start_deep_profiling() -> None:
    """Start tracemalloc and the periodic snapshot task.

    Idempotent — safe to call multiple times (e.g. Uvicorn hot-reload).
    """
    global _snapshot_task, _collector

    if _snapshot_task is not None:
        return

    if not tracemalloc.is_tracing():
        tracemalloc.start(10)
        logger.info("tracemalloc started with 10-frame depth")
    else:
        logger.info("tracemalloc already active, reusing existing session")

    _snapshot_task = asyncio.create_task(
        _snapshot_loop(DEEP_PROFILING_SNAPSHOT_INTERVAL_SECONDS)
    )

    if _collector is None:
        collector = DeepProfilingCollector()
        REGISTRY.register(collector)
        _collector = collector
    logger.info("Deep profiling collector registered")


async def stop_deep_profiling() -> None:
    """Stop tracemalloc and cancel the snapshot task."""
    global _snapshot_task

    if _snapshot_task is not None:
        _snapshot_task.cancel()
        try:
            await _snapshot_task
        except asyncio.CancelledError:
            pass
        _snapshot_task = None

    if tracemalloc.is_tracing():
        tracemalloc.stop()
        logger.info("tracemalloc stopped")
