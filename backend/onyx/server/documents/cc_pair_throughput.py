"""Documents indexed over a window, from the index runs in it. A run records
only its total, so its documents spread evenly over the time it ran."""

from datetime import datetime

from onyx.db.models import IndexAttempt


def docs_indexed_per_slice(
    attempts: list[IndexAttempt],
    window_start: datetime,
    window_end: datetime,
    slice_count: int,
) -> list[int]:
    """Documents indexed in each of ``slice_count`` equal slices of the window,
    oldest first. A run still going counts up to ``window_end``."""
    width = (window_end - window_start) / slice_count
    totals = [0.0] * slice_count
    for attempt in attempts:
        docs = attempt.total_docs_indexed or 0
        if attempt.time_started is None or docs == 0:
            continue
        run_start = attempt.time_started
        # A run from before time_finished existed ends at its last heartbeat
        # check, and is instant when it never reached one.
        ended = attempt.time_finished or attempt.last_heartbeat_time
        if not attempt.is_finished():
            run_end = window_end
        elif ended is None:
            run_end = run_start
        else:
            run_end = max(ended, run_start)
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
