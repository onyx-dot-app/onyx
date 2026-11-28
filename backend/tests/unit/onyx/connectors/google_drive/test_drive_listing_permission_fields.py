"""Which listings ask Drive for permissions, and what the stub listing does
without them.

Inline indexing and pruning apply the link-only filter at the listing, so they
ask for permissions when the filter is on. The stub listing never asks:
conversion reads every permission. With permission sync, the stub listing
still gives each folder node its permissions."""

from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from onyx.access.models import ExternalAccess
from onyx.connectors.google_drive.connector import GoogleDriveConnector
from onyx.connectors.google_drive.constants import DRIVE_FOLDER_TYPE
from onyx.connectors.google_drive.file_retrieval import DriveFileFieldType
from onyx.connectors.google_drive.models import (
    DriveListingState,
    GoogleDriveCheckpoint,
    RetrievedDriveFile,
)
from onyx.connectors.google_drive.source_operations import GoogleDriveSourceOperations
from onyx.connectors.models import HierarchyNode, SlimDocumentStub

_CONN_MODULE = "onyx.connectors.google_drive.connector"
_ADMIN = "admin@example.com"
_LISTER = "lister@example.com"


class _ListerBuilt(Exception):
    pass


def _connector(exclude_domain_link_only: bool = False) -> GoogleDriveConnector:
    connector = GoogleDriveConnector(
        include_my_drives=True, exclude_domain_link_only=exclude_domain_link_only
    )
    connector._ops = MagicMock(spec=GoogleDriveSourceOperations)
    connector._primary_admin_email = _ADMIN
    return connector


def _checkpoint(connector: GoogleDriveConnector) -> GoogleDriveCheckpoint:
    checkpoint = connector.build_dummy_checkpoint()
    checkpoint.listing = DriveListingState(window_t0=0, window_t1=1)
    return checkpoint


def _listing_field_type(
    connector: GoogleDriveConnector, **kwargs: bool
) -> DriveFileFieldType:
    with patch(
        f"{_CONN_MODULE}.ParallelDriveLister", side_effect=_ListerBuilt
    ) as lister:
        with pytest.raises(_ListerBuilt):
            list(connector._fetch_drive_items(_checkpoint(connector), **kwargs))
    return lister.call_args.kwargs["field_type"]


@pytest.mark.parametrize("inline", [True, False])
def test_the_link_only_filter_asks_the_listing_for_permissions(inline: bool) -> None:
    connector = _connector(exclude_domain_link_only=True)
    assert (
        _listing_field_type(connector, include_permissions=False, inline=inline)
        == DriveFileFieldType.WITH_PERMISSIONS
    )


def test_a_listing_with_no_filter_and_no_sync_asks_for_no_permissions() -> None:
    assert (
        _listing_field_type(_connector(), include_permissions=False)
        == DriveFileFieldType.STANDARD
    )


@pytest.mark.parametrize("exclude_domain_link_only", [True, False])
def test_the_stub_listing_asks_for_no_permissions(
    exclude_domain_link_only: bool,
) -> None:
    connector = _connector(exclude_domain_link_only=exclude_domain_link_only)
    assert (
        _listing_field_type(
            connector, include_permissions=True, permissions_read_later=True
        )
        == DriveFileFieldType.STANDARD
    )


