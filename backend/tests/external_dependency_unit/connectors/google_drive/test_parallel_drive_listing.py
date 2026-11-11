"""The parallel sharded Drive listing against the mock Google Drive server.

The listing must give the full corpus with no gaps and no duplicates when
pages come back in any order, when calls fail at random, and when Drive
answers with a burst of 429s. It must not make many more list calls than a
serial listing."""

import time
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
    """Pages of 10 files, so 2000 files are 200 pages."""
    monkeypatch.setattr(parallel_listing, "LISTING_PAGE_SIZE", _PAGE_SIZE)
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
    monkeypatch.setattr(parallel_listing, "MIN_PAGES_TO_SPLIT", 10**9)
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
