"""Unit tests for the shared Graph drive-item folder-path helper."""

from __future__ import annotations

from onyx.connectors.microsoft_utils.drive_items import (
    extract_folder_path_from_parent_reference,
)


def test_extract_folder_path_from_parent_reference_with_folder() -> None:
    """Test extracting folder path when file is in a folder."""
    # Standard path format: /drives/{drive_id}/root:/folder/path
    path = "/drives/b!abc123def456/root:/Engineering/API"
    result = extract_folder_path_from_parent_reference(path)
    assert result == "Engineering/API"


def test_extract_folder_path_from_parent_reference_nested_folder() -> None:
    """Test extracting folder path from deeply nested folders."""
    path = "/drives/b!xyz789/root:/Documents/Project/2025/Q1"
    result = extract_folder_path_from_parent_reference(path)
    assert result == "Documents/Project/2025/Q1"


def test_extract_folder_path_from_parent_reference_at_root() -> None:
    """Test extracting folder path when file is at drive root."""
    # File at root: path ends with "root:" or "root:/"
    path = "/drives/b!abc123/root:"
    result = extract_folder_path_from_parent_reference(path)
    assert result is None


def test_extract_folder_path_from_parent_reference_at_root_with_slash() -> None:
    """Test extracting folder path when file is at drive root (with trailing slash)."""
    path = "/drives/b!abc123/root:/"
    result = extract_folder_path_from_parent_reference(path)
    assert result is None


def test_extract_folder_path_from_parent_reference_none() -> None:
    """Test extracting folder path when path is None."""
    result = extract_folder_path_from_parent_reference(None)
    assert result is None


def test_extract_folder_path_from_parent_reference_empty() -> None:
    """Test extracting folder path when path is empty."""
    result = extract_folder_path_from_parent_reference("")
    assert result is None


def test_extract_folder_path_from_parent_reference_no_root() -> None:
    """Test extracting folder path when path doesn't contain root:/."""
    # Unusual path format without root:/
    path = "/drives/b!abc123/items/folder"
    result = extract_folder_path_from_parent_reference(path)
    assert result is None
