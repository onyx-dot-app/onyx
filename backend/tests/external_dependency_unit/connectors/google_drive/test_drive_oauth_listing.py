"""An OAuth connector lists through the shard engine, with the OAuth user as
the only principal. For each include setting it must give the same files as
main's serial OAuth listing: corpora=allDrives with all three settings on,
else the user's own files, the files shared with the user and the shared
drives the user is a member of, as the settings select."""

import json
import time
from collections import Counter
from collections.abc import Iterator
from functools import cache
from typing import Any

import httpx
import pytest
from scripts.benchmark_google_drive_connector import start_mock_server

from onyx.connectors.google_drive import parallel_listing
from onyx.connectors.google_drive.connector import GoogleDriveConnector
from onyx.connectors.google_drive.models import (
    GoogleDriveCheckpoint,
    ListingPartitionKind,
    ListingShard,
)
from onyx.connectors.google_drive.source_operations import (
    DriveCorpus,
    GoogleDriveHttpError,
    GoogleDriveRefreshError,
)
from onyx.connectors.models import HierarchyNode, SlimDocumentStub
from tests.external_dependency_unit.connectors.google_drive.conftest import MockDrive
from tests.external_dependency_unit.connectors.google_drive.test_checkpointed_slim_listing import (
    _file_id,
    list_with_resume,
)
from tests.external_dependency_unit.connectors.google_drive.test_drive_entry_points import (
    _index_inline,
    _perm_sync_with_stops,
    _slim_ids,
)

_EMAIL = "user1@onyx-mock.test"
_MAX_CALLS = 1000
_OAUTH_CORPUS: dict[str, Any] = {
    "num_users": 4,
    "num_groups": 1,
    "num_shared_drives": 4,
    "files_per_shared_drive": 12,
    "files_per_user": 8,
    "folders_per_container": 3,
    # A shortcut target outside the user's corpus is not in the expected
    # sets that the mock gives.
    "shortcut_fraction": 0,
    "external_shares": {"owners": 2, "files": 20, "recipients": 3},
    # Only plain text: it converts without a file store or extraction service.
    "mime_weights": {
        "application/vnd.google-apps.document": 0,
        "application/vnd.google-apps.spreadsheet": 0,
        "application/vnd.google-apps.presentation": 0,
        "application/pdf": 0,
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document": 0,
        "text/markdown": 0,
        "text/plain": 1,
    },
}


@pytest.fixture(scope="module")
def mock_drive_url() -> Iterator[str]:
    """Replaces the shared fixture of conftest with an OAuth corpus."""
    process, url = start_mock_server(
        {"corpus": _OAUTH_CORPUS, "latency": {"enabled": False}}
    )
    try:
        yield url
    finally:
        process.terminate()
        process.wait(timeout=30)


@pytest.fixture
def small_calls(monkeypatch: pytest.MonkeyPatch) -> None:
    """Small pages and budgets, so the corpus needs many calls."""
    monkeypatch.setattr(parallel_listing, "LISTING_PAGE_SIZE", 3)
    monkeypatch.setattr(parallel_listing, "CALL_BUDGET_FILES", 4)
    monkeypatch.setattr(parallel_listing, "INLINE_CALL_BUDGET_FILES", 7)


def _oauth_connector(mock: MockDrive, **kwargs: Any) -> GoogleDriveConnector:
    tokens = mock.client.get("/_mock/oauth-credentials", params={"email": _EMAIL})
    tokens.raise_for_status()
    connector = GoogleDriveConnector(**kwargs)
    connector.load_credentials(
        {
            "google_tokens": json.dumps(tokens.json()),
            "google_primary_admin": _EMAIL,
            "authentication_method": "uploaded",
        }
    )
    assert not connector.is_service_account
    return connector


