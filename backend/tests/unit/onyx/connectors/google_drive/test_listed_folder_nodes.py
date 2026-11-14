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
    assert listing.unresolved_parent_emails == {"top": _LISTER}


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
