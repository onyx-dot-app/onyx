"""The split plan and the window of the parallel Drive listing. A split must
cover the whole shard with no overlap, wherever the files are, because the
sub-ranges are the only record of what is still to list."""

from datetime import datetime, timezone
from typing import cast

import pytest

from onyx.connectors.google_drive import parallel_listing
from onyx.connectors.google_drive.file_retrieval import (
    RESOLVED_FROM_SHORTCUT_KEY,
    DriveFileFieldType,
)
from onyx.connectors.google_drive.models import (
    DriveListingState,
    DriveRetrievalStage,
    GoogleDriveCheckpoint,
    GoogleDriveFileType,
    ListingPartition,
    ListingPartitionKind,
    ListingShard,
)
from onyx.connectors.google_drive.parallel_listing import (
    extend_window,
    plan_split,
    window_ms,
)
from onyx.connectors.google_drive.source_operations import (
    GoogleDriveSourceOperations,
)
from onyx.connectors.models import DocumentTypeLabel
from onyx.utils.threadpool_concurrency import ThreadSafeDict

_DRIVE = ListingPartition(kind=ListingPartitionKind.SHARED_DRIVE, key="drive_1")
_DAY = 86_400_000


def _shard(t0: int, t1: int) -> ListingShard:
    return ListingShard(id=1, partition=_DRIVE, principal="a@x.com", t0=t0, t1=t1)


def _assert_covers(ranges: list[tuple[int, int]], t0: int, t1: int) -> None:
    assert ranges[0][0] == t0
    assert ranges[-1][1] == t1
    for (_, end), (start, _) in zip(ranges, ranges[1:], strict=False):
        assert end == start
    assert all(start < end for start, end in ranges)


def test_a_dense_range_splits_into_ranges_that_cover_the_shard() -> None:
    # The first page holds one hour of a year of files.
    shard = _shard(0, 1000 * _DAY)
    page = [500 * _DAY + i * 3_600 for i in range(1000)]
    newest = 865 * _DAY

    ranges = plan_split(shard, page, newest)

    assert len(ranges) == parallel_listing.SPLIT_MAX_WAYS
    _assert_covers(ranges, shard.t0, shard.t1)
    # The cuts lie where the files are, not in the empty time around them.
    assert ranges[0][1] > 500 * _DAY
    assert ranges[-1][0] < newest


def test_a_range_of_few_files_does_not_split() -> None:
    shard = _shard(0, 1000 * _DAY)
    # Two files over a tenth of the files' range: about 20 files.
    page = [500 * _DAY, 510 * _DAY]

    assert plan_split(shard, page, 600 * _DAY) == []


def test_pages_in_no_order_do_not_split() -> None:
    """When Drive ignores orderBy, a page spans the whole range. The shard
    then lists serially: slower, with no file lost."""
    shard = _shard(0, 1000 * _DAY)
    page = [1 * _DAY, 999 * _DAY, 400 * _DAY]

    assert plan_split(shard, page, 999 * _DAY) == []


def test_a_dense_new_end_raises_the_estimate() -> None:
    shard = _shard(0, 1000 * _DAY)
    # 40 files by the old end alone, which is under the split threshold.
    page = [0, 50 * _DAY]

    assert plan_split(shard, page, 1000 * _DAY - 1) == []
    # The page of newest files holds 1000 files in one day.
    ranges = plan_split(shard, page, 1000 * _DAY - 1, newest_density=1000 / _DAY)
    assert len(ranges) > 1
    _assert_covers(ranges, shard.t0, shard.t1)


def test_the_pages_a_shard_kept_raise_a_sparse_page_estimate() -> None:
    """Bulk uploads 2 s apart: a page between two uploads looks sparse. The
    pages the shard kept show the true density."""
    shard = _shard(0, 1000 * _DAY)
    # 10 files over 2 s, and 60 s of range left: 300 files.
    page = [10_000 + i * 200 for i in range(10)]
    assert plan_split(shard, page, 70_000) == []

    # The shard kept 30,000 files over the 10 s before the page.
    shard.kept_since_ms = 0
    shard.frontier_ms = 10_000
    shard.kept_files = 30_000
    ranges = plan_split(shard, page, 70_000)
    assert len(ranges) > 1
    _assert_covers(ranges, shard.t0, shard.t1)


def test_a_wrong_newest_time_still_covers_the_shard() -> None:
    shard = _shard(10 * _DAY, 1000 * _DAY)
    page = [500 * _DAY + i for i in range(1000)]

    # Older than the page, and newer than the shard.
    for newest in (1 * _DAY, 5000 * _DAY):
        ranges = plan_split(shard, page, newest)
        if ranges:
            _assert_covers(ranges, shard.t0, shard.t1)


@pytest.mark.parametrize("page", [[], [5]])
def test_a_page_with_one_file_does_not_split(page: list[int]) -> None:
    assert plan_split(_shard(0, 1000 * _DAY), page, 900 * _DAY) == []


