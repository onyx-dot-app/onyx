"""Unit tests for SharePoint connector hierarchy helper functions."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from onyx.access.models import ExternalAccess
from onyx.connectors.microsoft_utils.drive_items import (
    DriveFolderReference,
    DriveItemData,
    resolve_drive_folder,
)
from onyx.connectors.models import HierarchyNode
from onyx.connectors.sharepoint.connector import (
    FetchedDriveItem,
    SharepointConnector,
    SharepointConnectorCheckpoint,
    SiteDescriptor,
    SiteDrive,
)
from onyx.db.enums import HierarchyNodeType


def test_resolve_drive_folder_requests_canonical_web_url() -> None:
    client = MagicMock(graph_api_base="https://graph.microsoft.com/v1.0")
    client.get_json.return_value = {
        "id": "folder-id",
        "webUrl": "https://tenant.sharepoint.com/sites/eng/Docs/Canonical",
    }

    folder = resolve_drive_folder(client, "drive-id", "Configured Folder")

    assert folder.web_url.endswith("/Canonical")
    client.get_json.assert_called_once_with(
        "https://graph.microsoft.com/v1.0/drives/drive-id/root:/Configured%20Folder",
        {"$select": "id,webUrl"},
    )


@patch(
    "onyx.connectors.sharepoint.connector.get_sharepoint_hierarchy_node_external_access"
)
def test_hierarchy_helpers_fetch_permissions_when_requested(
    mock_get_access: MagicMock,
) -> None:
    access = ExternalAccess(
        external_user_emails={"user@contoso.com"},
        external_user_group_ids={"sharepoint_group"},
        is_public=False,
    )
    mock_get_access.return_value = access
    connector = SharepointConnector()
    connector._graph_client = MagicMock()
    checkpoint = SharepointConnectorCheckpoint(has_more=True)
    site_url = "https://contoso.sharepoint.com/sites/eng"
    drive_url = f"{site_url}/Shared%20Documents"
    drive = SiteDrive(
        drive_id="drive-id",
        list_id="list-id",
        display_name="Documents",
        web_url=drive_url,
    )

    with patch.object(
        connector,
        "_create_rest_client_context",
        return_value=MagicMock(),
    ):
        site_node = next(
            connector._yield_site_hierarchy_node(
                SiteDescriptor(url=site_url, drive_name=None, folder_path=None),
                checkpoint,
                include_permissions=True,
            )
        )
        drive_node = next(
            connector._yield_drive_hierarchy_node(
                site_url,
                drive,
                checkpoint,
                include_permissions=True,
            )
        )
        folder_node = next(
            connector._yield_folder_hierarchy_nodes(
                site_url,
                drive,
                "Engineering",
                checkpoint,
                include_permissions=True,
            )
        )

    assert site_node.external_access is access
    assert drive_node.external_access is access
    assert folder_node.external_access is access
    assert [call.args[3] for call in mock_get_access.call_args_list] == [
        HierarchyNodeType.SITE,
        HierarchyNodeType.DRIVE,
        HierarchyNodeType.FOLDER,
    ]


@patch(
    "onyx.connectors.sharepoint.connector.get_sharepoint_hierarchy_node_external_access"
)
def test_folder_permissions_use_library_url_not_display_name(
    mock_get_access: MagicMock,
) -> None:
    """SharePoint strips "&" from the library URL, so "R&D Docs" lives at "RD Docs"."""
    mock_get_access.return_value = ExternalAccess.empty()
    connector = SharepointConnector()
    connector._graph_client = MagicMock()
    site_url = "https://contoso.sharepoint.com/sites/eng"
    drive = SiteDrive(
        drive_id="drive-id",
        list_id="list-id",
        display_name="R&D Docs",
        web_url=f"{site_url}/RD%20Docs",
    )
    checkpoint = SharepointConnectorCheckpoint(
        has_more=True,
        current_site_descriptor=SiteDescriptor(
            url=site_url,
            drive_name="RD Docs",
            folder_path="Plans/Q1%20%26%20Q2",
        ),
        current_folder=DriveFolderReference(
            id="folder-id",
            web_url=f"{site_url}/RD%20Docs/Plans/Canonical-Q1",
        ),
    )

    with patch.object(
        connector, "_create_rest_client_context", return_value=MagicMock()
    ):
        nodes = list(
            connector._yield_folder_hierarchy_nodes(
                site_url,
                drive,
                "Plans/Q1%20%26%20Q2",
                checkpoint,
                include_permissions=True,
            )
        )

    assert [
        call.kwargs["folder_server_relative_path"]
        for call in mock_get_access.call_args_list
    ] == ["/sites/eng/RD Docs/Plans", "/sites/eng/RD Docs/Plans/Q1 & Q2"]
    assert [node.raw_node_id for node in nodes] == [
        f"{site_url}/RD%20Docs/Plans",
        f"{site_url}/RD%20Docs/Plans/Canonical-Q1",
    ]


def test_full_and_slim_folder_hierarchy_use_canonical_url() -> None:
    site_url = "https://contoso.sharepoint.com/sites/eng"
    site = SiteDescriptor(
        url=site_url,
        drive_name="Shared Documents",
        folder_path="engineering/R%26D Plans",
    )
    drive = SiteDrive(
        drive_id="drive-id",
        list_id="list-id",
        display_name="Documents",
        web_url=f"{site_url}/Shared%20Documents",
    )
    folder = DriveFolderReference(
        id="folder-id",
        web_url=f"{site_url}/Shared%20Documents/Engineering/R%26D%20Plans",
    )
    driveitem = DriveItemData(
        id="item-id",
        name="design.pdf",
        web_url=f"{folder.web_url}/design.pdf",
        parent_reference_path="/drives/drive-id/root:/Engineering/R&D%20Plans",
        drive_id=drive.drive_id,
    )
    connector = SharepointConnector(
        include_site_pages=False,
        include_site_documents=True,
    )
    connector.site_descriptors = [site]
    connector._graph_client = MagicMock()

    full_checkpoint = SharepointConnectorCheckpoint(
        has_more=True,
        current_site_descriptor=site,
        current_folder=folder,
    )
    full_nodes = list(
        connector._yield_folder_hierarchy_nodes(
            site_url,
            drive,
            "Engineering/R&D%20Plans",
            full_checkpoint,
        )
    )

    fetched = FetchedDriveItem(
        driveitem=driveitem,
        drive=drive,
        configured_folder=folder,
    )
    with patch.object(connector, "_fetch_driveitems", return_value=[fetched]):
        slim_nodes = [
            item
            for batch in connector._fetch_slim_documents_from_sharepoint(
                include_permissions=False
            )
            for item in batch
            if isinstance(item, HierarchyNode)
            and item.node_type == HierarchyNodeType.FOLDER
        ]

    assert [
        (node.raw_node_id, node.raw_parent_id, node.link) for node in slim_nodes
    ] == [(node.raw_node_id, node.raw_parent_id, node.link) for node in full_nodes]
    assert slim_nodes[-1].raw_node_id == folder.web_url
