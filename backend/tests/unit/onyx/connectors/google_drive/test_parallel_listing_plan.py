"""The split plan and the window of the parallel Drive listing. A split must
cover the whole shard with no overlap, wherever the files are, because the
sub-ranges are the only record of what is still to list."""

from datetime import datetime, timezone
from typing import cast

import pytest

from onyx.connectors.google_drive import parallel_listing
from onyx.connectors.google_drive.file_retrieval import (
    RESOLVED_FROM_SHORTCUT_KEY,
    TARGET_MODIFIED_TIME_KEY,
    DriveFileFieldType,
)
from onyx.connectors.google_drive.models import (
    DriveListingState,
    GoogleDriveCheckpoint,
    ListingPartition,
    ListingPartitionKind,
    ListingShard,
    RetrievedDriveFile,
)
from onyx.connectors.google_drive.parallel_listing import (
    extend_window,
    plan_split,
    window_ms,
)
from onyx.connectors.google_drive.source_operations import (
    GoogleDriveSourceOperations,
)
from onyx.connectors.google_utils.shared_constants import GoogleDriveFileType
from onyx.connectors.models import DocumentTypeLabel

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
        plan_folder_target=lambda _folder, _covered: (
            parallel_listing.FolderTargetPlan()
        ),
    )


def _shortcut_target(file_id: str, owner: str, modified_ms: int) -> GoogleDriveFileType:
    """A target as ``resolve_file_or_shortcut`` returns it: modifiedTime is
    the shortcut's time, which is in the window, and the target's own time
    is under its own key."""
    stamp = datetime.fromtimestamp(modified_ms / 1000, tz=timezone.utc)
    shortcut_stamp = datetime.fromtimestamp((_WINDOW_T0 + _DAY) / 1000, tz=timezone.utc)
    return {
        "id": file_id,
        "owners": [{"emailAddress": owner}],
        "modifiedTime": shortcut_stamp.isoformat(),
        TARGET_MODIFIED_TIME_KEY: stamp.isoformat(),
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


_FOLDER = ListingPartition(kind=ListingPartitionKind.FOLDER_SUBTREE, key="folder_1")


@pytest.mark.parametrize(
    "partition, folder_id",
    [(_SHARED_WITH_A, None), (_FOLDER, "folder_1")],
)
def test_a_recovery_listing_keeps_the_targets_of_other_owners_shortcuts(
    monkeypatch: pytest.MonkeyPatch,
    partition: ListingPartition,
    folder_id: str | None,
) -> None:
    """The My Drive listing of b@x.com failed, so a shard lists the files of
    b@x.com again. A shortcut that c@x.com owns can point to a file of
    b@x.com: the query must return the shortcut, and the shard keeps the
    target and drops what other owners have."""
    admitted: list[str] = []
    lister = _lister(admitted)
    lister._state.listed_owners.clear()
    shard = ListingShard(
        id=1,
        partition=partition,
        principal="a@x.com",
        t0=_WINDOW_T0,
        t1=_WINDOW_T1,
        exact=False,
        owner_filter="b@x.com",
        folder_id=folder_id,
    )
    lister._state.shards[shard.id] = shard

    query = lister._query(shard, shard.t0, shard.t1)
    assert (
        "('b@x.com' in owners or mimeType = 'application/vnd.google-apps.shortcut')"
        in query
    )

    page: list[GoogleDriveFileType] = [
        {"id": "own", "owners": [{"emailAddress": "b@x.com"}]},
        {"id": "shortcut_to_b", "mimeType": "application/vnd.google-apps.shortcut"},
        {"id": "shortcut_to_c", "mimeType": "application/vnd.google-apps.shortcut"},
    ]
    targets: dict[str, GoogleDriveFileType] = {
        "shortcut_to_b": _shortcut_target("target_of_b", "b@x.com", _WINDOW_T0 - _DAY),
        "shortcut_to_c": _shortcut_target("target_of_c", "c@x.com", _WINDOW_T0 - _DAY),
    }
    monkeypatch.setattr(lister, "_fetch_page", lambda _shard: (page, None))
    monkeypatch.setattr(
        lister, "_resolve_file", lambda _email, file: targets.get(file["id"], file)
    )

    lister._list_one_page(shard)

    assert admitted == ["own", "target_of_b"]


def _folder_lister_covered_by_drive() -> parallel_listing.ParallelDriveLister:
    """A lister where no usable user can walk the requested folder, and a
    full listing of its shared drive covers it while that drive is listed."""
    lister = _lister([])
    state = lister._state
    state.listed_drive_ids.add(_DRIVE.key)
    state.pending_partitions.append(_FOLDER)
    lister._planning.add(_FOLDER)
    lister._plan_folder_target = lambda _folder, covered: (
        parallel_listing.FolderTargetPlan(
            covered_drive_id=_DRIVE.key if _DRIVE.key in covered else None
        )
    )
    return lister


def _fail_drive(lister: parallel_listing.ParallelDriveLister, list_again: bool) -> None:
    drive_shard = ListingShard(
        id=7, partition=_DRIVE, principal="a@x.com", t0=_WINDOW_T0, t1=_WINDOW_T1
    )
    lister._state.shards[drive_shard.id] = drive_shard
    lister._partition_failed(drive_shard, [], list_again=list_again)


@pytest.mark.parametrize("relisted", [True, False])
def test_a_folder_covered_by_a_failed_drive_listing_is_planned_again(
    relisted: bool,
) -> None:
    """No usable user can walk the requested folder, so the full listing of
    its shared drive is its only cover. When that listing fails, the folder
    is planned again. A new full listing of the drive covers it again.
    Without one, nothing covers the folder, so pruning must not run."""
    lister = _folder_lister_covered_by_drive()
    state = lister._state

    assert lister._plan_folder_subtree(_FOLDER) == []
    assert state.folders_covered_by_drive == {"folder_1": _DRIVE.key}
    assert lister._checkpoint.unreachable_target_ids == set()

    _fail_drive(lister, list_again=True)

    assert state.folders_covered_by_drive == {}
    assert lister._checkpoint.unreachable_target_ids == set()
    assert state.pending_partitions == [_DRIVE, _FOLDER]

    state.pending_partitions.remove(_DRIVE)
    if relisted:
        # Another organizer lists the drive in full.
        state.listed_drive_ids.add(_DRIVE.key)
    assert lister._plan_folder_subtree(_FOLDER) == []

    if relisted:
        assert state.folders_covered_by_drive == {"folder_1": _DRIVE.key}
        assert lister._checkpoint.unreachable_target_ids == set()
    else:
        assert state.folders_covered_by_drive == {}
        assert lister._checkpoint.unreachable_target_ids == {"folder_1"}


def test_a_folder_cover_that_fails_during_planning_is_not_recorded() -> None:
    """The drive listing fails while the folder's users are checked. The
    folder must not record that drive as its cover, or no failure would mark
    the folder unreachable. It is planned again with no cover."""
    lister = _folder_lister_covered_by_drive()
    state = lister._state
    lister._plan_folder_target = lambda _folder, covered: (
        parallel_listing.FolderTargetPlan(
            principals=["u@x.com"],
            covered_drive_id=_DRIVE.key if _DRIVE.key in covered else None,
        )
    )

    def check_impersonation(_email: str) -> tuple[bool, list[RetrievedDriveFile]]:
        _fail_drive(lister, list_again=False)
        return False, []

    lister._check_impersonation = check_impersonation

    assert lister._plan_folder_subtree(_FOLDER) == []

    assert state.folders_covered_by_drive == {}
    assert state.pending_partitions == [_FOLDER]

    lister._check_impersonation = lambda _email: (False, [])
    assert lister._plan_folder_subtree(_FOLDER) == []

    assert state.folders_covered_by_drive == {}
    assert lister._checkpoint.unreachable_target_ids == {"folder_1"}


_OWNER_B = ListingPartition(kind=ListingPartitionKind.MY_DRIVE, key="b@x.com")


@pytest.mark.parametrize("failed", [_OWNER_B, _DRIVE])
def test_a_shortcut_target_that_a_failed_listing_covered_is_listed_again(
    monkeypatch: pytest.MonkeyPatch, failed: ListingPartition
) -> None:
    """A shortcut in the My Drive of a@x.com points to a file that the
    listing of ``failed`` covers, so a@x.com's listing drops the target.
    When that listing fails, a@x.com's shortcuts are listed again, and the
    target is kept."""
    admitted: list[str] = []
    lister = _lister(admitted)
    state = lister._state
    state.listed_drive_ids.add(_DRIVE.key)
    target = _shortcut_target("target", "b@x.com", _WINDOW_T0 + _DAY)
    if failed is _DRIVE:
        target["driveId"] = _DRIVE.key
        del target["owners"]
    state.started_partitions = [
        (_OWNER_A, "a@x.com", True),
        (failed, "b@x.com", True),
    ]
    own_shard = ListingShard(
        id=1, partition=_OWNER_A, principal="a@x.com", t0=_WINDOW_T0, t1=_WINDOW_T1
    )
    assert not lister._admit(own_shard, target)

    failed_shard = ListingShard(
        id=2, partition=failed, principal="b@x.com", t0=_WINDOW_T0, t1=_WINDOW_T1
    )
    state.shards[failed_shard.id] = failed_shard
    lister._partition_failed(failed_shard, [], list_again=False)

    [relist] = [
        shard
        for shard in state.shards.values()
        if shard.partition == _OWNER_A and shard.shortcuts_only
    ]
    query = lister._query(relist, relist.t0, relist.t1)
    assert "mimeType = 'application/vnd.google-apps.shortcut'" in query
    assert "'me' in owners" in query

    shortcut: GoogleDriveFileType = {
        "id": "shortcut",
        "mimeType": "application/vnd.google-apps.shortcut",
    }
    other = _shortcut_target("other", "c@x.com", _WINDOW_T0 + _DAY)
    other["driveId"] = "drive_2"
    targets = {"shortcut": target, "shortcut_to_other": other}
    monkeypatch.setattr(
        lister,
        "_fetch_page",
        lambda _shard: (
            [shortcut, {**shortcut, "id": "shortcut_to_other"}],
            None,
        ),
    )
    monkeypatch.setattr(
        lister, "_resolve_file", lambda _email, file: targets[file["id"]]
    )

    lister._list_one_page(relist)

    assert admitted == ["target"]
