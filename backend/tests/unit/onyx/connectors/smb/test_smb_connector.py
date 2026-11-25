from collections.abc import Generator
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, create_autospec, patch

import pytest

from onyx.connectors.connector_runner import CheckpointOutputWrapper
from onyx.connectors.exceptions import CredentialInvalidError
from onyx.connectors.models import (
    ConnectorFailure,
    Document,
    DocumentFailure,
    HierarchyNode,
    SlimDocument,
)
from onyx.connectors.smb import connector as smb_connector
from onyx.connectors.smb.connector import PATH_METADATA_KEY, SmbConnector
from onyx.connectors.smb.models import (
    FILE_ATTRIBUTE_DIRECTORY,
    FILE_ATTRIBUTE_OFFLINE,
    FILE_ATTRIBUTE_RECALL_ON_DATA_ACCESS,
    FILE_ATTRIBUTE_REPARSE_POINT,
    SmbCheckpoint,
    SmbEntry,
    SmbFile,
)
from onyx.connectors.smb.source_operations import (
    SmbAccessDeniedError,
    SmbNotFoundError,
    SmbRequestError,
    SmbSourceOperations,
)

OLD = datetime(2025, 1, 1, tzinfo=timezone.utc)
UPDATED = datetime(2026, 3, 1, tzinfo=timezone.utc)
WINDOW_START = datetime(2026, 2, 1, tzinfo=timezone.utc).timestamp()
WINDOW_END = datetime(2026, 4, 1, tzinfo=timezone.utc).timestamp()
ROOT_ID = "smb://files.example.com/Plans"

Tree = dict[str, list[SmbEntry] | Exception]


def _file(
    name: str,
    *,
    written: datetime = UPDATED,
    changed: datetime | None = None,
    created: datetime | None = None,
    size: int = 10,
    attributes: int = 0,
) -> SmbEntry:
    return SmbEntry(
        name=name,
        attributes=attributes,
        creation_time=created or written,
        last_write_time=written,
        change_time=changed or written,
        size=size,
    )


def _folder(
    name: str,
    *,
    written: datetime = OLD,
    changed: datetime | None = None,
    attributes: int = 0,
) -> SmbEntry:
    return SmbEntry(
        name=name,
        attributes=FILE_ATTRIBUTE_DIRECTORY | attributes,
        creation_time=OLD,
        last_write_time=written,
        change_time=changed or written,
        size=0,
    )


@pytest.fixture(autouse=True)
def _no_unstructured_key() -> Generator[None, None, None]:
    with patch(
        "onyx.file_processing.extract_file_text.get_unstructured_api_key",
        return_value=None,
    ):
        yield


def _connector(
    tree: Tree,
    *,
    path_prefix: str = "",
    excluded_paths: list[str] | None = None,
    index_offline_files: bool = False,
    root_written: datetime = OLD,
) -> tuple[SmbConnector, MagicMock]:
    """A connector whose gateway serves ``tree`` by folder path and returns
    each file's path as its text."""
    connector = SmbConnector(
        host="Files.Example.com",
        share="Plans",
        path_prefix=path_prefix,
        excluded_paths=excluded_paths,
        index_offline_files=index_offline_files,
    )
    ops = create_autospec(SmbSourceOperations, instance=True)

    def list_folder(*, path: str) -> list[SmbEntry]:
        listing = tree[path]
        if isinstance(listing, Exception):
            raise listing
        return listing

    ops.list_folder.side_effect = list_folder
    ops.stat.side_effect = lambda *, path: _folder(  # noqa: ARG005
        path.rsplit("/", 1)[-1], written=root_written
    )
    ops.read_file.side_effect = lambda *, path, max_bytes: SmbFile(  # noqa: ARG005
        size=len(path), content=path.encode()
    )
    connector._ops = ops
    return connector, ops


