"""One-shot memory diagnostics for spawned indexing workers. When a worker's
RSS crosses a fraction of INDEXING_WORKER_MEMORY_LIMIT_MB, logs a tracemalloc
snapshot (when enabled) so the allocation sites are captured in the logs before
the docfetching watchdog terminates the process."""

import threading
import tracemalloc

import psutil

from onyx.configs.app_configs import INDEXING_WORKER_MEMORY_LIMIT_MB
from onyx.configs.app_configs import INDEXING_WORKER_TRACEMALLOC
from onyx.utils.logger import setup_logger

logger = setup_logger()

_CHECK_INTERVAL_SECONDS = 15
_REPORT_FRACTION = 0.75
_TOP_ALLOCATIONS = 15
_TRACEMALLOC_FRAMES = 10

MemoryObserver = tuple[threading.Thread, threading.Event]


def start_memory_observer(index_attempt_id: int) -> MemoryObserver | None:
    """Mirrors the heartbeat thread pattern; call from the spawned process
    entrypoint. No-op unless the memory limit is configured."""
    if INDEXING_WORKER_MEMORY_LIMIT_MB <= 0:
        return None

    if INDEXING_WORKER_TRACEMALLOC and not tracemalloc.is_tracing():
        tracemalloc.start(_TRACEMALLOC_FRAMES)

    stop_event = threading.Event()
    thread = threading.Thread(
        target=_observe,
        args=(index_attempt_id, stop_event),
        name=f"memory-observer-{index_attempt_id}",
        daemon=True,
    )
    thread.start()
    return thread, stop_event


def stop_memory_observer(observer: MemoryObserver | None) -> None:
    if observer is None:
        return
    thread, stop_event = observer
    stop_event.set()
    thread.join(timeout=5)


def _observe(index_attempt_id: int, stop_event: threading.Event) -> None:
    report_threshold_mb = int(INDEXING_WORKER_MEMORY_LIMIT_MB * _REPORT_FRACTION)
    process = psutil.Process()
    while not stop_event.wait(_CHECK_INTERVAL_SECONDS):
        try:
            rss_mb = process.memory_info().rss // (1024 * 1024)
        except psutil.Error:
            continue
        if rss_mb < report_threshold_mb:
            continue
        _report(index_attempt_id, rss_mb)
        # one-shot: the snapshot is expensive and one capture identifies the sites
        return


def _report(index_attempt_id: int, rss_mb: int) -> None:
    logger.warning(
        "Indexing worker memory nearing the limit: attempt=%s rss_mb=%s limit_mb=%s",
        index_attempt_id,
        rss_mb,
        INDEXING_WORKER_MEMORY_LIMIT_MB,
    )

    if not tracemalloc.is_tracing():
        logger.warning(
            "tracemalloc is disabled; set INDEXING_WORKER_TRACEMALLOC=true to "
            "capture allocation sites in this report"
        )
        return

    snapshot = tracemalloc.take_snapshot()
    stats = snapshot.statistics("lineno")
    for stat in stats[:_TOP_ALLOCATIONS]:
        logger.warning("tracemalloc top allocation: %s", stat)
    if stats:
        for line in stats[0].traceback.format():
            logger.warning("tracemalloc largest site: %s", line)
