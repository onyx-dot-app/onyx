"""Recent OpenSearch search samples for the admin Service Status page.

Each process buffers one small sample per search and flushes the buffer to
the shared cache every few seconds, as one member of a per-minute set. The
status page reads the last minutes from every process. Prometheus keeps
latency buckets per process; this keeps individual searches, so the page can
show each slow or failed one and a few of the others.
"""

import json
import math
import os
import random
import threading
import time
import uuid
from enum import Enum
from typing import Any

from pydantic import BaseModel

from onyx.cache.factory import get_shared_cache_backend
from onyx.cache.interface import CacheBackend
from onyx.configs.app_configs import CACHE_BACKEND, DISABLE_VECTOR_DB
from onyx.configs.constants import CacheBackendType
from onyx.utils.logger import setup_logger
from shared_configs.configs import MULTI_TENANT

logger = setup_logger()

SAMPLE_KEY_PREFIX = "opensearch_search_samples"
SAMPLE_WINDOW_MINUTES = 30
FLUSH_INTERVAL_SECONDS = 5.0
# A process drops samples beyond this many between flushes.
MAX_BUFFERED_SAMPLES = 5000
# Batches per minute that a read takes; each process flushes about 12 a minute.
MAX_BATCHES_PER_MINUTE = 2000
# The response lists each slow or failed search, up to this many (the latest).
MAX_RETURNED_SAMPLES = 1000
# The response also lists up to this many of each minute's other searches.
MAX_TYPICAL_SAMPLES_PER_MINUTE = 20
SLOW_SEARCH_MS = 1000
# A minute whose p90 is above this shows as slow on the status page. A healthy
# 1.56M-chunk index in memory measured a p95 under 700 ms; a disk or memory
# limit pushed it past 800 ms.
SLOW_P90_MS = 700
_KEY_TTL_SECONDS = (SAMPLE_WINDOW_MINUTES + 5) * 60


class SearchResult(str, Enum):
    OK = "ok"
    ERROR = "error"
    TIMEOUT = "timeout"


class SearchSample(BaseModel):
    # Epoch milliseconds when the search finished.
    at_ms: int
    client_ms: float
    server_ms: int | None
    search_type: str
    result: SearchResult


class SearchRatePoint(BaseModel):
    """The searches of one minute."""

    # Epoch milliseconds at the start of the minute.
    minute_ms: int
    # 60, or the seconds elapsed so far for the current minute.
    seconds: float
    count: int
    error_count: int = 0
    # Percentiles of the minute's successful searches; None without any.
    p10_ms: float | None = None
    p90_ms: float | None = None


class SearchActivity(BaseModel):
    window_minutes: int
    total_count: int
    error_count: int
    p90_ms: float | None
    rate: list[SearchRatePoint]
    slow_p90_ms: int = SLOW_P90_MS
    # Every slow or failed search, and a random few of each minute's others.
    samples: list[SearchSample]
    # True when more slow or failed searches happened than samples lists.
    sampled: bool


class _Buffer:
    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.samples: list[dict[str, Any]] = []
        self.process_id: str = uuid.uuid4().hex
        self.sequence: int = 0
        self.flusher: threading.Thread | None = None


_buffer = _Buffer()


def _reset_buffer_after_fork() -> None:
    # A forked child inherits the parent's buffer, and a lock the parent's
    # flusher may hold, but not the flusher thread.
    _buffer.lock = threading.Lock()
    _buffer.samples = []
    _buffer.process_id = uuid.uuid4().hex
    _buffer.flusher = None


os.register_at_fork(after_in_child=_reset_buffer_after_fork)

# Cloud shares the cluster across tenants and does not serve the page. The
# PostgreSQL cache keeps set members without an expiry, so samples there would
# never be removed.
RECORDING_ENABLED = (
    not MULTI_TENANT
    and not DISABLE_VECTOR_DB
    and CACHE_BACKEND == CacheBackendType.REDIS
)


def _minute_key(minute: int) -> str:
    return f"{SAMPLE_KEY_PREFIX}:{minute}"


def _start_flusher_locked() -> None:
    if _buffer.flusher is None or not _buffer.flusher.is_alive():
        _buffer.flusher = threading.Thread(
            target=_flush_forever, name="opensearch-search-samples", daemon=True
        )
        _buffer.flusher.start()


def record_search_sample(
    search_type: str,
    client_duration_s: float,
    server_took_ms: int | None,
    result: SearchResult,
) -> None:
    """Buffers one search. Never raises; samples are best-effort."""
    if not RECORDING_ENABLED:
        return
    try:
        sample: dict[str, Any] = {
            "at_ms": int(time.time() * 1000),
            "client_ms": round(client_duration_s * 1000, 1),
            "server_ms": server_took_ms,
            "search_type": search_type,
            "result": result.value,
        }
        with _buffer.lock:
            _start_flusher_locked()
            if len(_buffer.samples) < MAX_BUFFERED_SAMPLES:
                _buffer.samples.append(sample)
    except Exception:
        logger.debug("Unable to record an OpenSearch search sample", exc_info=True)


