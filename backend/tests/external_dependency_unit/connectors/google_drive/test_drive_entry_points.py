"""Every Drive entry point lists through the shard engine for a service
account with no requested folders. For the same corpus each one must give
the same files, with no gaps and no duplicates, across resumes that send the
checkpoint through JSON."""

import threading
import time
from collections import Counter
from collections.abc import Collection

import pytest

from onyx.connectors.google_drive import parallel_listing
from onyx.connectors.google_drive.connector import (
    GoogleDriveConnector,
    UnreachableTargetsError,
)
from onyx.connectors.google_drive.models import GoogleDriveCheckpoint, ListingShard
from onyx.connectors.google_drive.source_operations import GoogleDriveHttpError
from onyx.connectors.models import (
    ConnectorFailure,
    Document,
    HierarchyNode,
    SlimDocument,
)
from tests.external_dependency_unit.connectors.google_drive.conftest import MockDrive
from tests.external_dependency_unit.connectors.google_drive.test_checkpointed_slim_listing import (
    _file_id,
    list_with_resume,
)

_PAGE_SIZE = 3
_INLINE_BUDGET = 7
_MAX_CALLS = 1000


@pytest.fixture
def small_calls(monkeypatch: pytest.MonkeyPatch) -> None:
    """Small pages and budgets, so the small corpus needs many calls."""
    monkeypatch.setattr(parallel_listing, "LISTING_PAGE_SIZE", _PAGE_SIZE)
    monkeypatch.setattr(parallel_listing, "CALL_BUDGET_FILES", 10)
    monkeypatch.setattr(parallel_listing, "INLINE_CALL_BUDGET_FILES", _INLINE_BUDGET)


def _discard_raw_file(file: object, content_type: str) -> str:  # noqa: ARG001
    return "staged"


class _InlineRun:
    def __init__(self) -> None:
        self.document_ids: list[str] = []
        self.documents_per_call: list[int] = []
        self.failures: list[ConnectorFailure] = []
        self.final: GoogleDriveCheckpoint | None = None


def _index_inline(
    connector: GoogleDriveConnector,
    checkpoint: GoogleDriveCheckpoint | None = None,
) -> _InlineRun:
    """Runs load_from_checkpoint to its end, as docfetching does with no
    conversion stage."""
    connector.set_raw_file_callback(_discard_raw_file)
    run = _InlineRun()
    end = time.time()
    checkpoint = checkpoint or connector.build_dummy_checkpoint()
    for _ in range(_MAX_CALLS):
        output = connector.load_from_checkpoint(0, end, checkpoint)
        documents = 0
        while True:
            try:
                item = next(output)
            except StopIteration as stop:
                checkpoint = connector.validate_checkpoint_json(
                    stop.value.model_dump_json()
                )
                break
            if isinstance(item, Document):
                documents += 1
                run.document_ids.append(item.id)
            elif isinstance(item, ConnectorFailure):
                run.failures.append(item)
        run.documents_per_call.append(documents)
        if not checkpoint.has_more:
            run.final = checkpoint
            return run
    raise AssertionError("The inline listing did not finish")


def _slim_ids(batches: object) -> list[str]:
    return [
        doc.id
        for batch in batches  # ty: ignore[not-iterable]
        for doc in batch
        if isinstance(doc, SlimDocument) and not isinstance(doc, HierarchyNode)
    ]


def _perm_sync_with_stops(connector: GoogleDriveConnector) -> tuple[list[str], int]:
    """Permission sync that stops after each saved checkpoint and resumes from
    its JSON, as a stopped sync task resumes from FileStoreDocSyncCheckpointer.
    Returns the ids and the number of runs."""

    class _Stop(Exception):
        pass

    saved: list[str] = []
    ids: list[str] = []
    end = time.time()
    for runs in range(1, _MAX_CALLS):
        checkpoint = connector.validate_checkpoint_json(saved[-1]) if saved else None

        def save(drive_checkpoint: GoogleDriveCheckpoint) -> None:
            saved.append(drive_checkpoint.model_dump_json())
            raise _Stop()

        try:
            for batch in connector.retrieve_all_slim_docs_perm_sync(
                start=0, end=end, checkpoint=checkpoint, on_checkpoint=save
            ):
                ids.extend(_slim_ids([batch]))
        except _Stop:
            continue
        return ids, runs
    raise AssertionError("Permission sync did not finish")


# Text extraction reads settings from Postgres.
@pytest.mark.usefixtures("small_calls", "db_session", "tenant_context")
def test_every_entry_point_lists_the_same_files(mock_drive: MockDrive) -> None:
    expected_files = mock_drive.content_file_ids()

    inline = _index_inline(mock_drive.build_connector())
    stubs = list_with_resume(mock_drive.build_connector())
    pruning = _slim_ids(mock_drive.build_connector().retrieve_all_slim_docs())
    perm_sync, perm_sync_runs = _perm_sync_with_stops(mock_drive.build_connector())

    assert inline.failures == []
    assert stubs.failures == []
    # Each one took many calls, so each resumed from a JSON checkpoint.
    assert len(inline.documents_per_call) > 1
    assert stubs.calls > 1
    assert perm_sync_runs > 1
    listings = {
        "inline": inline.document_ids,
        "stubs": [stub.id for stub in stubs.stubs],
        "pruning": pruning,
        "permission sync": perm_sync,
    }
    for name, ids in listings.items():
        duplicates = [doc_id for doc_id, n in Counter(ids).items() if n > 1]
        assert not duplicates, f"{name}: {len(duplicates)} duplicates"
        assert {_file_id(doc_id) for doc_id in ids} == expected_files, name

    # The count of the listing is the count of what it yielded.
    assert inline.final is not None and inline.final.listing is not None
    assert inline.final.listing.total_docs == len(inline.document_ids)
    stub_state = stubs.checkpoints[-1].listing
    assert stub_state is not None
    assert stub_state.total_docs == len(stubs.stubs)


