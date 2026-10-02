"""Unit tests for SharePoint connector hierarchy helper functions."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from onyx.access.models import ExternalAccess
from onyx.connectors.sharepoint.connector import (
    SharepointConnector,
    SharepointConnectorCheckpoint,
    SiteDescriptor,
)
from onyx.db.enums import HierarchyNodeType


def test_extract_folder_path_from_parent_reference_with_folder() -> None:
    """Test extracting folder path when file is in a folder."""
    connector = SharepointConnector()

    # Standard path format: /drives/{drive_id}/root:/folder/path
    path = "/drives/b!abc123def456/root:/Engineering/API"
    result = connector._extract_folder_path_from_parent_reference(path)
    assert result == "Engineering/API"


def test_extract_folder_path_from_parent_reference_nested_folder() -> None:
    """Test extracting folder path from deeply nested folders."""
    connector = SharepointConnector()

    path = "/drives/b!xyz789/root:/Documents/Project/2025/Q1"
    result = connector._extract_folder_path_from_parent_reference(path)
    assert result == "Documents/Project/2025/Q1"


def test_extract_folder_path_from_parent_reference_at_root() -> None:
    """Test extracting folder path when file is at drive root."""
    connector = SharepointConnector()

    # File at root: path ends with "root:" or "root:/"
    path = "/drives/b!abc123/root:"
    result = connector._extract_folder_path_from_parent_reference(path)
    assert result is None


def test_extract_folder_path_from_parent_reference_at_root_with_slash() -> None:
    """Test extracting folder path when file is at drive root (with trailing slash)."""
    connector = SharepointConnector()

    path = "/drives/b!abc123/root:/"
    result = connector._extract_folder_path_from_parent_reference(path)
    assert result is None


def test_extract_folder_path_from_parent_reference_none() -> None:
    """Test extracting folder path when path is None."""
    connector = SharepointConnector()

    result = connector._extract_folder_path_from_parent_reference(None)
    assert result is None


def test_extract_folder_path_from_parent_reference_empty() -> None:
    """Test extracting folder path when path is empty."""
    connector = SharepointConnector()

    result = connector._extract_folder_path_from_parent_reference("")
    assert result is None


def test_extract_folder_path_from_parent_reference_no_root() -> None:
    """Test extracting folder path when path doesn't contain root:/."""
    connector = SharepointConnector()

    # Unusual path format without root:/
    path = "/drives/b!abc123/items/folder"
    result = connector._extract_folder_path_from_parent_reference(path)
    assert result is None


def test_build_folder_url_simple() -> None:
    """Test building folder URL with simple folder path."""
    connector = SharepointConnector()

    site_url = "https://company.sharepoint.com/sites/eng"
    drive_name = "Shared Documents"
    folder_path = "Engineering"

    result = connector._build_folder_url(site_url, drive_name, folder_path)
    expected = "https://company.sharepoint.com/sites/eng/Shared Documents/Engineering"
    assert result == expected


def test_build_folder_url_nested() -> None:
    """Test building folder URL with nested folder path."""
    connector = SharepointConnector()

    site_url = "https://company.sharepoint.com/sites/eng"
    drive_name = "Shared Documents"
    folder_path = "Engineering/API/v2"

    result = connector._build_folder_url(site_url, drive_name, folder_path)
    expected = (
        "https://company.sharepoint.com/sites/eng/Shared Documents/Engineering/API/v2"
    )
    assert result == expected


