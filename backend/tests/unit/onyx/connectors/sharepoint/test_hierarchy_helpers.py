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
