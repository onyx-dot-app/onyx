"""Requested folders list through the shard engine as folder subtree
partitions. Each entry point must give exactly the folder's subtree, with no
gaps and no duplicates, across resumes that send the checkpoint through
JSON."""

import json
import threading
import time
from collections import Counter
from collections.abc import Iterable
from typing import Any

import pytest

from onyx.connectors.google_drive import parallel_listing
from onyx.connectors.google_drive.connector import (
    GoogleDriveConnector,
    UnreachableTargetsError,
)
from onyx.connectors.google_drive.models import (
    GoogleDriveFileType,
    ListingPartitionKind,
    ListingShard,
)
from onyx.connectors.google_drive.source_operations import GoogleDriveHttpError
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
from tests.external_dependency_unit.connectors.google_drive.test_drive_oauth_listing import (
    _EMAIL as _OAUTH_EMAIL,
)
from tests.external_dependency_unit.connectors.google_drive.test_drive_oauth_listing import (
    _oauth_connector,
)

_BASE_CORPUS: dict[str, Any] = {
    "num_users": 3,
    "num_groups": 2,
    "num_shared_drives": 2,
    "files_per_shared_drive": 15,
    "files_per_user": 8,
    "folders_per_container": 3,
    # A shortcut in a container root reaches a random file, which would make
    # the expected sets depend on the seed.
    "shortcut_fraction": 0,
}
_PAGE_SIZE = 3


@pytest.fixture
def small_calls(monkeypatch: pytest.MonkeyPatch) -> None:
    """Small pages and budgets, so a small tree needs many calls."""
    monkeypatch.setattr(parallel_listing, "LISTING_PAGE_SIZE", _PAGE_SIZE)
    monkeypatch.setattr(parallel_listing, "CALL_BUDGET_FILES", 10)
    monkeypatch.setattr(parallel_listing, "INLINE_CALL_BUDGET_FILES", 7)


def _folder_url(folder_id: str) -> str:
    return f"https://drive.google.com/drive/folders/{folder_id}"


def _content_ids(mock_drive: MockDrive, folder_id: str) -> set[str]:
    response = mock_drive.client.get(f"/_mock/corpus/folders/{folder_id}/content-ids")
    response.raise_for_status()
    return set(response.json()["file_ids"])


def _summary(mock_drive: MockDrive) -> dict[str, Any]:
    return mock_drive.client.get("/_mock/corpus/summary").json()


def _connector(mock_drive: MockDrive, **settings: Any) -> GoogleDriveConnector:
    return mock_drive.build_connector(
        include_shared_drives=False,
        include_my_drives=False,
        include_files_shared_with_me=False,
        **settings,
    )


def _assert_exact(name: str, document_ids: Iterable[str], expected: set[str]) -> None:
    file_ids = [_file_id(document_id) for document_id in document_ids]
    duplicates = [file_id for file_id, n in Counter(file_ids).items() if n > 1]
    assert not duplicates, f"{name}: {len(duplicates)} duplicates"
    assert set(file_ids) == expected, name


def _record_walked_folders(
    monkeypatch: pytest.MonkeyPatch,
) -> list[str]:
    """The folder ids that a walk shard listed the children of."""
    walked: list[str] = []
    lock = threading.Lock()
    fetch_page = parallel_listing.ParallelDriveLister._fetch_page

    def recording_fetch_page(
        self: parallel_listing.ParallelDriveLister, shard: ListingShard
    ) -> object:
        if shard.folder_id is not None:
            with lock:
                walked.append(shard.folder_id)
        return fetch_page(self, shard)

    monkeypatch.setattr(
        parallel_listing.ParallelDriveLister, "_fetch_page", recording_fetch_page
    )
    return walked