def _step(
    connector: SmbConnector, checkpoint: SmbCheckpoint
) -> tuple[list[Document | HierarchyNode | ConnectorFailure], SmbCheckpoint]:
    items: list[Document | HierarchyNode | ConnectorFailure] = []
    next_checkpoint: SmbCheckpoint | None = None
    for document, node, failure, returned in CheckpointOutputWrapper[SmbCheckpoint]()(
        connector.load_from_checkpoint(WINDOW_START, WINDOW_END, checkpoint)
    ):
        items.extend(item for item in (document, node, failure) if item is not None)
        next_checkpoint = returned or next_checkpoint
    assert next_checkpoint is not None
    # Every step survives the JSON round trip the checkpoint store makes.
    return items, connector.validate_checkpoint_json(next_checkpoint.model_dump_json())


def _run(connector: SmbConnector) -> list[Document | HierarchyNode | ConnectorFailure]:
    items: list[Document | HierarchyNode | ConnectorFailure] = []
    checkpoint = connector.build_dummy_checkpoint()
    for _ in range(100):
        step_items, checkpoint = _step(connector, checkpoint)
        items.extend(step_items)
        if not checkpoint.has_more:
            return items
    raise AssertionError("The walk did not finish.")


def _document_ids(items: list[Document | HierarchyNode | ConnectorFailure]) -> set[str]:
    return {item.id for item in items if isinstance(item, Document)}


def _node_ids(items: list[Document | HierarchyNode | ConnectorFailure]) -> list[str]:
    return [item.raw_node_id for item in items if isinstance(item, HierarchyNode)]


def test_walk_indexes_every_folder_with_ids_scoped_by_host_and_share() -> None:
    connector, _ = _connector(
        {
            "": [_folder("Projects"), _file("readme.txt")],
            "Projects": [_folder("Alpha"), _file("b.txt")],
            "Projects/Alpha": [_file("plan.txt")],
        }
    )

    items = _run(connector)

    assert _document_ids(items) == {
        f"{ROOT_ID}/readme.txt",
        f"{ROOT_ID}/Projects/b.txt",
        f"{ROOT_ID}/Projects/Alpha/plan.txt",
    }
    assert _node_ids(items) == [
        ROOT_ID,
        f"{ROOT_ID}/Projects",
        f"{ROOT_ID}/Projects/Alpha",
    ]
    plan = next(
        item
        for item in items
        if isinstance(item, Document) and item.id.endswith("plan.txt")
    )
    assert plan.parent_hierarchy_raw_node_id == f"{ROOT_ID}/Projects/Alpha"
    assert plan.metadata[PATH_METADATA_KEY] == (
        "\\\\Files.Example.com\\Plans\\Projects\\Alpha\\plan.txt"
    )
    # A browser blocks file links, so the document has none.
    assert all(section.link is None for section in plan.sections)


def test_a_step_stops_at_the_file_limit_and_resumes_after_the_last_name() -> None:
    connector, ops = _connector(
        {
            "": [_file("c.txt"), _folder("sub"), _file("a.txt"), _file("b.txt")],
            "sub": [_file("d.txt")],
        }
    )

    with patch.object(smb_connector, "FILES_PER_STEP", 2):
        first, checkpoint = _step(connector, connector.build_dummy_checkpoint())
        assert _document_ids(first) == {f"{ROOT_ID}/a.txt", f"{ROOT_ID}/b.txt"}
        assert checkpoint.has_more and checkpoint.last_name == "b.txt"
        assert checkpoint.current is not None and checkpoint.current.path == ""

        second, checkpoint = _step(connector, checkpoint)
        # "sub" sorts after "c.txt": the resumed step still queues it.
        assert _document_ids(second) == {f"{ROOT_ID}/c.txt"}
        assert _node_ids(second) == [f"{ROOT_ID}/sub"]
        assert [folder.path for folder in checkpoint.pending] == ["sub"]

        third, checkpoint = _step(connector, checkpoint)

    assert _document_ids(third) == {f"{ROOT_ID}/sub/d.txt"}
    assert not checkpoint.has_more
    assert ops.read_file.call_count == 4