class _UserCorpus:
    """What the mock says the OAuth user sees, by include setting."""

    def __init__(self, client: httpx.Client) -> None:
        def scope(name: str) -> set[str]:
            response = client.get(
                f"/_mock/corpus/users/{_EMAIL}/content-ids", params={"scope": name}
            )
            response.raise_for_status()
            return set(response.json()["file_ids"])

        self.all_drives = scope("all_drives")
        self.owned = scope("owned")
        self.shared_with_me = scope("shared_with_me")
        # Files of the shared drives the user is a member of, by drive.
        self.drive_files: dict[str, set[str]] = {}
        # Files that the user cannot read the parent folder of.
        self.parent_unreadable: set[str] = set()
        summary = client.get("/_mock/corpus/summary", params={"include_ids": True})
        for file_id in summary.json()["content_file_ids"]:
            described = client.get(f"/_mock/corpus/files/{file_id}").json()
            drive_id = described["file"]["drive_id"]
            if drive_id and _EMAIL in described["drive_members"]:
                self.drive_files.setdefault(drive_id, set()).add(file_id)
            for parent_id in described["file"]["parents"]:
                parent = client.get(f"/_mock/corpus/files/{parent_id}").json()
                if _EMAIL not in parent["readers"]:
                    self.parent_unreadable.add(file_id)

    @property
    def member_drive_files(self) -> set[str]:
        return set().union(*self.drive_files.values())

    def expected(self, my_drives: bool, shared_with_me: bool, drives: bool) -> set[str]:
        """Main's serial listing: corpora=allDrives with all three on."""
        if my_drives and shared_with_me and drives:
            return self.all_drives
        files: set[str] = set()
        if my_drives:
            files |= self.owned
        if shared_with_me:
            files |= self.shared_with_me
        if drives:
            files |= self.member_drive_files
        return files


@cache
def _user_corpus(url: str) -> _UserCorpus:
    with httpx.Client(base_url=url, timeout=30) as client:
        return _UserCorpus(client)


def _assert_exact(name: str, ids: list[str], expected: set[str]) -> None:
    duplicates = [doc_id for doc_id, n in Counter(ids).items() if n > 1]
    assert not duplicates, f"{name}: {len(duplicates)} duplicates"
    listed = {_file_id(doc_id) for doc_id in ids}
    assert listed - expected == set(), f"{name}: files listed that are not expected"
    assert expected - listed == set(), f"{name}: expected files not listed"


def test_the_corpus_has_each_kind_of_file(mock_drive: MockDrive) -> None:
    """The include settings select different files of this corpus, so each
    case below checks its own set."""
    corpus = _user_corpus(mock_drive.url)
    assert corpus.owned and corpus.shared_with_me
    assert len(corpus.drive_files) >= 2
    # Files shared with the user in drives the user is not a member of.
    assert corpus.shared_with_me - corpus.member_drive_files - corpus.owned
    assert corpus.all_drives == (
        corpus.owned | corpus.shared_with_me | corpus.member_drive_files
    )


@pytest.mark.usefixtures("small_calls")
@pytest.mark.parametrize(
    "my_drives,shared_with_me,drives",
    [
        (True, True, True),
        (True, False, False),
        (False, True, False),
        (False, False, True),
        (True, True, False),
        (True, False, True),
        (False, True, True),
    ],
)
def test_oauth_lists_the_files_of_its_settings(
    mock_drive: MockDrive, my_drives: bool, shared_with_me: bool, drives: bool
) -> None:
    expected = _user_corpus(mock_drive.url).expected(my_drives, shared_with_me, drives)
    settings = {
        "include_my_drives": my_drives,
        "include_files_shared_with_me": shared_with_me,
        "include_shared_drives": drives,
    }

    stubs = list_with_resume(_oauth_connector(mock_drive, **settings))
    pruning = _slim_ids(
        _oauth_connector(mock_drive, **settings).retrieve_all_slim_docs()
    )

    assert stubs.failures == []
    assert stubs.calls > 1
    _assert_exact("stubs", [stub.id for stub in stubs.stubs], expected)
    _assert_exact("pruning", pruning, expected)
    # The shard engine listed, not the serial listing.
    assert all(cp.listing is not None for cp in stubs.checkpoints)
    for stub in stubs.stubs:
        assert stub.listing_payload.retriever_email == _EMAIL  # ty: ignore[unresolved-attribute]