@pytest.mark.usefixtures("small_calls", "db_session", "tenant_context")
def test_inline_call_converts_at_most_its_budget(mock_drive: MockDrive) -> None:
    run = _index_inline(mock_drive.build_connector())

    assert run.failures == []
    assert max(run.documents_per_call) <= _INLINE_BUDGET
    # The budget, not the page, ends most calls.
    assert max(run.documents_per_call) > _PAGE_SIZE


@pytest.mark.usefixtures("small_calls")
def test_the_count_skips_files_that_indexing_skips(mock_drive: MockDrive) -> None:
    full = list_with_resume(mock_drive.build_connector())
    sizes = sorted(s.size_bytes for s in full.stubs if s.size_bytes is not None)
    threshold = sizes[len(sizes) // 2]

    connector = mock_drive.build_connector()
    connector.size_threshold = threshold
    filtered = list_with_resume(connector)

    assert len(filtered.stubs) < len(full.stubs)
    state = filtered.checkpoints[-1].listing
    assert state is not None
    assert state.total_docs == len(filtered.stubs)


def test_pruning_refuses_when_a_requested_drive_has_no_lister(
    mock_drive: MockDrive, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Pruning deletes what its listing lacks. A requested drive that no user
    can list must fail the prune, not empty the drive. Permission sync only
    updates what it lists, so it goes on."""
    drive_ids = mock_drive.client.get("/_mock/corpus/summary").json()[
        "shared_drive_ids"
    ]
    blocked = drive_ids[0]
    choose = GoogleDriveConnector._choose_drive_principal

    def nobody_for_blocked(
        self: GoogleDriveConnector,
        drive_id: str,
        checkpoint: GoogleDriveCheckpoint,
        busy: Collection[str] = (),
    ) -> tuple[str | None, bool]:
        if drive_id == blocked:
            return None, False
        return choose(self, drive_id, checkpoint, busy)

    monkeypatch.setattr(
        GoogleDriveConnector, "_choose_drive_principal", nobody_for_blocked
    )
    urls = ",".join(
        f"https://drive.google.com/drive/folders/{drive_id}" for drive_id in drive_ids
    )

    connector = mock_drive.build_connector(
        include_shared_drives=False,
        include_my_drives=False,
        include_files_shared_with_me=False,
        shared_drive_urls=urls,
    )
    with pytest.raises(UnreachableTargetsError, match=blocked):
        list(connector.retrieve_all_slim_docs())

    connector = mock_drive.build_connector(
        include_shared_drives=False,
        include_my_drives=False,
        include_files_shared_with_me=False,
        shared_drive_urls=urls,
    )
    assert _slim_ids(connector.retrieve_all_slim_docs_perm_sync(start=0))


@pytest.mark.usefixtures("small_calls")
def test_a_failed_page_fails_the_prune(
    mock_drive: MockDrive, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A partition whose page call fails must fail the prune. A partial
    listing would read as deleted files."""
    fetch_page = parallel_listing.ParallelDriveLister._fetch_page
    calls = 0

    def failing_fetch_page(
        self: parallel_listing.ParallelDriveLister, shard: ListingShard
    ) -> object:
        nonlocal calls
        calls += 1
        if calls == 5:
            raise GoogleDriveHttpError(
                status_code=500,
                reasons=("backendError",),
                access_denied=False,
                message="backend error",
            )
        return fetch_page(self, shard)

    monkeypatch.setattr(
        parallel_listing.ParallelDriveLister, "_fetch_page", failing_fetch_page
    )

    with pytest.raises(GoogleDriveHttpError):
        list(mock_drive.build_connector().retrieve_all_slim_docs())


def test_pruning_lists_files_edited_during_the_listing(
    own_mock_drive: MockDrive, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The shard engine lists up to the time the listing started. A file
    edited during the listing moves past that end. Pruning must still list
    it, or it would delete the file's document."""
    monkeypatch.setattr(parallel_listing, "LISTING_PAGE_SIZE", _PAGE_SIZE)
    mock_drive = own_mock_drive
    expected = mock_drive.content_file_ids()
    fetch_page = parallel_listing.ParallelDriveLister._fetch_page
    lock = threading.Lock()
    edited: list[str] = []

    def edit_during_listing(
        self: parallel_listing.ParallelDriveLister, shard: ListingShard
    ) -> object:
        # Before the first page, so no page token spans the edit.
        with lock:
            if not edited:
                # The mock gives the edit the current time, after the window
                # end.
                time.sleep(0.01)
                edited.extend(
                    mock_drive.client.post(
                        "/_mock/corpus/touch", json={"count": 5}
                    ).json()["file_ids"]
                )
        return fetch_page(self, shard)

    monkeypatch.setattr(
        parallel_listing.ParallelDriveLister, "_fetch_page", edit_during_listing
    )

    pruning = _slim_ids(mock_drive.build_connector().retrieve_all_slim_docs())

    assert edited
    assert {_file_id(doc_id) for doc_id in pruning} == expected
