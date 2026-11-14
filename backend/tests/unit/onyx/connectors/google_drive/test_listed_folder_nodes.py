"""Hierarchy nodes from the folder shards of the parallel listing. A folder
that one user lists with no parent gets its parent from a later copy or from
a read after the listing. A folder shared only by link is a node only as the
parent of another node."""

from typing import Any

import pytest

from onyx.connectors.google_drive.connector import GoogleDriveConnector
from onyx.connectors.google_drive.constants import DRIVE_FOLDER_TYPE
from onyx.connectors.google_drive.models import (
    DriveListingState,
    DriveRetrievalStage,
    GoogleDriveCheckpoint,
    GoogleDriveFileType,
    RetrievedDriveFile,
)
from onyx.connectors.models import HierarchyNode

_LISTER = "user1@x.com"


def _connector(exclude_domain_link_only: bool = False) -> GoogleDriveConnector:
    return GoogleDriveConnector(
        include_shared_drives=True,
        exclude_domain_link_only=exclude_domain_link_only,
    )


def _checkpoint(connector: GoogleDriveConnector) -> GoogleDriveCheckpoint:
    checkpoint = connector.build_dummy_checkpoint()
    checkpoint.listing = DriveListingState(window_t0=0, window_t1=1)
    return checkpoint


def _folder(
    folder_id: str, parent_id: str | None = None, link_only: bool = False
) -> RetrievedDriveFile:
    drive_file: GoogleDriveFileType = {
        "id": folder_id,
        "name": folder_id,
        "mimeType": DRIVE_FOLDER_TYPE,
    }
    if parent_id is not None:
        drive_file["parents"] = [parent_id]
    if link_only:
        drive_file["permissions"] = [
            {"type": "domain", "role": "reader", "allowFileDiscovery": False}
        ]
    return RetrievedDriveFile(
        completion_stage=DriveRetrievalStage.SHARED_DRIVE_FILES,
        drive_file=drive_file,
        user_email=_LISTER,
    )


def _nodes(
    connector: GoogleDriveConnector,
    checkpoint: GoogleDriveCheckpoint,
    folders: list[RetrievedDriveFile],
) -> list[HierarchyNode]:
    listing = checkpoint.listing
    assert listing is not None
    return connector._listed_folder_nodes(
        listing, checkpoint, folders, [], None, add_prefix=False
    )


def test_a_later_copy_gives_a_parentless_folder_its_parent() -> None:
    connector = _connector()
    checkpoint = _checkpoint(connector)

    first = _nodes(connector, checkpoint, [_folder("shared")])
    again = _nodes(connector, checkpoint, [_folder("shared")])
    repaired = _nodes(connector, checkpoint, [_folder("shared", parent_id="top")])

    assert [(node.raw_node_id, node.raw_parent_id) for node in first] == [
        ("shared", None)
    ]
    assert again == []
    assert [(node.raw_node_id, node.raw_parent_id) for node in repaired] == [
        ("shared", "top")
    ]
    listing = checkpoint.listing
    assert listing is not None
    assert listing.parentless_folder_emails == {}
    # The parent is read after the listing.
    assert listing.unresolved_parent_emails == {"top": [_LISTER]}


def test_a_read_after_the_listing_gives_a_parentless_folder_its_parent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connector = _connector()
    checkpoint = _checkpoint(connector)
    _nodes(connector, checkpoint, [_folder("shared")])
    folders: dict[str, GoogleDriveFileType] = {
        "shared": _folder("shared", parent_id="top").drive_file,
        "top": _folder("top").drive_file,
    }

    def read_folder(
        _self: GoogleDriveConnector, folder_id: str, *_args: Any, **_kwargs: Any
    ) -> GoogleDriveFileType | None:
        return folders.get(folder_id)

    monkeypatch.setattr(GoogleDriveConnector, "_get_folder_metadata", read_folder)
    monkeypatch.setattr(GoogleDriveConnector, "_is_my_drive_root", lambda *_args: False)

    batches = list(
        connector._resolve_unlisted_parents(
            checkpoint, include_permissions=False, add_prefix=False
        )
    )

    nodes = [
        (node.raw_node_id, node.raw_parent_id) for batch in batches for node in batch
    ]
    assert nodes == [("shared", "top"), ("top", None)]
    listing = checkpoint.listing
    assert listing is not None
    assert listing.parentless_folder_emails == {}
    assert listing.unresolved_parent_emails == {}