def flush_search_samples() -> None:
    """Writes the buffered samples to the shared cache, grouped by minute."""
    with _buffer.lock:
        samples: list[dict[str, Any]] = _buffer.samples
        _buffer.samples = []
    if not samples:
        return
    by_minute: dict[int, list[dict[str, Any]]] = {}
    for sample in samples:
        by_minute.setdefault(sample["at_ms"] // 60000, []).append(sample)
    cache: CacheBackend = get_shared_cache_backend()
    for minute, batch in by_minute.items():
        with _buffer.lock:
            _buffer.sequence += 1
            member: str = json.dumps(
                {"id": f"{_buffer.process_id}:{_buffer.sequence}", "samples": batch},
                separators=(",", ":"),
            )
        key: str = _minute_key(minute)
        cache.set_add(key, member)
        cache.expire(key, _KEY_TTL_SECONDS)


def _flush_forever() -> None:
    while True:
        time.sleep(FLUSH_INTERVAL_SECONDS)
        try:
            flush_search_samples()
        except Exception:
            logger.debug("Unable to flush OpenSearch search samples", exc_info=True)


def _percentile(sorted_values: list[float], fraction: float) -> float | None:
    if not sorted_values:
        return None
    index: int = min(
        len(sorted_values) - 1, math.ceil(fraction * len(sorted_values)) - 1
    )
    return sorted_values[max(index, 0)]


def _is_notable(sample: SearchSample) -> bool:
    return sample.result != SearchResult.OK or sample.client_ms >= SLOW_SEARCH_MS


def read_search_activity(now_ms: int | None = None) -> SearchActivity:
    """Returns the searches of the last SAMPLE_WINDOW_MINUTES from all processes.

    The window starts on a whole minute, so it holds the current minute so far
    and the SAMPLE_WINDOW_MINUTES - 1 whole minutes before it.
    """
    now_ms = now_ms if now_ms is not None else int(time.time() * 1000)
    start_ms: int = (now_ms // 60000 - SAMPLE_WINDOW_MINUTES + 1) * 60000
    cache: CacheBackend = get_shared_cache_backend()
    samples: list[SearchSample] = []
    for minute in range(start_ms // 60000, now_ms // 60000 + 1):
        for raw in cache.set_members(_minute_key(minute), limit=MAX_BATCHES_PER_MINUTE):
            for item in json.loads(raw)["samples"]:
                sample = SearchSample.model_validate(item)
                if start_ms <= sample.at_ms <= now_ms:
                    samples.append(sample)
    samples.sort(key=lambda sample: sample.at_ms)

    by_minute: dict[int, list[SearchSample]] = {}
    for sample in samples:
        by_minute.setdefault(sample.at_ms // 60000 * 60000, []).append(sample)
    rate: list[SearchRatePoint] = []
    typical_samples: list[SearchSample] = []
    for minute_ms in range(start_ms, now_ms // 60000 * 60000 + 1, 60000):
        minute_samples: list[SearchSample] = by_minute.get(minute_ms, [])
        ok: list[float] = sorted(
            sample.client_ms
            for sample in minute_samples
            if sample.result == SearchResult.OK
        )
        rate.append(
            SearchRatePoint(
                minute_ms=minute_ms,
                # At least 1 s, so a rate never divides by zero.
                seconds=max(1.0, min(60000, now_ms - minute_ms) / 1000),
                count=len(minute_samples),
                error_count=len(minute_samples) - len(ok),
                p10_ms=_percentile(ok, 0.1),
                p90_ms=_percentile(ok, 0.9),
            )
        )
        typical: list[SearchSample] = [
            sample for sample in minute_samples if not _is_notable(sample)
        ]
        # Seeded by the minute, so a refresh shows the same searches.
        typical_samples.extend(
            random.Random(minute_ms).sample(
                typical, min(len(typical), MAX_TYPICAL_SAMPLES_PER_MINUTE)
            )
        )
    # Failures and timeouts are counted, not timed: a 60 s timeout would skew them.
    durations: list[float] = sorted(
        sample.client_ms for sample in samples if sample.result == SearchResult.OK
    )
    notable: list[SearchSample] = [sample for sample in samples if _is_notable(sample)]
    listed: list[SearchSample] = sorted(
        typical_samples + notable[-MAX_RETURNED_SAMPLES:],
        key=lambda sample: sample.at_ms,
    )
    return SearchActivity(
        window_minutes=SAMPLE_WINDOW_MINUTES,
        total_count=len(samples),
        error_count=sum(1 for sample in samples if sample.result != SearchResult.OK),
        p90_ms=_percentile(durations, 0.9),
        rate=rate,
        samples=listed,
        sampled=len(notable) > MAX_RETURNED_SAMPLES,
    )
