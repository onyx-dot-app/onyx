"""A run's documents spread over the slices it ran in. A running one counts up
to the window's end. A finished run ends at its recorded finish, an older one
at its last heartbeat, and one with neither is instant. A run before the
window adds nothing."""

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy.orm import Session

from onyx.db.enums import IndexingStatus
from onyx.db.models import IndexAttempt
from onyx.server.documents import cc_pair_throughput
from onyx.server.documents.cc_pair_throughput import (
    THROUGHPUT_SLICES,
    docs_indexed_per_slice,
    throughput_of,
)
from onyx.server.documents.models import (
    CCPairThroughputResponse,
    CCPairThroughputWindow,
)

_START = datetime(2026, 1, 1, tzinfo=timezone.utc)
_END = _START + timedelta(hours=4)


def _attempt(
    status: IndexingStatus,
    started: timedelta,
    finished: timedelta | None,
    docs: int,
    # An attempt from before time_finished existed: its last heartbeat stands in.
    legacy: bool = False,
) -> IndexAttempt:
    ended = None if finished is None else _START + finished
    return IndexAttempt(
        status=status,
        time_started=_START + started,
        time_finished=None if legacy else ended,
        last_heartbeat_time=ended if legacy else None,
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
    unknown_end = _attempt(IndexingStatus.SUCCESS, timedelta(hours=1), None, 5)
    legacy = _attempt(
        IndexingStatus.SUCCESS, timedelta(hours=2), timedelta(hours=3), 10, legacy=True
    )

    assert docs_indexed_per_slice(
        [before, instant, unknown_end, legacy], _START, _END, 4
    ) == [0, 5, 10, 7]


# Off every bin boundary, so the window's end must round up to one.
_NOW = datetime(2026, 1, 1, 13, 47, 12, tzinfo=timezone.utc)
_EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)


@contextmanager
def _no_runs_at(now: datetime) -> Iterator[None]:
    """Pins the clock and gives the window no runs, so only the slicing shows."""
    with (
        patch.object(cc_pair_throughput, "datetime", wraps=datetime) as frozen,
        patch.object(cc_pair_throughput, "get_index_runs_since", return_value=[]),
    ):
        frozen.now.return_value = now
        yield


def _throughput(
    window: CCPairThroughputWindow, bins: int | None
) -> CCPairThroughputResponse:
    session = MagicMock(spec=Session)
    with _no_runs_at(_NOW):
        if bins is None:
            # Absent, as an old web pod sends it.
            return throughput_of(session, [1], window)
        return throughput_of(session, [1], window, bins=bins)


def _next_boundary(moment: datetime, width: timedelta) -> datetime:
    """The first multiple of ``width`` since the epoch at or after ``moment``.
    Each width used here divides a day, so it is also a multiple since midnight UTC."""
    whole = -(-(moment - _EPOCH) // width)
    return _EPOCH + width * whole


def test_ac1_bins_sets_the_slice_count() -> None:
    response = _throughput(CCPairThroughputWindow.HOURS_24, 48)

    assert len(response.docs_indexed) == 48
    assert len(response.slices) == 48


@pytest.mark.parametrize("window", list(CCPairThroughputWindow))
def test_ac1_no_bins_keeps_the_window_default_count(
    window: CCPairThroughputWindow,
) -> None:
    response = _throughput(window, None)

    assert len(response.docs_indexed) == THROUGHPUT_SLICES[window]
    assert len(response.slices) == THROUGHPUT_SLICES[window]


@pytest.mark.parametrize(
    ("window", "bins", "width"),
    [
        (CCPairThroughputWindow.HOURS_1, None, timedelta(minutes=3)),
        (CCPairThroughputWindow.HOURS_1, 12, timedelta(minutes=5)),
        (CCPairThroughputWindow.HOURS_24, None, timedelta(minutes=20)),
        (CCPairThroughputWindow.HOURS_24, 48, timedelta(minutes=30)),
        (CCPairThroughputWindow.HOURS_24, 12, timedelta(hours=2)),
        (CCPairThroughputWindow.DAYS_7, None, timedelta(hours=2)),
        (CCPairThroughputWindow.DAYS_7, 84, timedelta(hours=2)),
    ],
)
def test_ac2_slices_start_on_clock_boundaries(
    window: CCPairThroughputWindow, bins: int | None, width: timedelta
) -> None:
    response = _throughput(window, bins)

    duration = window.duration()
    assert duration is not None
    # The end rounds up to the next bin boundary instead of stopping at now.
    expected_end = _next_boundary(_NOW, width)
    assert response.window_end == expected_end
    assert response.window_start == expected_end - duration
    assert [(s.start, s.end) for s in response.slices] == [
        (response.window_start + width * i, response.window_start + width * (i + 1))
        for i in range(len(response.slices))
    ]


def test_ac2_all_time_bins_split_the_span_into_whole_slices() -> None:
    response = _throughput(CCPairThroughputWindow.ALL, 24)

    assert len(response.slices) == 24
    assert response.window_end >= _NOW
    assert (
        response.window_end - response.window_start
        >= cc_pair_throughput.MIN_ALL_TIME_SPAN
    )
    assert response.slices[0].start == response.window_start
    assert response.slices[-1].end == response.window_end
    for earlier, later in zip(response.slices, response.slices[1:], strict=False):
        assert earlier.end == later.start
    width = response.slices[0].end - response.slices[0].start
    assert all(s.end - s.start == width for s in response.slices)


def test_ac5_an_empty_window_gives_empty_slices() -> None:
    response = _throughput(CCPairThroughputWindow.HOURS_24, 36)

    assert response.docs_indexed == [0] * 36
    assert [(s.docs_indexed, s.runs) for s in response.slices] == [(0, [])] * 36
    assert response.runs == []