def test_build_folder_url_with_spaces() -> None:
    """Test building folder URL with spaces in folder path."""
    connector = SharepointConnector()

    site_url = "https://company.sharepoint.com/sites/eng"
    drive_name = "Shared Documents"
    folder_path = "Engineering/API Docs/Version 2"

    result = connector._build_folder_url(site_url, drive_name, folder_path)
    expected = "https://company.sharepoint.com/sites/eng/Shared Documents/Engineering/API Docs/Version 2"
    assert result == expected


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
                drive_url,
                "Shared Documents",
                checkpoint,
                include_permissions=True,
            )
        )
        folder_node = next(
            connector._yield_folder_hierarchy_nodes(
                site_url,
                drive_url,
                "Shared Documents",
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

    with patch.object(
        connector, "_create_rest_client_context", return_value=MagicMock()
    ):
        nodes = list(
            connector._yield_folder_hierarchy_nodes(
                site_url,
                f"{site_url}/RD%20Docs",
                "R&D Docs",
                "Plans/Q1%20%26%20Q2",
                SharepointConnectorCheckpoint(has_more=True),
                include_permissions=True,
            )
        )

    assert [
        call.kwargs["folder_server_relative_path"]
        for call in mock_get_access.call_args_list
    ] == ["/sites/eng/RD Docs/Plans", "/sites/eng/RD Docs/Plans/Q1 & Q2"]
    assert [node.raw_node_id for node in nodes] == [
        f"{site_url}/R&D Docs/Plans",
        f"{site_url}/R&D Docs/Plans/Q1%20%26%20Q2",
    ]


SITE_URL = "https://contoso.sharepoint.com/sites/eng"
DRIVE_URL = f"{SITE_URL}/Shared%20Documents"


@patch(
    "onyx.connectors.sharepoint.connector.get_sharepoint_hierarchy_node_external_access"
)
def test_drive_node_permissions_use_drive_list_id(mock_get_access: MagicMock) -> None:
    access = ExternalAccess.empty()
    mock_get_access.return_value = access
    connector = SharepointConnector()
    connector._graph_client = MagicMock()

    with (
        patch.object(
            connector, "_create_rest_client_context", return_value=MagicMock()
        ),
        patch.object(
            connector, "_graph_api_get_json", return_value={"id": "list-guid"}
        ) as mock_graph_get,
    ):
        node = next(
            connector._yield_drive_hierarchy_node(
                SITE_URL,
                DRIVE_URL,
                "Documents",
                SharepointConnectorCheckpoint(has_more=True),
                include_permissions=True,
                drive_id="drive-1",
            )
        )

    assert node.external_access is access
    assert mock_get_access.call_args.kwargs["list_id"] == "list-guid"
    assert mock_graph_get.call_args.args[0].endswith("/drives/drive-1/list")


@patch(
    "onyx.connectors.sharepoint.connector.get_sharepoint_hierarchy_node_external_access"
)
def test_drive_node_permission_failure_is_not_fatal(mock_get_access: MagicMock) -> None:
    mock_get_access.side_effect = RuntimeError("List 'Documents' does not exist")
    connector = SharepointConnector()
    connector._graph_client = MagicMock()

    with (
        patch.object(
            connector, "_create_rest_client_context", return_value=MagicMock()
        ),
        patch.object(connector, "_get_drive_list_id", return_value=None),
    ):
        nodes = list(
            connector._yield_drive_hierarchy_node(
                SITE_URL,
                DRIVE_URL,
                "Documents",
                SharepointConnectorCheckpoint(has_more=True),
                include_permissions=True,
                drive_id="drive-1",
            )
        )

    assert len(nodes) == 1
    assert nodes[0].node_type == HierarchyNodeType.DRIVE
    assert nodes[0].external_access is None


def test_get_drive_list_id_caches_and_falls_back_on_error() -> None:
    connector = SharepointConnector()

    with patch.object(
        connector, "_graph_api_get_json", side_effect=[{"id": "list-guid"}, Exception]
    ) as mock_graph_get:
        assert connector._get_drive_list_id("drive-1") == "list-guid"
        assert connector._get_drive_list_id("drive-1") == "list-guid"
        assert connector._get_drive_list_id("drive-2") is None
        assert connector._get_drive_list_id("drive-2") is None
        assert connector._get_drive_list_id(None) is None

    assert mock_graph_get.call_count == 2
