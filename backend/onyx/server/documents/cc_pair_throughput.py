"""A rough estimate of documents indexed over a window, from the index runs in
it. Nothing records when each document landed: a run records only its total, so
its documents spread evenly over the time it ran, and a slice's figure is that
interpolation, not a count."""

from datetime import datetime, timezone

from sqlalchemy.orm import Session

from onyx.db.cc_pair_runs import get_index_runs_since
from onyx.db.models import IndexAttempt
from onyx.server.documents.models import (
    CCPairThroughputResponse,
    CCPairThroughputRun,
    CCPairThroughputWindow,
)

# Bars per window, each wide enough to read at the chart's width: 3 minutes over
# an hour, 10 over 12 hours, 20 over a day and 2 hours over a week.
THROUGHPUT_SLICES: dict[CCPairThroughputWindow, int] = {
    CCPairThroughputWindow.HOURS_1: 20,
    CCPairThroughputWindow.HOURS_12: 72,
    CCPairThroughputWindow.HOURS_24: 72,
    CCPairThroughputWindow.DAYS_7: 84,
}


def run_ended_at(attempt: IndexAttempt, started: datetime) -> datetime | None:
    """When a finished run ended, or None while it still runs. A run from
    before time_finished existed ends at its last heartbeat check, and is
    instant when it never reached one."""
    if not attempt.is_finished():
        return None
    ended = attempt.time_finished or attempt.last_heartbeat_time
    return started if ended is None else max(ended, started)


def docs_indexed_per_slice(
    attempts: list[IndexAttempt],
    window_start: datetime,
    window_end: datetime,
    slice_count: int,
) -> list[int]:
    """Estimated documents indexed in each of ``slice_count`` equal slices of
    the window, oldest first: each run's total spread evenly over its span. A
    run still going counts up to ``window_end``."""
    width = (window_end - window_start) / slice_count
    totals = [0.0] * slice_count
    for attempt in attempts:
        docs = attempt.total_docs_indexed or 0
        if attempt.time_started is None or docs == 0:
            continue
        run_start = attempt.time_started
        run_end = run_ended_at(attempt, run_start) or window_end
        if run_end < window_start or run_start >= window_end:
            continue
        if run_end == run_start:
            totals[min(slice_count - 1, int((run_end - window_start) / width))] += docs
            continue
        per_second = docs / (run_end - run_start).total_seconds()
        first = max(0, int((run_start - window_start) / width))
        last = min(slice_count - 1, int((run_end - window_start) / width))
        for index in range(first, last + 1):
            slice_start = window_start + width * index
            overlap = min(run_end, slice_start + width) - max(run_start, slice_start)
            totals[index] += per_second * max(0.0, overlap.total_seconds())
    # Round the running total, not each slice, so the slices sum to the window total.
    counts: list[int] = []
    running = 0.0
    for total in totals:
        previous = round(running)
        running += total
        counts.append(round(running) - previous)
    return counts


def throughput_of(
    db_session: Session,
    cc_pair_ids: list[int],
    window: CCPairThroughputWindow,
) -> CCPairThroughputResponse:
    """The documents the pairs indexed in each equal slice of the window ending
    now, and the runs that overlap it."""
    window_end = datetime.now(timezone.utc)
    window_start = window_end - window.duration()
    attempts = get_index_runs_since(db_session, cc_pair_ids, window_start)
    return CCPairThroughputResponse(
        window_start=window_start,
        window_end=window_end,
        docs_indexed=docs_indexed_per_slice(
            attempts, window_start, window_end, THROUGHPUT_SLICES[window]
        ),
        # Every run the query gives overlaps the window, also one that began before it.
        runs=[_throughput_run(attempt) for attempt in attempts],
    )


def _throughput_run(attempt: IndexAttempt) -> CCPairThroughputRun:
    # A queued run has no start yet, so it starts at its creation.
    started = attempt.time_started or attempt.time_created
    return CCPairThroughputRun(
        started=started,
        ended=run_ended_at(attempt, started),
        status=attempt.status,
    )
