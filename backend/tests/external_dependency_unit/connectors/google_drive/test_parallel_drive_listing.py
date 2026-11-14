"""The parallel sharded Drive listing against the mock Google Drive server.

The listing must give the full corpus with no gaps and no duplicates when
pages come back in any order, when calls fail at random, and when Drive
answers with a burst of 429s. It must not make many more list calls than a
serial listing."""

import threading
import time
from datetime import datetime
from typing import Any

import pytest

from onyx.connectors.google_drive import parallel_listing
from onyx.connectors.google_drive.file_retrieval import owner_email
from onyx.connectors.google_drive.models import (
    GoogleDriveCheckpoint,
    GoogleDriveFileType,
    ListingPartitionKind,
    ListingShard,
)
from onyx.connectors.google_drive.parallel_listing import drive_document_type
from onyx.connectors.google_drive.source_operations import (
    GoogleDriveHttpError,
    GoogleDriveRefreshError,
)
from onyx.connectors.models import SlimDocumentStub
from onyx.utils import threadpool_concurrency
from tests.external_dependency_unit.connectors.google_drive.conftest import MockDrive
from tests.external_dependency_unit.connectors.google_drive.test_checkpointed_slim_listing import (
    _file_id,
    _Listing,
    list_with_resume,
)

# One large shared drive, so its listing splits into shards.
_SHARDED_CORPUS = {
    "num_users": 3,
    "num_groups": 1,
    "num_shared_drives": 2,
    "files_per_shared_drive": 2000,
    "files_per_user": 30,
    "folders_per_container": 5,
    "shortcut_fraction": 0.02,
}
_PAGE_SIZE = 10


@pytest.fixture
def small_pages(monkeypatch: pytest.MonkeyPatch) -> None:
    """Pages of 10 files, so 2000 files are 200 pages. The split thresholds
    shrink with the pages."""
    monkeypatch.setattr(parallel_listing, "LISTING_PAGE_SIZE", _PAGE_SIZE)
    monkeypatch.setattr(parallel_listing, "LEAF_TARGET_FILES", 24 * _PAGE_SIZE)
    monkeypatch.setattr(parallel_listing, "MIN_FILES_TO_SPLIT", 48 * _PAGE_SIZE)
    monkeypatch.setattr(parallel_listing, "MIN_FILES_TO_PROBE", 24 * _PAGE_SIZE)
    monkeypatch.setattr(parallel_listing, "CALL_BUDGET_FILES", 1500)


def _assert_full_corpus(listing: _Listing, expected: set[str]) -> None:
    assert len(listing.file_ids) == len(set(listing.file_ids)), "duplicate stubs"
    missing = expected - set(listing.file_ids)
    assert not missing, f"{len(missing)} files were not listed"
    assert set(listing.file_ids) == expected


def _max_shards_of_one_drive(listing: _Listing) -> int:
    most = 0
    for checkpoint in listing.checkpoints:
        state = checkpoint.listing
        assert state is not None
        per_drive: dict[str, int] = {}
        for shard in state.shards.values():
            if shard.partition.kind is ListingPartitionKind.SHARED_DRIVE:
                key = shard.partition.key
                per_drive[key] = per_drive.get(key, 0) + 1
        most = max(most, max(per_drive.values(), default=0))
    return most


@pytest.mark.usefixtures("small_pages")
def test_sharded_listing_resumes_to_the_full_corpus(own_mock_drive: MockDrive) -> None:
    own_mock_drive.set_corpus(_SHARDED_CORPUS)
    expected = own_mock_drive.content_file_ids()

    listing = list_with_resume(own_mock_drive.build_connector())

    assert listing.failures == []
    assert listing.calls > 1
    _assert_full_corpus(listing, expected)
    # The large drives did split, and the checkpoint held open shards.
    assert _max_shards_of_one_drive(listing) > 1

    # The running count is the count of the stubs, by type.
    final = listing.checkpoints[-1].listing
    assert final is not None
    assert final.is_done
    assert final.total_docs == len(listing.stubs)
    by_type: dict[str, int] = {}
    for stub in listing.stubs:
        label = drive_document_type(stub.mime_type or "").value
        by_type[label] = by_type.get(label, 0) + 1
    assert {k.value: v for k, v in final.docs_by_type.items()} == by_type
    assert sum(final.bytes_by_type.values()) == sum(
        stub.size_bytes or 0 for stub in listing.stubs
    )


