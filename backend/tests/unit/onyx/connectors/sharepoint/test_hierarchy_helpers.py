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