@pytest.mark.usefixtures("small_calls")
def test_oauth_lists_requested_shared_drives(mock_drive: MockDrive) -> None:
    corpus = _user_corpus(mock_drive.url)
    requested = sorted(corpus.drive_files)[:2]
    urls = ",".join(
        f"https://drive.google.com/drive/folders/{drive_id}" for drive_id in requested
    )
    connector = _oauth_connector(mock_drive, shared_drive_urls=urls)

    stubs = list_with_resume(connector)

    assert stubs.checkpoints[-1].listing is not None
    _assert_exact(
        "stubs",
        [stub.id for stub in stubs.stubs],
        corpus.drive_files[requested[0]] | corpus.drive_files[requested[1]],
    )


# Text extraction reads settings from Postgres.
@pytest.mark.usefixtures("small_calls", "db_session", "tenant_context")
def test_every_entry_point_lists_the_same_files(mock_drive: MockDrive) -> None:
    corpus = _user_corpus(mock_drive.url)
    expected = corpus.all_drives
    settings = {
        "include_my_drives": True,
        "include_files_shared_with_me": True,
        "include_shared_drives": True,
    }

    inline = _index_inline(_oauth_connector(mock_drive, **settings))
    stubs = list_with_resume(_oauth_connector(mock_drive, **settings))
    pruning = _slim_ids(
        _oauth_connector(mock_drive, **settings).retrieve_all_slim_docs()
    )
    perm_sync, perm_sync_runs = _perm_sync_with_stops(
        _oauth_connector(mock_drive, **settings)
    )

    assert inline.failures == []
    assert len(inline.documents_per_call) > 1
    assert perm_sync_runs > 1
    _assert_exact("inline", inline.document_ids, expected)
    _assert_exact("stubs", [stub.id for stub in stubs.stubs], expected)
    _assert_exact("pruning", pruning, expected)
    _assert_exact("permission sync", perm_sync, expected)

    # The folder tree comes from the folder listings and the STUB parents.
    node_ids = {node.raw_node_id for node in inline.nodes}
    assert len(node_ids) == len(inline.nodes)
    for node in inline.nodes:
        assert node.raw_parent_id is None or node.raw_parent_id in node_ids
    for document in inline.documents:
        if document.parent_hierarchy_raw_node_id not in node_ids:
            # The user cannot read the folder, so the document keeps its
            # STUB parent.
            assert _file_id(document.id) in corpus.parent_unreadable, document.id
    assert inline.final is not None and inline.final.listing is not None
    assert inline.final.listing.unresolved_parent_emails == {}


def _old_oauth_checkpoint(connector: GoogleDriveConnector) -> GoogleDriveCheckpoint:
    """A checkpoint of main's serial OAuth listing, in its JSON format, in
    its first stage with a page token."""
    old = {
        "has_more": True,
        "retrieved_folder_and_drive_ids": [],
        "completion_stage": "oauth_files",
        "completion_map": {
            _EMAIL: {
                "stage": "oauth_files",
                "completed_until": time.time() - 60,
                "current_folder_or_drive_id": None,
                "next_page_token": "token-from-the-serial-listing",
            }
        },
        "retrieved_drive_file_ids": [],
    }
    return connector.validate_checkpoint_json(json.dumps(old))


