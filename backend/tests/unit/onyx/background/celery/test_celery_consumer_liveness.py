"""Unit coverage for the consumer-wedge liveness decision: a worker withholds
its k8s liveness touch (so the pod is restarted) only when detection is on, no
task has started within the threshold, nothing is currently running, and work is
still queued. Every other case — a busy/saturated worker, an unreadable active
count, an unreadable broker, or recent activity — keeps it alive."""

from onyx.background.celery.celery_consumer_liveness import ACTIVE_REQUESTS_UNKNOWN
from onyx.background.celery.celery_consumer_liveness import BACKLOG_UNKNOWN
from onyx.background.celery.celery_consumer_liveness import mark_task_consumed
from onyx.background.celery.celery_consumer_liveness import seconds_since_last_consumed
from onyx.background.celery.celery_consumer_liveness import (
    should_withhold_liveness_touch,
)


def _withhold(
    seconds_since: float,
    threshold: int,
    backlog: int,
    active_requests: int = 0,
) -> bool:
    return should_withhold_liveness_touch(
        seconds_since_consumed=seconds_since,
        stale_threshold_s=threshold,
        active_requests=active_requests,
        backlog=backlog,
    )


def test_withholds_when_stale_idle_with_backlog() -> None:
    assert _withhold(seconds_since=301, threshold=300, backlog=5) is True


def test_keeps_alive_when_threads_busy() -> None:
    # Saturated worker: all threads running long tasks, backlog waiting — healthy.
    assert (
        _withhold(seconds_since=9999, threshold=300, backlog=5000, active_requests=48)
        is False
    )


def test_keeps_alive_when_active_count_unknown() -> None:
    # Can't tell if threads are busy: fail open.
    assert (
        _withhold(
            seconds_since=9999,
            threshold=300,
            backlog=5000,
            active_requests=ACTIVE_REQUESTS_UNKNOWN,
        )
        is False
    )


def test_keeps_alive_when_recently_consumed() -> None:
    assert _withhold(seconds_since=10, threshold=300, backlog=5000) is False


def test_keeps_alive_when_stale_but_no_backlog() -> None:
    # An idle worker with empty queues is healthy, not wedged.
    assert _withhold(seconds_since=9999, threshold=300, backlog=0) is False


def test_fails_open_when_backlog_unknown() -> None:
    # Broker unreachable: a stale reading must never trigger a restart.
    assert (
        _withhold(seconds_since=9999, threshold=300, backlog=BACKLOG_UNKNOWN) is False
    )


def test_disabled_when_threshold_non_positive() -> None:
    assert _withhold(seconds_since=9999, threshold=0, backlog=5000) is False
    assert _withhold(seconds_since=9999, threshold=-1, backlog=5000) is False


def test_boundary_at_exact_threshold_keeps_alive() -> None:
    # Exactly at the threshold is not yet stale.
    assert _withhold(seconds_since=300, threshold=300, backlog=5) is False


def test_mark_task_consumed_resets_clock() -> None:
    mark_task_consumed()
    assert seconds_since_last_consumed() < 1.0
