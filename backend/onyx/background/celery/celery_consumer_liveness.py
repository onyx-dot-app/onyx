"""Detects an in-process Celery consumer wedge so Kubernetes can restart the pod.

A worker can wedge while staying alive: the pod keeps running and its timer
threads keep firing (so the timer-touched liveness file stays fresh), but the
Celery consumer stops fetching from the broker — tasks pile up while every pool
thread sits idle. The file-mtime liveness probe can't see this on its own.

Here the worker withholds the liveness-file touch when it looks wedged, so the
stale file trips the existing k8s liveness probe and the pod is restarted. The
wedge signature is narrow on purpose, because a false positive restarts a
healthy pod: no task started within the threshold, AND nothing is currently
executing (a saturated worker busy on long tasks is NOT wedged), AND work is
still waiting. Every "can't tell" reading fails open and keeps the worker alive.

The "last consumed" signal is kept in process (not in Redis) so the restart
decision never depends on an external store that can blip or evict the key.
Detection is opt-in per deployment via CELERY_LIVENESS_WEDGE_STALE_THRESHOLD_S.
"""

import time

from celery.worker import state as worker_state  # ty: ignore[unresolved-import]

# Sentinels meaning "could not determine". Both fail open (never restart).
BACKLOG_UNKNOWN = -1
ACTIVE_REQUESTS_UNKNOWN = -1

# Monotonic timestamp of the last task this worker started. Written from task
# threads (task_prerun), read from the liveness timer thread; a bare float is
# safe to share under the GIL.
_last_consumed_monotonic: float = time.monotonic()


def mark_task_consumed() -> None:
    """Record that the worker just started executing a task."""
    global _last_consumed_monotonic
    _last_consumed_monotonic = time.monotonic()


def seconds_since_last_consumed() -> float:
    return time.monotonic() - _last_consumed_monotonic


def active_request_count() -> int:
    """Tasks this worker is currently executing, or ACTIVE_REQUESTS_UNKNOWN if it
    can't be read. Unknown fails open: a worker that might be busy is never
    treated as wedged."""
    try:
        return len(worker_state.active_requests)
    except Exception:
        return ACTIVE_REQUESTS_UNKNOWN


def reserved_request_count() -> int:
    """Tasks prefetched into this worker but not yet started — a wedge that
    happens after prefetch drains the broker's ready lists but leaves these
    stranded. 0 if unreadable, which only omits this evidence (never invents
    work)."""
    try:
        return len(worker_state.reserved_requests)
    except Exception:
        return 0


def should_withhold_liveness_touch(
    *,
    seconds_since_consumed: float,
    stale_threshold_s: int,
    active_requests: int,
    backlog: int,
) -> bool:
    """Whether to skip the liveness touch (→ k8s restarts the pod).

    Withhold only when no task has started within the threshold, no task is
    currently running, and work is still queued. A non-positive threshold means
    detection is off. A non-zero ``active_requests`` (busy, or the unknown
    sentinel) and any non-positive ``backlog`` (incl. BACKLOG_UNKNOWN) fail open.
    """
    if stale_threshold_s <= 0:
        return False
    if seconds_since_consumed <= stale_threshold_s:
        return False
    if active_requests != 0:
        return False
    return backlog > 0
