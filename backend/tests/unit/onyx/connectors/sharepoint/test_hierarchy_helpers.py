"""Unit tests for SharePoint connector hierarchy helper functions."""

from __future__ import annotations

from onyx.connectors.sharepoint.connector import SharepointConnector


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