@pytest.mark.parametrize(
    "entry, indexed",
    [
        (_file("new.txt"), True),
        (_file("old.txt", written=OLD), False),
        # Copied onto the share: the last write time stays old.
        (_file("copied.txt", written=OLD, created=UPDATED), True),
        # Renamed, moved in, or given a new ACL.
        (_file("renamed.txt", written=OLD, changed=UPDATED), True),
        (_file("future.txt", written=UPDATED + timedelta(days=365)), False),
    ],
)
def test_the_newest_of_three_timestamps_decides_the_window(
    entry: SmbEntry, indexed: bool
) -> None:
    connector, _ = _connector({"": [entry]})

    assert bool(_document_ids(_run(connector))) is indexed


def test_a_renamed_folder_indexes_its_unchanged_files() -> None:
    """A rename gives every file below a new document id and no new
    timestamp."""
    old_file = _file("plan.txt", written=OLD)
    connector, _ = _connector(
        {
            "": [
                _folder("Renamed", changed=UPDATED),
                _folder("Untouched"),
            ],
            "Renamed": [_folder("Deep"), old_file],
            "Renamed/Deep": [old_file],
            "Untouched": [old_file],
        }
    )

    assert _document_ids(_run(connector)) == {
        f"{ROOT_ID}/Renamed/plan.txt",
        f"{ROOT_ID}/Renamed/Deep/plan.txt",
    }


def test_a_folder_renamed_and_then_written_to_still_indexes_its_files() -> None:
    """A new entry in the folder sets its change time and last write time to
    one instant, which hides the rename. The parent's last write time shows
    that one of its entries was renamed."""
    old_file = _file("plan.txt", written=OLD)
    tree: Tree = {
        "": [_folder("Busy", written=UPDATED)],
        "Busy": [old_file],
    }

    renamed, _ = _connector(tree, root_written=UPDATED)
    only_written_to, _ = _connector(tree, root_written=OLD)

    assert _document_ids(_run(renamed)) == {f"{ROOT_ID}/Busy/plan.txt"}
    assert _document_ids(_run(only_written_to)) == set()


def test_walk_skips_what_it_must_not_follow_or_read() -> None:
    connector, ops = _connector(
        {
            "": [
                _folder("Junction", attributes=FILE_ATTRIBUTE_REPARSE_POINT),
                _file("link.txt", attributes=FILE_ATTRIBUTE_REPARSE_POINT),
                _file("tiered.txt", attributes=FILE_ATTRIBUTE_OFFLINE),
                _file("cloud.txt", attributes=FILE_ATTRIBUTE_RECALL_ON_DATA_ACCESS),
                _file("~$report.docx"),
                _file("Thumbs.db"),
                _file("desktop.ini"),
                _file("drawing.dwg"),
                _file("huge.txt", size=10**12),
                _folder("Private"),
                _folder("Archive"),
                _file("kept.txt"),
            ],
            "Private": SmbAccessDeniedError("denied"),
            "Archive": [_file("old.txt")],
        },
        excluded_paths=["archive"],
    )

    items = _run(connector)

    assert _document_ids(items) == {f"{ROOT_ID}/kept.txt"}
    assert _node_ids(items) == [ROOT_ID, f"{ROOT_ID}/Private"]
    assert [call.kwargs["path"] for call in ops.list_folder.call_args_list] == [
        "",
        "Private",
    ]


def test_offline_files_are_read_when_the_option_is_on() -> None:
    connector, _ = _connector(
        {"": [_file("tiered.txt", attributes=FILE_ATTRIBUTE_OFFLINE)]},
        index_offline_files=True,
    )

    assert _document_ids(_run(connector)) == {f"{ROOT_ID}/tiered.txt"}


def test_path_prefix_yields_its_folders_and_must_be_readable() -> None:
    connector, _ = _connector(
        {"Projects/Alpha": [_file("plan.txt")]}, path_prefix="\\Projects\\Alpha\\"
    )
    denied, _ = _connector(
        {"Projects": SmbAccessDeniedError("denied")}, path_prefix="Projects"
    )

    items = _run(connector)

    assert _node_ids(items) == [
        ROOT_ID,
        f"{ROOT_ID}/Projects",
        f"{ROOT_ID}/Projects/Alpha",
    ]
    assert _document_ids(items) == {f"{ROOT_ID}/Projects/Alpha/plan.txt"}
    with pytest.raises(SmbAccessDeniedError):
        _run(denied)