def test_window_includes_its_end() -> None:
    t0, t1 = window_ms(0, 1700000000.5)
    assert t0 == 0
    assert t1 == 1700000000500 + 1


def test_a_later_window_end_adds_a_shard_for_each_started_partition() -> None:
    user = ListingPartition(kind=ListingPartitionKind.MY_DRIVE, key="b@x.com")
    pending = ListingPartition(kind=ListingPartitionKind.MY_DRIVE, key="c@x.com")
    state = DriveListingState(
        window_t0=0,
        window_t1=100,
        pending_partitions=[pending],
        started_partitions=[(_DRIVE, "a@x.com", True), (user, "b@x.com", True)],
        next_shard_id=7,
        docs_by_type={DocumentTypeLabel.PDF: 4},
    )

    extend_window(state, 100)
    assert state.shards == {}

    extend_window(state, 250)

    assert state.window_t1 == 250
    assert sorted(state.shards) == [7, 8]
    assert {(s.partition, s.principal, s.t0, s.t1) for s in state.shards.values()} == {
        (_DRIVE, "a@x.com", 100, 250),
        (user, "b@x.com", 100, 250),
    }
    # The state still reads back from JSON.
    assert DriveListingState.model_validate_json(state.model_dump_json()) == state


_OWNER_A = ListingPartition(kind=ListingPartitionKind.MY_DRIVE, key="a@x.com")
_SHARED_WITH_A = ListingPartition(
    kind=ListingPartitionKind.SHARED_WITH_USER, key="a@x.com"
)
_WINDOW_T0 = 10 * _DAY
_WINDOW_T1 = 20 * _DAY


def _lister(admitted: list[str]) -> parallel_listing.ParallelDriveLister:
    """A lister of the window [_WINDOW_T0, _WINDOW_T1) where the My Drive of
    b@x.com has begun. ``admit_file`` records each dedup claim."""
    checkpoint = GoogleDriveCheckpoint(
        retrieved_folder_and_drive_ids=set(),
        completion_stage=DriveRetrievalStage.START,
        completion_map=ThreadSafeDict(),
        has_more=True,
        listing=DriveListingState(
            window_t0=_WINDOW_T0, window_t1=_WINDOW_T1, listed_owners={"b@x.com"}
        ),
    )

    def admit_file(file: GoogleDriveFileType, _exact: bool) -> bool:
        admitted.append(file["id"])
        return True

    return parallel_listing.ParallelDriveLister(
        ops=cast(GoogleDriveSourceOperations, None),
        checkpoint=checkpoint,
        field_type=DriveFileFieldType.STANDARD,
        requested_shared_drive_ids=(),
        choose_drive_principal=lambda _drive, _busy: (None, False),
        check_impersonation=lambda _email: (True, []),
        impersonation_failed=lambda _email, _error: [],
        listing_denied=lambda _partition, _email, _error: [],
        admit_file=admit_file,
    )


def _shortcut_target(file_id: str, owner: str, modified_ms: int) -> GoogleDriveFileType:
    stamp = datetime.fromtimestamp(modified_ms / 1000, tz=timezone.utc)
    return {
        "id": file_id,
        "owners": [{"emailAddress": owner}],
        "modifiedTime": stamp.isoformat(),
        RESOLVED_FROM_SHORTCUT_KEY: "shortcut",
    }


@pytest.mark.parametrize("partition", [_OWNER_A, _SHARED_WITH_A])
def test_a_shortcut_target_older_than_the_window_is_emitted(
    partition: ListingPartition,
) -> None:
    """The target's owner is listed, but only for files changed in the
    window. A target that changed before it comes only through the
    shortcut."""
    admitted: list[str] = []
    lister = _lister(admitted)
    shard = ListingShard(
        id=1, partition=partition, principal="a@x.com", t0=_WINDOW_T0, t1=_WINDOW_T1
    )

    old = _shortcut_target("old", "b@x.com", _WINDOW_T0 - _DAY)
    recent = _shortcut_target("recent", "b@x.com", _WINDOW_T0 + _DAY)

    assert lister._admit(shard, old)
    # The owner's listing returns this one.
    assert not lister._admit(shard, recent)
    assert admitted == ["old"]


def test_a_shortcut_to_an_own_old_file_is_emitted() -> None:
    admitted: list[str] = []
    lister = _lister(admitted)
    shard = ListingShard(
        id=1,
        partition=_OWNER_A,
        principal="a@x.com",
        t0=_WINDOW_T0,
        t1=_WINDOW_T1,
        exact=True,
    )

    old = _shortcut_target("old", "a@x.com", _WINDOW_T0 - _DAY)
    recent = _shortcut_target("recent", "a@x.com", _WINDOW_T0 + _DAY)

    assert lister._admit(shard, old)
    assert not lister._admit(shard, recent)
    assert admitted == ["old"]