@pytest.mark.usefixtures("small_calls")
def test_old_oauth_checkpoint_is_dropped(mock_drive: MockDrive) -> None:
    connector = _oauth_connector(
        mock_drive,
        include_my_drives=True,
        include_files_shared_with_me=True,
        include_shared_drives=True,
    )
    checkpoint = _old_oauth_checkpoint(connector)
    ids: list[str] = []
    end = time.time()
    for _ in range(_MAX_CALLS):
        generator = connector.retrieve_slim_docs_from_checkpoint(0, end, checkpoint)
        while True:
            try:
                item = next(generator)
            except StopIteration as stop:
                checkpoint = connector.validate_checkpoint_json(
                    stop.value.model_dump_json()
                )
                break
            if isinstance(item, SlimDocumentStub):
                ids.append(item.id)
            else:
                assert isinstance(item, HierarchyNode), item
        if not checkpoint.has_more:
            break

    _assert_exact("stubs", ids, _user_corpus(mock_drive.url).all_drives)
    assert "completion_map" not in checkpoint.model_dump()
    assert checkpoint.listing is not None and checkpoint.listing.is_done


@pytest.mark.usefixtures("small_calls")
def test_a_refresh_failure_fails_the_listing(
    mock_drive: MockDrive, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The OAuth user is the only principal, so a revoked grant must fail
    the prune, not read as deleted files."""
    fetch_page = parallel_listing.ParallelDriveLister._fetch_page
    calls = 0

    def revoked_after_a_few_pages(
        self: parallel_listing.ParallelDriveLister, shard: ListingShard
    ) -> object:
        nonlocal calls
        calls += 1
        if calls >= 5:
            raise GoogleDriveRefreshError("Token has been expired or revoked.")
        return fetch_page(self, shard)

    monkeypatch.setattr(
        parallel_listing.ParallelDriveLister, "_fetch_page", revoked_after_a_few_pages
    )
    connector = _oauth_connector(
        mock_drive,
        include_my_drives=True,
        include_files_shared_with_me=True,
        include_shared_drives=True,
    )

    with pytest.raises(GoogleDriveRefreshError):
        list(connector.retrieve_all_slim_docs())


@pytest.mark.usefixtures("small_calls")
def test_a_denied_page_fails_the_listing(
    mock_drive: MockDrive, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A 403 on the OAuth user's own listing, for example after Drive access
    is turned off, must fail the prune, not end the listing as empty."""
    fetch_page = parallel_listing.ParallelDriveLister._fetch_page

    def denied_my_drive(
        self: parallel_listing.ParallelDriveLister, shard: ListingShard
    ) -> object:
        if shard.partition.kind is ListingPartitionKind.MY_DRIVE:
            raise GoogleDriveHttpError(
                status_code=403,
                reasons=("accessNotConfigured",),
                access_denied=True,
                message="Drive API is disabled",
            )
        return fetch_page(self, shard)

    monkeypatch.setattr(
        parallel_listing.ParallelDriveLister, "_fetch_page", denied_my_drive
    )
    connector = _oauth_connector(mock_drive, include_my_drives=True)

    with pytest.raises(GoogleDriveHttpError):
        list(connector.retrieve_all_slim_docs())


@pytest.mark.parametrize("all_settings", [True, False])
def test_shared_with_listing_includes_shared_drive_items_as_all_drives(
    mock_drive: MockDrive, monkeypatch: pytest.MonkeyPatch, all_settings: bool
) -> None:
    """With all three settings on, main listed corpora=allDrives, which holds
    files shared directly from drives the user is not a member of. The
    shared-with-user listing then lists all drives too."""
    connector = _oauth_connector(
        mock_drive,
        include_my_drives=all_settings,
        include_files_shared_with_me=True,
        include_shared_drives=all_settings,
    )
    variants: set[DriveCorpus] = set()
    list_files = connector.ops.list_files

    def recording_list_files(**kwargs: Any) -> Any:
        if "not 'me' in owners" in (kwargs.get("query") or ""):
            variants.add(kwargs["variant"])
        return list_files(**kwargs)

    monkeypatch.setattr(connector.ops, "list_files", recording_list_files)
    list(connector.retrieve_all_slim_docs())

    expected = DriveCorpus.ALL_DRIVES if all_settings else DriveCorpus.USER
    assert variants == {expected}
