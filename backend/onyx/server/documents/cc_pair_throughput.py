"""A rough estimate of documents indexed over a window, from the index runs in
it. Nothing records when each document landed: a run records only its total, so
its documents spread evenly over the time it ran, and a slice's figure is that
interpolation, not a count."""

from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from onyx.db.cc_pair_run_resolution import get_resolution_times
from onyx.db.cc_pair_runs import get_index_runs_since, get_superseded_runs
from onyx.db.cc_pair_runs_models import CCPairRunFilter
from onyx.db.enums import CCPairRunKind, IndexingStatus
from onyx.db.models import IndexAttempt
from onyx.server.documents.models import (
    CCPairThroughputResponse,
    CCPairThroughputRun,
    CCPairThroughputSlice,
    CCPairThroughputSliceRun,
    CCPairThroughputWindow,
)

# Bars per window, each wide enough to read at the chart's width: 3 minutes over
# an hour, 20 over a day and 2 hours over a week. All time reuses the week's count.
THROUGHPUT_SLICES: dict[CCPairThroughputWindow, int] = {
    CCPairThroughputWindow.HOURS_1: 20,
    CCPairThroughputWindow.HOURS_24: 72,
    CCPairThroughputWindow.DAYS_7: 84,
    CCPairThroughputWindow.ALL: 84,
}

# The client asks for as many bars as its width fits, within what the chart can read.
MIN_THROUGHPUT_BINS: int = 12
MAX_THROUGHPUT_BINS: int = 84

# UTC offsets run from -14:00 to +14:00.
MAX_TZ_OFFSET_MINUTES: int = 14 * 60

# All time spans at least a day, so a first run minutes old still gets
# readable slices.
MIN_ALL_TIME_SPAN: timedelta = timedelta(days=1)

# Slice boundaries are multiples of the slice width since this midnight in the
# caller's UTC offset: a width that divides a day lands on their clock, any other
# width keeps its own grid from here. The offset is the caller's current one, so
# across a DST change the far side of the window sits an hour off their clock.
_EPOCH: datetime = datetime(1970, 1, 1, tzinfo=timezone.utc)


def run_ended_at(attempt: IndexAttempt, started: datetime) -> datetime | None:
    """When a finished run ended, never before ``started``, or None while it
    still runs."""
    ended = attempt.end_time
    return None if ended is None else max(ended, started)


def docs_indexed_per_slice(
    attempts: list[IndexAttempt],
    window_start: datetime,
    window_end: datetime,
    slice_count: int,
    now: datetime | None = None,
) -> list[int]:
    """Estimated documents indexed in each of ``slice_count`` equal slices of
    the window, oldest first: each run's total spread evenly over its span. A
    run still going counts up to ``now``, or to ``window_end`` without it."""
    width = (window_end - window_start) / slice_count
    totals = [0.0] * slice_count
    for attempt in attempts:
        docs = attempt.total_docs_indexed or 0
        if attempt.time_started is None or docs == 0:
            continue
        run_start = attempt.time_started
        run_end = _run_end(attempt, run_start, window_end if now is None else now)
        overlapped = _slice_range(run_start, run_end, window_start, width, slice_count)
        if run_end == run_start:
            for index in overlapped:
                totals[index] += docs
            continue
        per_second = docs / (run_end - run_start).total_seconds()
        for index in overlapped:
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
    bins: int | None = None,
    tz_offset_minutes: int = 0,
) -> CCPairThroughputResponse:
    """The documents the pairs indexed in each of ``bins`` equal slices of the
    window (the window's default count without it), and the runs that overlap
    it. The window ends at the first slice boundary at or after now in the
    ``tz_offset_minutes`` clock, so the last slice holds now."""
    slice_count = THROUGHPUT_SLICES[window] if bins is None else bins
    now = datetime.now(timezone.utc)
    duration = window.duration()
    all_runs: list[IndexAttempt] | None = None
    if duration is None:
        all_runs = get_index_runs_since(db_session, cc_pair_ids, None)
        width = _all_time_width(all_runs, now, slice_count)
    else:
        width = duration / slice_count
    window_end = _next_slice_boundary(now, width, tz_offset_minutes)
    window_start = window_end - width * slice_count
    attempts = (
        get_index_runs_since(db_session, cc_pair_ids, window_start)
        if all_runs is None
        else all_runs
    )
    docs_indexed = docs_indexed_per_slice(
        attempts, window_start, window_end, slice_count, now
    )
    closed = _closed_attempt_ids(db_session, cc_pair_ids, attempts)
    slices = [
        CCPairThroughputSlice(
            start=window_start + width * index,
            end=window_start + width * (index + 1),
            docs_indexed=docs,
            runs=[],
        )
        for index, docs in enumerate(docs_indexed)
    ]
    for attempt in attempts:
        run = CCPairThroughputSliceRun(
            attempt_id=attempt.id,
            status=attempt.status,
            resolved=attempt.id in closed,
        )
        run_start = _run_started(attempt)
        run_end = _run_end(attempt, run_start, now)
        for index in _slice_range(run_start, run_end, window_start, width, slice_count):
            slices[index].runs.append(run)
    return CCPairThroughputResponse(
        window_start=window_start,
        window_end=window_end,
        docs_indexed=docs_indexed,
        # Every run the query gives overlaps the window, also one that began before it.
        runs=[_throughput_run(attempt) for attempt in attempts],
        slices=slices,
    )