@pytest.mark.usefixtures("small_pages")
def test_listing_does_not_depend_on_page_order_or_on_clean_calls(
    own_mock_drive: MockDrive, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Drive ignores orderBy, answers with random delays, and fails 2% of the
    requests. A list page retries. A failed folder read fails its connector
    call, which then runs again from its checkpoint. The listing is still
    exact."""
    monkeypatch.setattr(parallel_listing, "CALL_BUDGET_FILES", 300)
    own_mock_drive.set_corpus(_SHARDED_CORPUS)
    expected = own_mock_drive.content_file_ids()
    own_mock_drive.patch_config(
        {
            "faults": {"ignore_order_by": True, "server_error_rate": 0.02},
            "latency": {
                "enabled": True,
                "token_ms": 1,
                "metadata_ms": 2,
                "list_ms": 10,
                "jitter": 1.0,
            },
        }
    )

    listing = list_with_resume(
        own_mock_drive.build_connector(), retry_failed_calls=True
    )

    assert listing.failures == []
    assert listing.calls > 1
    assert own_mock_drive.stats()["statuses"].get("500", 0) > 0
    _assert_full_corpus(listing, expected)


@pytest.mark.usefixtures("small_pages")
def test_a_burst_of_429s_cuts_the_pool_limit_and_loses_nothing(
    own_mock_drive: MockDrive, monkeypatch: pytest.MonkeyPatch
) -> None:
    own_mock_drive.set_corpus(_SHARDED_CORPUS)
    expected = own_mock_drive.content_file_ids()
    # Hold a cut for the rest of the call, so the checkpoint shows it.
    monkeypatch.setattr(threadpool_concurrency, "ADAPTIVE_COOLDOWN_SECONDS", 600.0)
    monkeypatch.setattr(parallel_listing, "CALL_BUDGET_FILES", 300)
    initial_limit = threadpool_concurrency.ADAPTIVE_INITIAL_WORKERS
    seen_limits: list[int] = []

    def after_call(listing: _Listing) -> None:
        state = listing.checkpoints[-1].listing
        assert state is not None and state.concurrency_limit is not None
        seen_limits.append(state.concurrency_limit)
        if listing.calls == 1:
            # The burst: the project quota allows 10 list calls each 2 s.
            own_mock_drive.patch_config(
                {
                    "quota": {
                        "window_seconds": 2,
                        "project_units_per_minute": 30_000,
                        "retry_after_seconds": 1,
                    }
                }
            )
        elif listing.calls == 2:
            own_mock_drive.patch_config(
                {"quota": {"window_seconds": 60, "project_units_per_minute": 1_000_000}}
            )

    listing = list_with_resume(own_mock_drive.build_connector(), after_call=after_call)

    assert listing.failures == []
    assert own_mock_drive.stats()["rate_limited"] > 0
    # The first call saw no pushback. The call in the burst cut the limit, and
    # the next call started from the cut limit.
    assert seen_limits[0] >= initial_limit
    assert seen_limits[1] < seen_limits[0]
    _assert_full_corpus(listing, expected)


@pytest.mark.usefixtures("small_pages")
def test_parallel_listing_adds_few_list_calls(
    own_mock_drive: MockDrive, monkeypatch: pytest.MonkeyPatch
) -> None:
    own_mock_drive.set_corpus(_SHARDED_CORPUS)
    expected = own_mock_drive.content_file_ids()

    own_mock_drive.reset_stats()
    parallel = list_with_resume(own_mock_drive.build_connector())
    parallel_calls = own_mock_drive.list_calls()
    _assert_full_corpus(parallel, expected)
    assert _max_shards_of_one_drive(parallel) > 1

    # The same listing with no split: each partition is one serial shard.
    monkeypatch.setattr(parallel_listing, "MIN_FILES_TO_SPLIT", 10**9)
    own_mock_drive.reset_stats()
    serial = list_with_resume(own_mock_drive.build_connector())
    serial_calls = own_mock_drive.list_calls()
    _assert_full_corpus(serial, expected)
    assert _max_shards_of_one_drive(serial) <= 1

    assert serial_calls > 400
    extra = (parallel_calls - serial_calls) / serial_calls
    assert extra <= 0.05, (
        f"{parallel_calls} list calls against {serial_calls} serial: {extra:.1%} more"
    )


@pytest.mark.usefixtures("small_pages")
def test_a_failed_call_stops_its_listing_threads(
    own_mock_drive: MockDrive, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The caller fails while pages are in flight. The call must stop its
    listing threads before it raises, and not leave them to list on."""
    own_mock_drive.set_corpus(_SHARDED_CORPUS)
    own_mock_drive.patch_config(
        {"latency": {"enabled": True, "list_ms": 20, "metadata_ms": 1, "token_ms": 1}}
    )
    connector = own_mock_drive.build_connector()

    def fail(*_args: object, **_kwargs: object) -> list[object]:
        raise RuntimeError("the folder walk failed")

    monkeypatch.setattr(connector, "_listed_folder_nodes", fail)
    generator = connector.retrieve_slim_docs_from_checkpoint(
        0, time.time(), connector.build_dummy_checkpoint()
    )
    # The error keeps its traceback, and so the call's frames, alive. The
    # threads must stop even then.
    with pytest.raises(RuntimeError, match="the folder walk failed") as error:
        list(generator)

    requests_at_failure = own_mock_drive.stats()["requests"]
    time.sleep(1.0)
    assert own_mock_drive.stats()["requests"] == requests_at_failure
    assert error.value is not None
    # The call failed long before the listing was complete.
    assert own_mock_drive.list_calls() < 200


def test_shared_with_user_listing_skips_the_users_own_files(
    own_mock_drive: MockDrive, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The user's My Drive partition lists the user's own files, so the
    shared-with-user partition must not list them again."""
    own_mock_drive.set_corpus(_SHARDED_CORPUS)
    expected = own_mock_drive.content_file_ids()

    shared_with_files = 0
    own_files: list[str] = []
    fetch_page = parallel_listing.ParallelDriveLister._fetch_page

    def recording_fetch_page(
        self: parallel_listing.ParallelDriveLister, shard: ListingShard
    ) -> tuple[list[GoogleDriveFileType], str | None]:
        nonlocal shared_with_files
        files, next_token = fetch_page(self, shard)
        if shard.partition.kind is ListingPartitionKind.SHARED_WITH_USER:
            shared_with_files += len(files)
            own_files.extend(
                file["id"]
                for file in files
                if owner_email(file) == shard.principal.lower()
            )
        return files, next_token

    monkeypatch.setattr(
        parallel_listing.ParallelDriveLister, "_fetch_page", recording_fetch_page
    )
    listing = list_with_resume(own_mock_drive.build_connector())

    _assert_full_corpus(listing, expected)
    assert shared_with_files > 0
    assert not own_files, f"{len(own_files)} own files in shared-with listings"


@pytest.mark.usefixtures("small_pages")
def test_a_split_refused_by_the_shard_cap_runs_on_a_later_page(
    own_mock_drive: MockDrive, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A shard that cannot split only because the open shard cap is reached
    must split on a later page, when other shards have closed."""
    monkeypatch.setattr(parallel_listing, "MAX_OPEN_SHARDS", 4)
    own_mock_drive.set_corpus(_SHARDED_CORPUS)
    expected = own_mock_drive.content_file_ids()

    cap_refused: set[int] = set()
    split_after_refusal: set[int] = set()
    try_split = parallel_listing.ParallelDriveLister._try_split

    def recording_try_split(
        self: parallel_listing.ParallelDriveLister,
        shard: ListingShard,
        files: list[GoogleDriveFileType],
    ) -> object:
        with self._lock:
            at_cap = len(self._state.shards) >= parallel_listing.MAX_OPEN_SHARDS
        result = try_split(self, shard, files)
        if isinstance(result, list):
            if shard.id in cap_refused and result:
                split_after_refusal.add(shard.id)
        elif at_cap:
            cap_refused.add(shard.id)
        return result

    monkeypatch.setattr(
        parallel_listing.ParallelDriveLister, "_try_split", recording_try_split
    )
    listing = list_with_resume(own_mock_drive.build_connector())

    _assert_full_corpus(listing, expected)
    assert cap_refused, "no split was refused by the shard cap"
    assert split_after_refusal, "no shard split after the cap refused it"


@pytest.mark.usefixtures("small_pages")
def test_a_shard_splits_again_after_a_bulk_upload_burst(
    own_mock_drive: MockDrive, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A bulk upload gives more files one modifiedTime than a shard keeps ids
    for. A shard that lists through that burst unsplit must split on a later
    page that starts after the burst."""
    monkeypatch.setattr(parallel_listing, "MAX_FRONTIER_IDS", 10)
    monkeypatch.setattr(parallel_listing, "LEAF_TARGET_FILES", 4 * _PAGE_SIZE)
    monkeypatch.setattr(parallel_listing, "MIN_FILES_TO_SPLIT", 8 * _PAGE_SIZE)
    own_mock_drive.set_corpus(_SHARDED_CORPUS)
    burst_ids = own_mock_drive.client.post(
        "/_mock/corpus/touch", json={"count": 600}
    ).json()["file_ids"]
    burst = own_mock_drive.client.get(f"/_mock/corpus/files/{burst_ids[0]}").json()
    # Drive gives modifiedTime to the millisecond.
    burst_ms = (
        datetime.fromisoformat(burst["file"]["modified_time"]).timestamp() * 1_000_000
    ) // 1000
    # Files over more than two seconds after the burst, so a shard past the
    # burst has a range wide enough to split.
    for _ in range(2):
        time.sleep(2.5)
        own_mock_drive.client.post(
            "/_mock/corpus/touch", json={"count": 400}
        ).raise_for_status()
    expected = own_mock_drive.content_file_ids()

    burst_files_seen: dict[int, int] = {}
    split_after_crowded_burst: set[int] = set()
    try_split = parallel_listing.ParallelDriveLister._try_split

    def hold_until_past_the_burst(
        self: parallel_listing.ParallelDriveLister,
        shard: ListingShard,
        files: list[GoogleDriveFileType],
    ) -> object:
        """Stands in for the shard cap until a page starts after the burst, as
        when the cap is reached early in a run and frees up late."""
        page_ms = [
            round(datetime.fromisoformat(str(file["modifiedTime"])).timestamp() * 1000)
            for file in files
            if file.get("modifiedTime")
        ]
        in_burst = sum(1 for ms in page_ms if ms == burst_ms)
        burst_files_seen[shard.id] = burst_files_seen.get(shard.id, 0) + in_burst
        if not page_ms or min(page_ms) <= burst_ms:
            return parallel_listing._SplitRefusal.SHARD_CAP
        result = try_split(self, shard, files)
        crowded = burst_files_seen[shard.id] > parallel_listing.MAX_FRONTIER_IDS
        if crowded and isinstance(result, list) and result:
            split_after_crowded_burst.add(shard.id)
        return result

    monkeypatch.setattr(
        parallel_listing.ParallelDriveLister, "_try_split", hold_until_past_the_burst
    )
    listing = list_with_resume(own_mock_drive.build_connector())

    _assert_full_corpus(listing, expected)
    assert max(burst_files_seen.values()) > parallel_listing.MAX_FRONTIER_IDS, (
        "no shard kept more burst files than it keeps ids for"
    )
    assert split_after_crowded_burst, "no shard split after a crowded burst"


@pytest.mark.usefixtures("small_pages")
def test_a_split_on_a_later_page_emits_each_file_once(
    own_mock_drive: MockDrive, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Many files share one modifiedTime, as files made in a burst do. A shard
    that splits on a later page starts its sub-ranges at that time. The files
    it already kept at that time must not come a second time."""
    own_mock_drive.set_corpus(_SHARDED_CORPUS)
    # Two bursts. The range after the first burst has files, so a shard in
    # the first burst has a reason to split.
    for _ in range(2):
        own_mock_drive.client.post(
            "/_mock/corpus/touch", json={"count": 1500}
        ).raise_for_status()
        time.sleep(2.5)
    expected = own_mock_drive.content_file_ids()

    late_splits_with_skips = 0
    try_split = parallel_listing.ParallelDriveLister._try_split

    def split_only_inside_the_burst(
        self: parallel_listing.ParallelDriveLister,
        shard: ListingShard,
        files: list[GoogleDriveFileType],
    ) -> object:
        """Stands in for the shard cap: refuses each split until the shard is
        on a later page whose files all have the burst's time."""
        nonlocal late_splits_with_skips
        times = {file.get("modifiedTime") for file in files}
        in_burst = len(times) == 1 and bool(shard.frontier_ids)
        if shard.page_token is None or not in_burst:
            if shard.skip_ids:
                # A sub-range of a split that this test let through.
                return try_split(self, shard, files)
            return parallel_listing._SplitRefusal.SHARD_CAP
        result = try_split(self, shard, files)
        if isinstance(result, list) and result:
            with self._lock:
                first_child = self._state.shards.get(result[0])
                if first_child is not None and first_child.skip_ids:
                    late_splits_with_skips += 1
        return result

    monkeypatch.setattr(
        parallel_listing.ParallelDriveLister, "_try_split", split_only_inside_the_burst
    )
    listing = list_with_resume(own_mock_drive.build_connector())

    assert late_splits_with_skips > 0, "no later-page split met files it had kept"
    _assert_full_corpus(listing, expected)


@pytest.mark.usefixtures("small_pages")
def test_a_nested_split_at_the_same_time_emits_each_file_once(
    own_mock_drive: MockDrive, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A sub-range that starts inside a burst skips the burst files its
    parent kept. If the sub-range splits again on a later page at that same
    time, its first sub-range must skip those files too."""
    # Narrow sub-ranges, so a sub-range can split again.
    monkeypatch.setattr(parallel_listing, "MIN_SHARD_MS", 1)
    own_mock_drive.set_corpus(_SHARDED_CORPUS)
    for _ in range(2):
        own_mock_drive.client.post(
            "/_mock/corpus/touch", json={"count": 1500}
        ).raise_for_status()
        time.sleep(2.5)
    expected = own_mock_drive.content_file_ids()

    nested_splits = 0
    try_split = parallel_listing.ParallelDriveLister._try_split

    def split_only_on_later_burst_pages(
        self: parallel_listing.ParallelDriveLister,
        shard: ListingShard,
        files: list[GoogleDriveFileType],
    ) -> object:
        """Stands in for the shard cap: refuses each split until the shard is
        on a later page whose files all have the burst's time."""
        nonlocal nested_splits
        times = {file.get("modifiedTime") for file in files}
        in_burst = len(times) == 1 and bool(shard.frontier_ids)
        if shard.page_token is None or not in_burst:
            return parallel_listing._SplitRefusal.SHARD_CAP
        page_ms = parallel_listing._modified_ms(files[0])
        result = try_split(self, shard, files)
        if shard.skip_ids and page_ms == shard.t0 and isinstance(result, list):
            nested_splits += bool(result)
        return result

    monkeypatch.setattr(
        parallel_listing.ParallelDriveLister,
        "_try_split",
        split_only_on_later_burst_pages,
    )
    listing = list_with_resume(own_mock_drive.build_connector())

    assert nested_splits > 0, "no sub-range split again at its own start"
    _assert_full_corpus(listing, expected)


@pytest.mark.usefixtures("small_pages")
def test_a_new_window_start_lists_every_file_again(
    own_mock_drive: MockDrive, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A checkpoint from a listing with another window start is of no use.
    The new listing must also drop the old one's dedup claims, or it drops
    the files that the old one claimed."""
    monkeypatch.setattr(parallel_listing, "CALL_BUDGET_FILES", 2500)
    own_mock_drive.set_corpus(_SHARDED_CORPUS)
    expected = own_mock_drive.content_file_ids()
    connector = own_mock_drive.build_connector()
    end = time.time()

    def one_call(
        start: float, checkpoint: GoogleDriveCheckpoint
    ) -> tuple[list[str], GoogleDriveCheckpoint]:
        generator = connector.retrieve_slim_docs_from_checkpoint(start, end, checkpoint)
        ids: list[str] = []
        while True:
            try:
                item = next(generator)
            except StopIteration as stop:
                return ids, connector.validate_checkpoint_json(
                    stop.value.model_dump_json()
                )
            if isinstance(item, SlimDocumentStub):
                ids.append(_file_id(item.id))

    _, checkpoint = one_call(0, connector.build_dummy_checkpoint())
    assert checkpoint.has_more
    # Stands in for the claims of the old listing: files that it reached by a
    # path with no exact partition.
    checkpoint.retrieved_drive_file_ids = set(expected)

    # The window start moves by one second: all files are still in the window.
    listed: list[str] = []
    while checkpoint.has_more:
        ids, checkpoint = one_call(1, checkpoint)
        listed.extend(ids)

    assert len(listed) == len(set(listed))
    assert set(listed) == expected


def _denied_page() -> GoogleDriveHttpError:
    return GoogleDriveHttpError(
        status_code=403,
        reasons=("insufficientFilePermissions",),
        access_denied=True,
        message="The user does not have sufficient permissions",
    )


@pytest.mark.parametrize("denied", [False, True], ids=["impersonation", "denied"])
def test_files_shared_by_an_owner_whose_my_drive_fails_are_still_listed(
    own_mock_drive: MockDrive, monkeypatch: pytest.MonkeyPatch, denied: bool
) -> None:
    """A shared-with-user listing drops a file whose owner's My Drive
    partition began, because that partition lists it. If that partition then
    fails, the file must still come from a shared-with-user listing. A page
    that Drive denies fails the partition too, with a reported failure."""
    own_mock_drive.set_corpus(_SHARDED_CORPUS)

    lock = threading.Lock()
    victim: list[str] = []
    last_shared_with_fetch = [0.0]
    owners_by_shared_file: dict[str, str] = {}
    fetch_page = parallel_listing.ParallelDriveLister._fetch_page

    def failing_fetch_page(
        self: parallel_listing.ParallelDriveLister, shard: ListingShard
    ) -> tuple[list[GoogleDriveFileType], str | None]:
        kind = shard.partition.kind
        if kind is ListingPartitionKind.MY_DRIVE:
            with lock:
                if not victim:
                    victim.append(shard.partition.key.lower())
                is_victim = victim[0] == shard.partition.key.lower()
            if is_victim:
                # Fail after the shared-with-user listings read their pages.
                deadline = time.monotonic() + 30
                while time.monotonic() < deadline:
                    with lock:
                        last = last_shared_with_fetch[0]
                    if last and time.monotonic() - last > 1.0:
                        break
                    time.sleep(0.05)
                if denied:
                    raise _denied_page()
                raise GoogleDriveRefreshError("the user can no longer be impersonated")
        files, next_token = fetch_page(self, shard)
        if kind is ListingPartitionKind.SHARED_WITH_USER:
            with lock:
                last_shared_with_fetch[0] = time.monotonic()
                for file in files:
                    owner = owner_email(file)
                    if owner and not file.get("driveId"):
                        owners_by_shared_file[file["id"]] = owner
        return files, next_token

    monkeypatch.setattr(
        parallel_listing.ParallelDriveLister, "_fetch_page", failing_fetch_page
    )
    listing = list_with_resume(own_mock_drive.build_connector())

    assert victim, "no My Drive partition ran"
    expected = own_mock_drive.content_file_ids()
    shared_by_victim = {
        file_id
        for file_id, owner in owners_by_shared_file.items()
        if owner == victim[0] and file_id in expected
    }
    assert shared_by_victim, "the corpus has no file that the failed owner shared"
    missing = shared_by_victim - set(listing.file_ids)
    assert not missing, (
        f"{len(missing)} of {len(shared_by_victim)} files that the failed owner "
        "shared were not listed"
    )
    if denied:
        assert listing.failures, "the denied listing was not reported"


def test_a_denied_page_fails_pruning(
    mock_drive: MockDrive, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Pruning deletes what the listing lacks. A page that Drive denies must
    fail the pruning listing, not end that partition as if it were empty."""
    fetch_page = parallel_listing.ParallelDriveLister._fetch_page

    def deny_one_my_drive(
        self: parallel_listing.ParallelDriveLister, shard: ListingShard
    ) -> tuple[list[GoogleDriveFileType], str | None]:
        if shard.partition.kind is ListingPartitionKind.MY_DRIVE:
            raise _denied_page()
        return fetch_page(self, shard)

    monkeypatch.setattr(
        parallel_listing.ParallelDriveLister, "_fetch_page", deny_one_my_drive
    )
    connector = mock_drive.build_connector()

    with pytest.raises(GoogleDriveHttpError):
        for _batch in connector.retrieve_all_slim_docs():
            pass


def _modified_ms(mock_drive: MockDrive, file_id: str) -> int:
    """The modifiedTime as Drive serves it: cut to the millisecond."""
    file = mock_drive.client.get(f"/_mock/corpus/files/{file_id}").json()["file"]
    stamp = datetime.fromisoformat(file["modified_time"])
    return int(stamp.timestamp()) * 1000 + stamp.microsecond // 1000


@pytest.mark.usefixtures("small_pages")
def test_a_sparse_page_does_not_stop_later_splits(
    own_mock_drive: MockDrive, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Bulk uploads 2 s apart. The first page holds the end of one burst and
    the start of the next, so its time span makes the range look sparse. A
    later page inside a burst shows the true density, and the shard must
    split then."""
    own_mock_drive.set_corpus(
        {
            "num_users": 2,
            "num_groups": 1,
            "num_shared_drives": 1,
            "files_per_shared_drive": 3000,
            "files_per_user": 0,
            "folders_per_container": 2,
            "shortcut_fraction": 0,
        }
    )
    # Small bursts first: a page of the oldest files then crosses a gap.
    touched: set[str] = set()
    for count in (6, 6, 150, 150, 150, 150, 150, 150):
        touched.update(
            own_mock_drive.client.post(
                "/_mock/corpus/touch", json={"count": count}
            ).json()["file_ids"]
        )
        time.sleep(2.0)
    # A later burst can move a file of an earlier one, so read the times now.
    times = {file_id: _modified_ms(own_mock_drive, file_id) for file_id in touched}
    per_burst: dict[int, int] = {}
    for ms in times.values():
        per_burst[ms] = per_burst.get(ms, 0) + 1
    bursts = sorted(per_burst)
    window_start_ms = next(ms for ms in bursts[:-1] if per_burst[ms] < _PAGE_SIZE)
    expected = {file_id for file_id, ms in times.items() if ms >= window_start_ms}

    drive_splits = 0
    try_split = parallel_listing.ParallelDriveLister._try_split

    def recording_try_split(
        self: parallel_listing.ParallelDriveLister,
        shard: ListingShard,
        files: list[GoogleDriveFileType],
    ) -> object:
        nonlocal drive_splits
        result = try_split(self, shard, files)
        if (
            isinstance(result, list)
            and result
            and shard.partition.kind is ListingPartitionKind.SHARED_DRIVE
        ):
            drive_splits += 1
        return result

    monkeypatch.setattr(
        parallel_listing.ParallelDriveLister, "_try_split", recording_try_split
    )
    listing = list_with_resume(
        own_mock_drive.build_connector(), start=window_start_ms / 1000
    )

    _assert_full_corpus(listing, expected)
    assert drive_splits > 0, "the shard never split after its sparse first page"


def test_folder_listing_replaces_the_per_file_ancestor_walk(
    own_mock_drive: MockDrive, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Folders come from folder-only listings. After the listing, only the
    parents that no listing returned are read, each one once."""
    own_mock_drive.set_corpus(_SHARDED_CORPUS)
    expected = own_mock_drive.content_file_ids()
    connector = own_mock_drive.build_connector()
    reads: list[str] = []
    read_folder = connector._get_folder_metadata

    def counting_read(folder_id: str, *args: Any, **kwargs: Any) -> Any:
        reads.append(folder_id)
        return read_folder(folder_id, *args, **kwargs)

    monkeypatch.setattr(connector, "_get_folder_metadata", counting_read)

    listing = list_with_resume(connector)

    assert listing.failures == []
    _assert_full_corpus(listing, expected)
    node_ids = {node.raw_node_id for node in listing.nodes}
    # Each node is yielded once, and its parent is a yielded node.
    assert len(node_ids) == len(listing.nodes)
    for node in listing.nodes:
        assert node.raw_parent_id is None or node.raw_parent_id in node_ids
    # Most nodes come from the folder listings, not from files.get.
    assert len(set(reads)) == len(reads)
    assert len(reads) < len(node_ids) // 2
