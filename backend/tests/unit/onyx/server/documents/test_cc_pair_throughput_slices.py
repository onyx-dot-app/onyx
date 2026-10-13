"""A run's documents spread over the slices it ran in. A running one counts up
to the window's end. A zero-length run lands in one slice. A run before the
window adds nothing."""

from datetime import datetime, timedelta, timezone

from onyx.db.enums import IndexingStatus
from onyx.db.models import IndexAttempt
from onyx.server.documents.cc_pair_throughput import docs_indexed_per_slice

_START = datetime(2026, 1, 1, tzinfo=timezone.utc)
_END = _START + timedelta(hours=4)


def _attempt(
    status: IndexingStatus, started: timedelta, updated: timedelta, docs: int
) -> IndexAttempt:
    return IndexAttempt(
        status=status,
        time_started=_START + started,
        time_updated=_START + updated,
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


def test_an_instant_run_lands_in_one_slice_and_an_earlier_run_adds_nothing() -> None:
    before = _attempt(
        IndexingStatus.SUCCESS, timedelta(hours=-3), timedelta(hours=-2), 40
    )
    instant = _attempt(
        IndexingStatus.SUCCESS, timedelta(hours=3), timedelta(hours=3), 7
    )

    assert docs_indexed_per_slice([before, instant], _START, _END, 4) == [0, 0, 0, 7]
