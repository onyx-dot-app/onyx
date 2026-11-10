"""The parallel sharded Drive listing against the mock Google Drive server.

The listing must give the full corpus with no gaps and no duplicates when
pages come back in any order, when calls fail at random, and when Drive
answers with a burst of 429s. It must not make many more list calls than a
serial listing."""

import pytest

from onyx.connectors.google_drive import parallel_listing
from onyx.connectors.google_drive.models import ListingPartitionKind
from onyx.connectors.google_drive.parallel_listing import drive_document_type
from onyx.utils import threadpool_concurrency
from tests.external_dependency_unit.connectors.google_drive.conftest import MockDrive
from tests.external_dependency_unit.connectors.google_drive.test_checkpointed_slim_listing import (
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