@pytest.mark.parametrize("container,index", [("my_drive", 2), ("shared_drive", 1)])
# Text extraction reads settings from Postgres.
@pytest.mark.usefixtures("small_calls", "db_session", "tenant_context")
def test_every_entry_point_lists_exactly_the_subtree(
    own_mock_drive: MockDrive,
    monkeypatch: pytest.MonkeyPatch,
    container: str,
    index: int,
) -> None:
    """The requested tree holds a shortcut to another tree, which the walk
    follows as the serial crawl did, and a shortcut back to its own root,
    which the walk must stop at. A third tree in the same container is not
    requested."""
    own_mock_drive.set_corpus(
        {
            **_BASE_CORPUS,
            "folder_trees": [
                {"container": container, "index": index, "depth": 1},
                {
                    "container": container,
                    "index": index,
                    "depth": 3,
                    "branching": 2,
                    "files_per_folder": 2,
                    "deepest_folder_files": 10,
                    "cycle_shortcut": True,
                    "shortcut_to_tree": 0,
                },
                {"container": container, "index": index, "depth": 1},
            ],
        }
    )
    linked_root, root_id, other_root = _summary(own_mock_drive)["folder_tree_root_ids"]
    expected = _content_ids(own_mock_drive, root_id)
    assert _content_ids(own_mock_drive, linked_root) <= expected
    assert not _content_ids(own_mock_drive, other_root) & expected

    def connector() -> GoogleDriveConnector:
        return _connector(own_mock_drive, shared_folder_urls=_folder_url(root_id))

    inline_connector = connector()
    folder_reads: list[str] = []
    read_folder = inline_connector._get_folder_metadata

    def counting_read(folder_id: str, *args: Any, **kwargs: Any) -> object:
        folder_reads.append(folder_id)
        return read_folder(folder_id, *args, **kwargs)

    monkeypatch.setattr(inline_connector, "_get_folder_metadata", counting_read)

    inline = _index_inline(inline_connector)
    stubs = list_with_resume(connector())
    pruning = _slim_ids(connector().retrieve_all_slim_docs())
    perm_sync, perm_sync_runs = _perm_sync_with_stops(connector())

    assert inline.failures == []
    assert stubs.failures == []
    assert len(inline.documents_per_call) > 1
    assert stubs.calls > 1
    assert perm_sync_runs > 1
    _assert_exact("inline", inline.document_ids, expected)
    _assert_exact("stubs", [stub.id for stub in stubs.stubs], expected)
    _assert_exact("pruning", pruning, expected)
    _assert_exact("permission sync", perm_sync, expected)

    # The walk yields each folder it lists as a node. Only the requested
    # folder and the folders above it are read one by one.
    node_ids = {node.raw_node_id for node in inline.nodes}
    assert len(node_ids) == len(inline.nodes)
    for node in inline.nodes:
        assert node.raw_parent_id is None or node.raw_parent_id in node_ids
    for document in inline.documents:
        assert document.parent_hierarchy_raw_node_id in node_ids, document.id
    assert root_id in folder_reads
    assert len(set(folder_reads)) <= 3, folder_reads
    assert inline.final is not None and inline.final.listing is not None
    assert inline.final.listing.unresolved_parent_emails == {}
    assert inline.final.listing.total_docs == len(inline.document_ids)
    assert inline.final.unreachable_target_ids == set()