def test_one_failed_file_is_a_failure_and_a_bad_credential_stops_the_run() -> None:
    connector, ops = _connector({"": [_file("a.txt"), _file("b.txt")]})
    ops.read_file.side_effect = [
        SmbRequestError("sharing violation", status_code=None),
        SmbFile(size=1, content=b"b"),
    ]

    items = _run(connector)

    failures = [item for item in items if isinstance(item, ConnectorFailure)]
    assert len(failures) == 1
    assert failures[0].failed_document is not None
    assert failures[0].failed_document.document_id == f"{ROOT_ID}/a.txt"
    assert _document_ids(items) == {f"{ROOT_ID}/b.txt"}

    ops.read_file.side_effect = CredentialInvalidError("password expired")
    with pytest.raises(CredentialInvalidError):
        _run(connector)


def _slim(connector: SmbConnector, callback: MagicMock | None = None) -> list[str]:
    return [
        item.id if isinstance(item, SlimDocument) else item.raw_node_id
        for batch in connector.retrieve_all_slim_docs(callback=callback)
        for item in batch
    ]


def test_slim_walk_lists_the_files_indexing_admits_without_the_window() -> None:
    connector, _ = _connector(
        {
            "": [
                _folder("Projects"),
                _folder("Private"),
                _file("old.txt", written=OLD),
                _file("drawing.dwg"),
                _file("~$lock.docx"),
            ],
            "Projects": [_file("plan.txt")],
            "Private": SmbAccessDeniedError("denied"),
        }
    )

    assert set(_slim(connector)) == {
        ROOT_ID,
        f"{ROOT_ID}/Projects",
        f"{ROOT_ID}/Private",
        f"{ROOT_ID}/old.txt",
        f"{ROOT_ID}/Projects/plan.txt",
    }


@pytest.mark.parametrize(
    "error",
    [SmbNotFoundError("gone"), SmbRequestError("server error", status_code=None)],
)
def test_slim_walk_raises_on_a_listing_error_so_pruning_deletes_nothing(
    error: Exception,
) -> None:
    connector, _ = _connector({"": [_folder("Projects")], "Projects": error})

    with pytest.raises(type(error)):
        _slim(connector)


def test_slim_walk_raises_on_the_stop_signal() -> None:
    connector, _ = _connector({"": [_file("a.txt")]})
    callback = MagicMock()
    callback.should_stop.return_value = True

    with pytest.raises(RuntimeError, match="stop signal"):
        _slim(connector, callback)


def test_reindex_reads_a_failed_file_again_and_rejects_other_shares() -> None:
    connector, ops = _connector({}, path_prefix="Projects")
    ops.stat.side_effect = lambda *, path: _file(path.rsplit("/", 1)[-1])

    def failure(document_id: str) -> ConnectorFailure:
        return ConnectorFailure(
            failed_document=DocumentFailure(document_id=document_id),
            failure_message="failed",
        )

    items = list(
        connector.reindex(
            [
                failure(f"{ROOT_ID}/Projects/Alpha/plan.txt"),
                failure(f"{ROOT_ID}/Other/plan.txt"),
                failure("smb://files.example.com/Other/Projects/plan.txt"),
            ]
        )
    )

    assert [item.id for item in items if isinstance(item, Document)] == [
        f"{ROOT_ID}/Projects/Alpha/plan.txt"
    ]
    assert len([item for item in items if isinstance(item, ConnectorFailure)]) == 2
    assert [item.raw_node_id for item in items if isinstance(item, HierarchyNode)] == [
        ROOT_ID,
        f"{ROOT_ID}/Projects",
        f"{ROOT_ID}/Projects/Alpha",
    ]