def _stub_listing(
    connector: GoogleDriveConnector,
    folder: dict[str, Any],
    file: dict[str, Any],
    include_permissions: bool = True,
) -> tuple[list[HierarchyNode], list[SlimDocumentStub], list[Any], list[Any]]:
    checkpoint = _checkpoint(connector)
    listed = [
        RetrievedDriveFile(drive_file=folder, user_email=_LISTER),
        RetrievedDriveFile(drive_file=file, user_email=_LISTER),
    ]
    stub_contexts: list[Any] = []
    folder_access_inputs: list[Any] = []

    def build_stub(
        _ops: object, drive_file: dict[str, Any], ctx: Any, *_: object
    ) -> SlimDocumentStub:
        stub_contexts.append(ctx)
        return SlimDocumentStub(id=str(drive_file["id"]))

    def folder_access(drive_file: dict[str, Any], *_: object) -> ExternalAccess:
        folder_access_inputs.append(drive_file)
        return ExternalAccess(
            external_user_emails={"member@example.com"},
            external_user_group_ids=set(),
            is_public=False,
        )

    with (
        patch.object(connector, "_plan_listing", return_value=checkpoint.listing),
        patch.object(connector, "_fetch_drive_items", return_value=(f for f in listed)),
        patch.object(connector, "_stub_listing_facts", return_value=(None, [])),
        patch(f"{_CONN_MODULE}.build_slim_document_stub", side_effect=build_stub),
        patch(
            f"{_CONN_MODULE}.get_external_access_for_folder",
            side_effect=folder_access,
        ),
    ):
        items = list(
            connector.retrieve_slim_docs_from_checkpoint(
                0, 1, checkpoint, include_permissions=include_permissions
            )
        )
    nodes = [item for item in items if isinstance(item, HierarchyNode)]
    stubs = [item for item in items if isinstance(item, SlimDocumentStub)]
    return nodes, stubs, stub_contexts, folder_access_inputs


_FOLDER: dict[str, Any] = {
    "id": "folder-1",
    "name": "Private",
    "mimeType": DRIVE_FOLDER_TYPE,
}
_FILE: dict[str, Any] = {
    "id": "file-1",
    "name": "notes.txt",
    "mimeType": "text/plain",
    "parents": ["folder-1"],
}


def test_the_stub_listing_gives_folder_nodes_their_permissions() -> None:
    """With permission sync, a folder listed with no permissions gets its
    permission ids from a read as the user who listed it. The node is not
    public. The file stub gets no permissions: conversion reads them."""
    connector = _connector()
    ops = MagicMock(spec=GoogleDriveSourceOperations)
    ops.get_file.return_value = {"id": "folder-1", "permissionIds": ["p1"]}
    connector._ops = ops

    nodes, stubs, stub_contexts, folder_access_inputs = _stub_listing(
        connector, dict(_FOLDER), dict(_FILE)
    )

    assert [node.raw_node_id for node in nodes] == ["folder-1"]
    assert nodes[0].external_access is not None
    assert not nodes[0].external_access.is_public
    assert ops.get_file.call_args.kwargs["user_email"] == _LISTER
    assert folder_access_inputs[0]["permissionIds"] == ["p1"]
    assert [stub.id for stub in stubs] == ["file-1"]
    assert stub_contexts == [None]


def test_a_folder_whose_permissions_cannot_be_read_keeps_its_stored_access() -> None:
    """The read of the folder's permission ids fails. The node has no access
    value, so the stored access stays: an unread access is never written as
    no access or as public."""
    connector = _connector()
    ops = MagicMock(spec=GoogleDriveSourceOperations)
    ops.get_file.return_value = None
    connector._ops = ops

    nodes, _, _, folder_access_inputs = _stub_listing(
        connector, dict(_FOLDER), dict(_FILE)
    )

    assert nodes[0].external_access is None
    assert folder_access_inputs == []


def test_a_folder_listed_without_permission_sync_keeps_its_stored_access() -> None:
    """Without permission sync, the node has no access value, so the stored
    access stays. The listing reads no folder permissions."""
    connector = _connector()
    ops = MagicMock(spec=GoogleDriveSourceOperations)
    connector._ops = ops

    nodes, _, _, folder_access_inputs = _stub_listing(
        connector, dict(_FOLDER), dict(_FILE), include_permissions=False
    )

    assert [node.raw_node_id for node in nodes] == ["folder-1"]
    assert nodes[0].external_access is None
    ops.get_file.assert_not_called()
    assert folder_access_inputs == []
