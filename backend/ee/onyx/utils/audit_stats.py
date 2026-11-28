"""Per-tenant counts of the audit events Onyx wrote, for the admin status page.

Onyx cannot see the customer's log shipper or SIEM, so these numbers say only
that Onyx wrote events. Recording never raises and never blocks emission.

- ``record_event`` only queues the count. One daemon thread per process writes
  it, so the cache write (a pooled connection on the PostgreSQL cache backend)
  never runs on a caller that may already hold a connection or a row lock. A
  full queue drops counts: the status page is a diagnostic, not a ledger.
- Count: one ``incr`` per event into an hourly bucket that lives 25 hours. The
  count sums the current clock hour and the 23 before it.
- Last event time: written at most once a minute per class in each process.
"""

import logging
import queue
import threading
import time

from onyx.cache.factory import get_cache_backend

# Not under ``onyx.audit``, so these warnings never reach the audit stream.
_internal_logger = logging.getLogger(__name__)

_HOUR_SECONDS = 3600
_WINDOW_HOURS = 24
_BUCKET_TTL_SECONDS = (_WINDOW_HOURS + 1) * _HOUR_SECONDS
_LAST_EVENT_TTL_SECONDS = 30 * 24 * _HOUR_SECONDS
_LAST_EVENT_WRITE_INTERVAL_SECONDS = 60.0
_QUEUE_SIZE = 10_000

_queue: queue.Queue[tuple[str | None, str, float]] = queue.Queue(maxsize=_QUEUE_SIZE)
_writer: threading.Thread | None = None
_writer_lock = threading.Lock()
_last_event_written_at: dict[tuple[str | None, str], float] = {}


def _count_key(event_class: str, hour: int) -> str:
    return f"audit:stats:count:{event_class}:{hour}"


def _last_event_key(event_class: str) -> str:
    return f"audit:stats:last:{event_class}"


def _write_event(tenant_id: str | None, event_class: str, ts: float) -> None:
    cache = get_cache_backend(tenant_id=tenant_id)
    cache.incr(
        _count_key(event_class, int(ts // _HOUR_SECONDS)), ex=_BUCKET_TTL_SECONDS
    )
    throttle_key = (tenant_id, event_class)
    written_at = _last_event_written_at.get(throttle_key)
    if (
        written_at is not None
        and time.monotonic() - written_at < _LAST_EVENT_WRITE_INTERVAL_SECONDS
    ):
        return
    _last_event_written_at[throttle_key] = time.monotonic()
    # Writers in other processes can lag; never move the time backwards. Two
    # writers racing here can still swap within a minute, which is fine for a
    # diagnostic.
    current = cache.get(_last_event_key(event_class))
    if current is None or float(current) < ts:
        cache.set(_last_event_key(event_class), ts, ex=_LAST_EVENT_TTL_SECONDS)


def _drain() -> None:
    while True:
        tenant_id, event_class, ts = _queue.get()
        try:
            _write_event(tenant_id, event_class, ts)
        except Exception:
            _internal_logger.warning(
                "Failed to record audit event stats", exc_info=True
            )
        finally:
            _queue.task_done()


def _ensure_writer() -> None:
    global _writer
    # A forked worker inherits the reference but not the thread, so check that
    # it runs, not only that it exists.
    if _writer is not None and _writer.is_alive():
        return
    with _writer_lock:
        if _writer is None or not _writer.is_alive():
            _writer = threading.Thread(
                target=_drain, name="audit-stats-writer", daemon=True
            )
            _writer.start()


def record_event(tenant_id: str | None, event_class: str) -> None:
    """Queue one count of a written event. Never raises or blocks."""
    try:
        _ensure_writer()
        _queue.put_nowait((tenant_id, event_class, time.time()))
    except queue.Full:
        _internal_logger.debug("Audit stats queue full; dropping a count")
    except Exception:
        _internal_logger.warning("Failed to queue audit event stats", exc_info=True)


def read_class_stats(
    tenant_id: str | None, event_class: str
) -> tuple[int, float | None]:
    """``(events in the last 24 hours, last event epoch seconds)``."""
    cache = get_cache_backend(tenant_id=tenant_id)
    current_hour = int(time.time() // _HOUR_SECONDS)
    count = 0
    for hour in range(current_hour - _WINDOW_HOURS + 1, current_hour + 1):
        raw = cache.get(_count_key(event_class, hour))
        if raw is not None:
            count += int(raw)
    last_raw = cache.get(_last_event_key(event_class))
    return count, float(last_raw) if last_raw is not None else None
