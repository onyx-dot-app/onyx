"""A run's documents spread over the slices it ran in. A running one counts up
to the window's end. A finished run ends at its last heartbeat, or is instant
without one. A run before the window adds nothing."""

from datetime import datetime, timedelta, timezone

from onyx.db.enums import IndexingStatus
from onyx.db.models import IndexAttempt
from onyx.server.documents.cc_pair_throughput import docs_indexed_per_slice

_START = datetime(2026, 1, 1, tzinfo=timezone.utc)
_END = _START + timedelta(hours=4)


def _attempt(
    status: IndexingStatus,
    started: timedelta,
    heartbeat: timedelta | None,
    docs: int,
) -> IndexAttempt:
    return IndexAttempt(
        status=status,
        time_started=_START + started,
        last_heartbeat_time=None if heartbeat is None else _START + heartbeat,
        # Cleanup can move this days later, so the slicer never reads it.
        time_updated=_END + timedelta(days=9),
        total_docs_indexed=docs,
    )


def test_a_finished_run_spreads_over_the_slices_it_ran_in() -> None:
    run = _attempt(
        IndexingStatus.SUCCESS, timedelta(minutes=30), timedelta(minutes=90), 60
    )

    assert docs_indexed_per_slice([run], _START, _END, 4) == [30, 30, 0, 0]


def test_a_running_run_counts_up_to_the_window_end() -> None:
    run = _attempt(
        IndexingStatus.IN_PROGRESS, timedelta(hours=2), timedelta(hours=2), 100
    )

    assert docs_indexed_per_slice([run], _START, _END, 4) == [0, 0, 50, 50]


def test_a_run_from_before_the_window_counts_the_part_inside_it() -> None:
    run = _attempt(IndexingStatus.SUCCESS, timedelta(hours=-1), timedelta(hours=1), 80)

    assert docs_indexed_per_slice([run], _START, _END, 4) == [40, 0, 0, 0]


def test_instant_runs_land_in_one_slice_and_an_earlier_run_adds_nothing() -> None:
    before = _attempt(
        IndexingStatus.SUCCESS, timedelta(hours=-3), timedelta(hours=-2), 40
    )
    instant = _attempt(
        IndexingStatus.SUCCESS, timedelta(hours=3), timedelta(hours=3), 7
    )
    no_heartbeat = _attempt(IndexingStatus.SUCCESS, timedelta(hours=1), None, 5)

    assert docs_indexed_per_slice([before, instant, no_heartbeat], _START, _END, 4) == [
        0,
        5,
        0,
        7,
    ]