def test_a_large_folder_splits_by_time(
    own_mock_drive: MockDrive, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A folder with many files deep in the tree lists as time-range shards,
    not page after page."""
    page_size = 10
    monkeypatch.setattr(parallel_listing, "LISTING_PAGE_SIZE", page_size)
    monkeypatch.setattr(parallel_listing, "LEAF_TARGET_FILES", 24 * page_size)
    monkeypatch.setattr(parallel_listing, "MIN_FILES_TO_SPLIT", 48 * page_size)
    monkeypatch.setattr(parallel_listing, "MIN_FILES_TO_PROBE", 24 * page_size)
    monkeypatch.setattr(parallel_listing, "CALL_BUDGET_FILES", 300)
    own_mock_drive.set_corpus(
        {
            **_BASE_CORPUS,
            "folder_trees": [
                {
                    "container": "shared_drive",
                    "index": 0,
                    "depth": 4,
                    "branching": 2,
                    "files_per_folder": 2,
                    "deepest_folder_files": 1_500,
                }
            ],
        }
    )
    root_id = _summary(own_mock_drive)["folder_tree_root_ids"][0]
    expected = _content_ids(own_mock_drive, root_id)
    assert len(expected) == 31 * 2 + 1_500

    splits: list[str] = []
    try_split = parallel_listing.ParallelDriveLister._try_split

    def recording_try_split(
        self: parallel_listing.ParallelDriveLister,
        shard: ListingShard,
        files: list[GoogleDriveFileType],
    ) -> object:
        result = try_split(self, shard, files)
        if isinstance(result, list) and result and shard.folder_id is not None:
            splits.append(shard.folder_id)
        return result

    monkeypatch.setattr(
        parallel_listing.ParallelDriveLister, "_try_split", recording_try_split
    )

    stubs = list_with_resume(
        _connector(own_mock_drive, shared_folder_urls=_folder_url(root_id))
    )

    assert stubs.failures == []
    assert stubs.calls > 1
    _assert_exact("stubs", [stub.id for stub in stubs.stubs], expected)
    assert splits, "the large folder did not split"


@pytest.mark.usefixtures("small_calls")
def test_a_requested_drive_url_that_is_a_folder(
    own_mock_drive: MockDrive, monkeypatch: pytest.MonkeyPatch
) -> None:
    own_mock_drive.set_corpus(
        {
            **_BASE_CORPUS,
            "folder_trees": [{"container": "shared_drive", "index": 0, "depth": 2}],
        }
    )
    root_id = _summary(own_mock_drive)["folder_tree_root_ids"][0]
    expected = _content_ids(own_mock_drive, root_id)
    walked = _record_walked_folders(monkeypatch)

    stubs = list_with_resume(
        _connector(own_mock_drive, shared_drive_urls=_folder_url(root_id))
    )

    assert stubs.failures == []
    _assert_exact("stubs", [stub.id for stub in stubs.stubs], expected)
    assert root_id in walked
    state = stubs.checkpoints[-1].listing
    assert state is not None
    assert {partition.kind for partition, _, _ in state.started_partitions} == {
        ListingPartitionKind.FOLDER_SUBTREE
    }


# The mock's drive 0 has no organizer, so its listing is not complete.
@pytest.mark.parametrize("drive_index,covered", [(0, False), (1, True)])
@pytest.mark.usefixtures("small_calls")
def test_folders_with_a_shared_drive_and_a_my_drive(
    own_mock_drive: MockDrive,
    monkeypatch: pytest.MonkeyPatch,
    drive_index: int,
    covered: bool,
) -> None:
    """A requested folder in a requested shared drive is walked, also when an
    organizer lists the drive in full: the walk follows the folder shortcuts,
    which the drive listing does not, and it does not depend on that listing
    staying complete. A requested folder in a requested My Drive is walked.
    Each walk drops the files that the other listing yields. No file is
    listed twice."""
    own_mock_drive.set_corpus(
        {
            **_BASE_CORPUS,
            "folder_trees": [
                {"container": "shared_drive", "index": drive_index, "depth": 2},
                {"container": "my_drive", "index": 2, "depth": 2},
            ],
        }
    )
    summary = _summary(own_mock_drive)
    in_drive_root, in_my_drive_root = summary["folder_tree_root_ids"]
    drive_id = summary["shared_drive_ids"][drive_index]
    owner = "user2@onyx-mock.test"
    owned = set(
        own_mock_drive.client.get(
            f"/_mock/corpus/users/{owner}/content-ids", params={"scope": "owned"}
        ).json()["file_ids"]
    )
    walked_tree = _content_ids(own_mock_drive, in_my_drive_root)
    assert walked_tree <= owned
    expected = _content_ids(own_mock_drive, drive_id) | owned | walked_tree

    def connector() -> GoogleDriveConnector:
        return _connector(
            own_mock_drive,
            shared_drive_urls=_folder_url(drive_id),
            shared_folder_urls=",".join(
                _folder_url(folder_id)
                for folder_id in (in_drive_root, in_my_drive_root)
            ),
            my_drive_emails=owner,
        )

    walked = _record_walked_folders(monkeypatch)
    stubs = list_with_resume(connector())
    pruning = _slim_ids(connector().retrieve_all_slim_docs())

    assert stubs.failures == []
    _assert_exact("stubs", [stub.id for stub in stubs.stubs], expected)
    _assert_exact("pruning", pruning, expected)
    final = stubs.checkpoints[-1]
    assert in_my_drive_root in walked
    assert (drive_id in final.incomplete_drive_ids) is not covered
    assert in_drive_root in walked
    assert final.unreachable_target_ids == set()


def test_an_unreachable_requested_folder_fails_the_prune(
    own_mock_drive: MockDrive,
) -> None:
    """Pruning deletes what its listing lacks. A requested folder that no
    user can see must fail the prune. Permission sync goes on."""
    mock_drive = own_mock_drive
    mock_drive.set_corpus(
        {
            **_BASE_CORPUS,
            "folder_trees": [{"container": "my_drive", "index": 1, "depth": 1}],
        }
    )
    folder_id = _summary(mock_drive)["folder_tree_root_ids"][0]
    missing = "1NoSuchFolderInTheCorpus"
    urls = ",".join(_folder_url(target) for target in (folder_id, missing))

    with pytest.raises(UnreachableTargetsError, match=missing):
        list(_connector(mock_drive, shared_folder_urls=urls).retrieve_all_slim_docs())

    perm_sync = _slim_ids(
        _connector(
            mock_drive, shared_folder_urls=urls
        ).retrieve_all_slim_docs_perm_sync(start=0)
    )
    _assert_exact("permission sync", perm_sync, _content_ids(mock_drive, folder_id))


def test_a_denied_walk_page_makes_the_folder_unreachable(
    own_mock_drive: MockDrive, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A page of a folder walk that Drive denies fails that walk, with a
    reported failure. No other user walks the folder, so the folder is
    unreachable: the listing ends and pruning refuses to run."""
    own_mock_drive.set_corpus(
        {
            **_BASE_CORPUS,
            "folder_trees": [{"container": "my_drive", "index": 1, "depth": 1}],
        }
    )
    folder_id = _summary(own_mock_drive)["folder_tree_root_ids"][0]
    fetch_page = parallel_listing.ParallelDriveLister._fetch_page

    def deny_walk(
        self: parallel_listing.ParallelDriveLister, shard: ListingShard
    ) -> tuple[list[GoogleDriveFileType], str | None]:
        if shard.partition.kind is ListingPartitionKind.FOLDER_SUBTREE:
            raise GoogleDriveHttpError(
                status_code=403,
                reasons=("insufficientFilePermissions",),
                access_denied=True,
                message="The user does not have sufficient permissions",
            )
        return fetch_page(self, shard)

    monkeypatch.setattr(parallel_listing.ParallelDriveLister, "_fetch_page", deny_walk)

    stubs = list_with_resume(
        _connector(own_mock_drive, shared_folder_urls=_folder_url(folder_id))
    )

    assert stubs.failures, "the denied walk was not reported"
    assert folder_id in stubs.checkpoints[-1].unreachable_target_ids
    with pytest.raises(GoogleDriveHttpError):
        list(
            _connector(
                own_mock_drive, shared_folder_urls=_folder_url(folder_id)
            ).retrieve_all_slim_docs()
        )


def test_pruning_lists_folder_files_edited_during_the_listing(
    own_mock_drive: MockDrive, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Every file is edited after the walk began, so each one moves past the
    window end. The last pruning pass walks the folder again with no upper
    bound, so pruning still lists every file."""
    monkeypatch.setattr(parallel_listing, "LISTING_PAGE_SIZE", _PAGE_SIZE)
    own_mock_drive.set_corpus(
        {
            **_BASE_CORPUS,
            "folder_trees": [{"container": "my_drive", "index": 1, "depth": 2}],
        }
    )
    root_id = _summary(own_mock_drive)["folder_tree_root_ids"][0]
    expected = _content_ids(own_mock_drive, root_id)
    all_files = len(own_mock_drive.content_file_ids())
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
                    own_mock_drive.client.post(
                        "/_mock/corpus/touch", json={"count": all_files}
                    ).json()["file_ids"]
                )
        return fetch_page(self, shard)

    monkeypatch.setattr(
        parallel_listing.ParallelDriveLister, "_fetch_page", edit_during_listing
    )

    pruning = _slim_ids(
        _connector(
            own_mock_drive, shared_folder_urls=_folder_url(root_id)
        ).retrieve_all_slim_docs()
    )

    assert expected <= set(edited)
    _assert_exact("pruning", pruning, expected)


@pytest.mark.usefixtures("small_calls", "db_session", "tenant_context")
def test_a_serial_folder_checkpoint_is_dropped(own_mock_drive: MockDrive) -> None:
    """A checkpoint of the serial requested-folder crawl is dropped. Its
    claims would make the new listing drop every file, so the files prove
    that the attempt listed again from its window start."""
    own_mock_drive.set_corpus(
        {
            **_BASE_CORPUS,
            "folder_trees": [{"container": "my_drive", "index": 1, "depth": 2}],
        }
    )
    root_id = _summary(own_mock_drive)["folder_tree_root_ids"][0]
    expected = _content_ids(own_mock_drive, root_id)
    connector = _connector(own_mock_drive, shared_folder_urls=_folder_url(root_id))
    # main's JSON format, in the requested-target phase.
    old_json = {
        "has_more": True,
        "retrieved_folder_and_drive_ids": [],
        "completion_stage": "start",
        "completion_map": {},
        "retrieved_drive_file_ids": sorted(expected),
        "user_emails": ["admin@onyx-mock.test"],
        "drive_ids_to_retrieve": [],
        "folder_ids_to_retrieve": [root_id],
        "phase_progress": {
            "phase": "requested_targets",
            "partition_keys": [f"{root_id}|admin@onyx-mock.test"],
            "partition_index": 0,
            "next_page_token": None,
            "completed_until": 0,
        },
        "crawled_target_ids": [],
        "seen_hierarchy_node_raw_ids": [],
    }
    old = connector.validate_checkpoint_json(json.dumps(old_json))

    run = _index_inline(connector, checkpoint=old)

    assert run.failures == []
    _assert_exact("inline", run.document_ids, expected)
    assert run.final is not None
    assert "phase_progress" not in run.final.model_dump()
    assert run.final.listing is not None and run.final.listing.is_done


@pytest.mark.usefixtures("small_calls", "db_session", "tenant_context")
def test_oauth_lists_exactly_a_requested_folder(
    own_mock_drive: MockDrive, monkeypatch: pytest.MonkeyPatch
) -> None:
    """OAuth walks a requested folder as its one user, through the same
    shortcuts and cycle as a service account. A requested folder that the
    user cannot see fails the prune."""
    own_mock_drive.set_corpus(
        {
            **_BASE_CORPUS,
            "folder_trees": [
                {"container": "my_drive", "index": 1, "depth": 1},
                {
                    "container": "my_drive",
                    "index": 1,
                    "depth": 2,
                    "cycle_shortcut": True,
                    "shortcut_to_tree": 0,
                },
                # In another user's My Drive and not shared with the OAuth
                # user.
                {"container": "my_drive", "index": 2, "depth": 1},
            ],
        }
    )
    assert _OAUTH_EMAIL == "user1@onyx-mock.test"
    linked_root, root_id, hidden_root = _summary(own_mock_drive)["folder_tree_root_ids"]
    expected = _content_ids(own_mock_drive, root_id)
    assert _content_ids(own_mock_drive, linked_root) <= expected

    def connector(*folder_ids: str) -> GoogleDriveConnector:
        return _oauth_connector(
            own_mock_drive,
            shared_folder_urls=",".join(_folder_url(f) for f in folder_ids),
        )

    walked = _record_walked_folders(monkeypatch)
    inline = _index_inline(connector(root_id))
    stubs = list_with_resume(connector(root_id))
    pruning = _slim_ids(connector(root_id).retrieve_all_slim_docs())
    perm_sync, _ = _perm_sync_with_stops(connector(root_id))

    assert inline.failures == []
    assert stubs.failures == []
    _assert_exact("inline", inline.document_ids, expected)
    _assert_exact("stubs", [stub.id for stub in stubs.stubs], expected)
    _assert_exact("pruning", pruning, expected)
    _assert_exact("permission sync", perm_sync, expected)
    assert root_id in walked
    assert inline.final is not None and inline.final.listing is not None
    assert inline.final.listing.is_done

    with pytest.raises(UnreachableTargetsError, match=hidden_root):
        list(connector(root_id, hidden_root).retrieve_all_slim_docs())
