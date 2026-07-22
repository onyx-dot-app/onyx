# backend/onyx/background/celery/memory_monitoring.py
import logging
import os
import threading
import tracemalloc
from logging.handlers import RotatingFileHandler

import psutil

from onyx.configs.app_configs import INDEXING_WORKER_MEMORY_LIMIT_MB
from onyx.configs.app_configs import INDEXING_WORKER_TRACEMALLOC
from onyx.utils.logger import setup_logger
from onyx.utils.platform_utils import is_running_in_container

# Regular application logger
logger = setup_logger()

# Only set up memory monitoring in container environment
if is_running_in_container():
    # Set up a dedicated memory monitoring logger
    MEMORY_LOG_DIR = "/tmp/onyx/memory"
    MEMORY_LOG_FILE = os.path.join(MEMORY_LOG_DIR, "memory_usage.log")
    MEMORY_LOG_MAX_BYTES = 10 * 1024 * 1024  # 10MB
    MEMORY_LOG_BACKUP_COUNT = 5  # Keep 5 backup files

    # Ensure log directory exists
    os.makedirs(MEMORY_LOG_DIR, exist_ok=True)

    # Create a dedicated logger for memory monitoring
    memory_logger = logging.getLogger("memory_monitoring")
    memory_logger.setLevel(logging.INFO)

    # Create a rotating file handler
    memory_handler = RotatingFileHandler(
        MEMORY_LOG_FILE,
        maxBytes=MEMORY_LOG_MAX_BYTES,
        backupCount=MEMORY_LOG_BACKUP_COUNT,
    )

    # Create a formatter that includes all relevant information
    memory_formatter = logging.Formatter(
        "%(asctime)s [%(levelname)s] %(message)s", datefmt="%Y-%m-%d %H:%M:%S"
    )
    memory_handler.setFormatter(memory_formatter)
    memory_logger.addHandler(memory_handler)
else:
    # Create a null logger when not in container
    memory_logger = logging.getLogger("memory_monitoring")
    memory_logger.addHandler(logging.NullHandler())


def emit_process_memory(
    pid: int, process_name: str, additional_metadata: dict[str, str | int]
) -> None:
    # Skip memory monitoring if not in container
    if not is_running_in_container():
        return

    try:
        process = psutil.Process(pid)
        memory_info = process.memory_info()
        cpu_percent = process.cpu_percent(interval=0.1)

        # Build metadata string from additional_metadata dictionary
        metadata_str = " ".join(
            [f"{key}={value}" for key, value in additional_metadata.items()]
        )
        metadata_str = f" {metadata_str}" if metadata_str else ""

        memory_logger.info(
            "PROCESS_MEMORY process_name=%s pid=%s rss_mb=%s vms_mb=%s cpu=%s%s",
            process_name,
            pid,
            format(memory_info.rss / (1024 * 1024), ".2f"),
            format(memory_info.vms / (1024 * 1024), ".2f"),
            format(cpu_percent, ".2f"),
            metadata_str,
        )
    except Exception:
        logger.exception("Error monitoring process memory.")


# --- Near-limit memory diagnostics for spawned indexing workers ---
# When a worker's RSS crosses a fraction of INDEXING_WORKER_MEMORY_LIMIT_MB,
# log a tracemalloc snapshot (when enabled) so allocation sites are captured
# before the docfetching watchdog terminates the process.

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