def _all_time_width(
    attempts: list[IndexAttempt], now: datetime, slice_count: int
) -> timedelta:
    earliest = min(_run_started(attempt) for attempt in attempts) if attempts else now
    span = max(MIN_ALL_TIME_SPAN, now - earliest)
    # Rounding the end up moves it by under one slice, so the span keeps one
    # spare slice and the oldest run still starts inside the window.
    return span / (slice_count - 1)


def _next_slice_boundary(
    moment: datetime, width: timedelta, tz_offset_minutes: int
) -> datetime:
    """The first multiple of ``width`` since the epoch in the offset's clock at
    or after ``moment``."""
    origin = _EPOCH - timedelta(minutes=tz_offset_minutes)
    return origin + width * -(-(moment - origin) // width)


def _slice_range(
    run_start: datetime,
    run_end: datetime,
    window_start: datetime,
    width: timedelta,
    slice_count: int,
) -> range:
    """The indexes of the slices a run overlaps. An instant run is in the slice
    that holds it."""
    window_end = window_start + width * slice_count
    if run_end < window_start or run_start >= window_end:
        return range(0)
    first = min(slice_count - 1, max(0, (run_start - window_start) // width))
    if run_end == run_start:
        return range(first, first + 1)
    # A run that ends on a boundary does not reach the slice that starts there,
    # so one ending at the window's start is in none.
    if run_end == window_start:
        return range(0)
    after_last = -(-(min(run_end, window_end) - window_start) // width)
    return range(first, max(first + 1, min(slice_count, after_last)))


def _closed_attempt_ids(
    db_session: Session, cc_pair_ids: list[int], attempts: list[IndexAttempt]
) -> set[int]:
    """The attempts an admin resolved or a newer run superseded, the runs the
    activity panel no longer lists as open failures."""
    runs = [(CCPairRunKind.INDEXING, attempt.id) for attempt in attempts]
    run_filter = CCPairRunFilter(
        cc_pair_ids=cc_pair_ids,
        source=None,
        shared_sources=set(),
        since=None,
        until=None,
        error_query=None,
        status_groups=None,
        errors=None,
        superseded=None,
        resolved=None,
    )
    # Only a failed attempt can be superseded, and the newer-run check reads its
    # pair's whole history, so a window with no failures makes no such query.
    failed = [
        (CCPairRunKind.INDEXING, attempt.id)
        for attempt in attempts
        if attempt.status == IndexingStatus.FAILED
    ]
    closed = set(get_resolution_times(db_session, runs)) | get_superseded_runs(
        db_session, run_filter, failed
    )
    return {run_id for _, run_id in closed}


def _run_end(attempt: IndexAttempt, run_start: datetime, now: datetime) -> datetime:
    # A run still going has reached now and no further.
    return run_ended_at(attempt, run_start) or max(now, run_start)


def _run_started(attempt: IndexAttempt) -> datetime:
    # A queued run has no start yet, so it starts at its creation.
    return attempt.time_started or attempt.time_created


def _throughput_run(attempt: IndexAttempt) -> CCPairThroughputRun:
    started = _run_started(attempt)
    return CCPairThroughputRun(
        started=started,
        ended=run_ended_at(attempt, started),
        status=attempt.status,
    )