def test_a_link_only_folder_is_a_node_only_as_a_parent() -> None:
    connector = _connector(exclude_domain_link_only=True)
    checkpoint = _checkpoint(connector)

    nodes = _nodes(
        connector,
        checkpoint,
        [
            _folder("link_only", parent_id="top", link_only=True),
            _folder("child", parent_id="link_only"),
        ],
    )

    assert [node.raw_node_id for node in nodes] == ["child"]
    listing = checkpoint.listing
    assert listing is not None
    # The read after the listing yields it, as the parent of "child".
    assert "link_only" in listing.unresolved_parent_emails
    assert "link_only" not in checkpoint.seen_hierarchy_node_raw_ids


def _file_under(parent_id: str, user_email: str) -> RetrievedDriveFile:
    return RetrievedDriveFile(
        completion_stage=DriveRetrievalStage.MY_DRIVE_FILES,
        drive_file={"id": f"file_of_{user_email}", "parents": [parent_id]},
        user_email=user_email,
    )


def test_an_unlisted_parent_is_read_as_a_later_user_who_can_read_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Two users see a file under the same unlisted parent. The first one
    cannot read the parent, and the admin cannot. The second one can."""
    connector = _connector()
    checkpoint = _checkpoint(connector)
    listing = checkpoint.listing
    assert listing is not None
    connector._listed_folder_nodes(
        listing,
        checkpoint,
        [],
        [_file_under("parent", "first@x.com"), _file_under("parent", "second@x.com")],
        None,
        add_prefix=False,
    )
    assert listing.unresolved_parent_emails == {
        "parent": ["first@x.com", "second@x.com"]
    }
    read_as: list[str] = []

    def read_folder(
        _self: GoogleDriveConnector,
        folder_id: str,
        retriever_email: str,
        *_args: Any,
        **_kwargs: Any,
    ) -> GoogleDriveFileType | None:
        read_as.append(retriever_email)
        if retriever_email != "second@x.com":
            return None
        return _folder(folder_id).drive_file

    monkeypatch.setattr(GoogleDriveConnector, "_get_folder_metadata", read_folder)
    monkeypatch.setattr(GoogleDriveConnector, "_is_my_drive_root", lambda *_args: True)

    batches = list(
        connector._resolve_unlisted_parents(
            checkpoint, include_permissions=False, add_prefix=False
        )
    )

    assert [node.raw_node_id for batch in batches for node in batch] == ["parent"]
    assert read_as == ["first@x.com", "second@x.com"]


def test_a_read_round_with_no_node_still_yields_a_batch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The consumer checks its stop signal for each batch, so a round in
    which no folder can be read must give it one."""
    connector = _connector()
    checkpoint = _checkpoint(connector)
    _nodes(connector, checkpoint, [_folder("shared")])
    monkeypatch.setattr(
        GoogleDriveConnector, "_get_folder_metadata", lambda *_args, **_kwargs: None
    )

    batches = list(
        connector._resolve_unlisted_parents(
            checkpoint, include_permissions=False, add_prefix=False
        )
    )

    assert batches == [[]]


def test_a_checkpoint_with_one_reader_for_each_parent_still_loads() -> None:
    state = DriveListingState.model_validate(
        {"window_t0": 0, "window_t1": 1, "unresolved_parent_emails": {"top": _LISTER}}
    )

    assert state.unresolved_parent_emails == {"top": [_LISTER]}
