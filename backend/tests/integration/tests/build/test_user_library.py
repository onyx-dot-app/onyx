"""
Integration tests for the User Library API.

Tests the CRUD operations for user-uploaded raw files in Craft.
"""

import io
import zipfile

import requests

from tests.integration.common_utils.managers.user import UserManager
from tests.integration.common_utils.test_models import DATestUser

API_SERVER_URL = "http://localhost:3000"


def _get_user_library_tree(user: DATestUser) -> list[dict]:
    """Get the user's library tree (returns a flat list of entries)."""
    response = requests.get(
        f"{API_SERVER_URL}/api/build/user-library/tree",
        headers=user.headers,
    )
    response.raise_for_status()
    return response.json()


def _upload_files(user: DATestUser, path: str, files: list[tuple[str, bytes]]) -> dict:
    """Upload files to the user library."""
    multipart_files = [("files", (name, content)) for name, content in files]
    response = requests.post(
        f"{API_SERVER_URL}/api/build/user-library/upload",
        headers=user.headers,
        data={"path": path},
        files=multipart_files,
    )
    response.raise_for_status()
    return response.json()


def _upload_zip(user: DATestUser, path: str, zip_data: bytes) -> dict:
    """Upload and extract a zip file."""
    response = requests.post(
        f"{API_SERVER_URL}/api/build/user-library/upload-zip",
        headers=user.headers,
        data={"path": path},
        files={"file": ("archive.zip", zip_data)},
    )
    response.raise_for_status()
    return response.json()


def _create_directory(user: DATestUser, name: str, parent_path: str = "/") -> dict:
    """Create a directory in the user library."""
    response = requests.post(
        f"{API_SERVER_URL}/api/build/user-library/directories",
        headers=user.headers,
        json={"name": name, "parent_path": parent_path},
    )
    response.raise_for_status()
    return response.json()


def _toggle_sync(user: DATestUser, document_id: str, enabled: bool) -> None:
    """Toggle sync status for a file."""
    response = requests.patch(
        f"{API_SERVER_URL}/api/build/user-library/files/{document_id}/toggle",
        headers=user.headers,
        params={"enabled": str(enabled).lower()},
    )
    response.raise_for_status()


def _delete_file(user: DATestUser, document_id: str) -> None:
    """Delete a file from the user library."""
    response = requests.delete(
        f"{API_SERVER_URL}/api/build/user-library/files/{document_id}",
        headers=user.headers,
    )
    response.raise_for_status()


def test_user_library_upload_file(reset: None) -> None:  # noqa: ARG001
    """Test uploading a single file to the user library."""
    admin_user: DATestUser = UserManager.create(name="admin_user")

    # Upload a simple CSV file
    csv_content = b"name,value\nfoo,1\nbar,2"
    result = _upload_files(admin_user, "/", [("data.csv", csv_content)])

    assert "entries" in result
    assert len(result["entries"]) == 1
    assert result["entries"][0]["name"] == "data.csv"
    assert result["entries"][0]["sync_enabled"] is True

    # Verify it appears in the tree
    tree = _get_user_library_tree(admin_user)
    assert any(entry["name"] == "data.csv" for entry in tree)


def test_user_library_upload_to_directory(reset: None) -> None:  # noqa: ARG001
    """Test uploading files to a specific directory path."""
    admin_user: DATestUser = UserManager.create(name="admin_user")

    # Create a directory first
    _create_directory(admin_user, "reports")

    # Upload to that directory
    xlsx_content = b"fake xlsx content"
    result = _upload_files(admin_user, "/reports", [("quarterly.xlsx", xlsx_content)])

    assert len(result["entries"]) == 1
    assert result["entries"][0]["path"] == "/reports/quarterly.xlsx"


def test_user_library_upload_zip(reset: None) -> None:  # noqa: ARG001
    """Test uploading and extracting a zip file."""
    admin_user: DATestUser = UserManager.create(name="admin_user")

    # Create an in-memory zip file
    zip_buffer = io.BytesIO()
    with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("folder/file1.txt", "content1")
        zf.writestr("folder/file2.txt", "content2")
        zf.writestr("root.txt", "root content")
    zip_buffer.seek(0)

    result = _upload_zip(admin_user, "/", zip_buffer.read())

    # Should have 3 files extracted
    assert "entries" in result
    assert len(result["entries"]) >= 3


def test_user_library_create_directory(reset: None) -> None:  # noqa: ARG001
    """Test creating a directory."""
    admin_user: DATestUser = UserManager.create(name="admin_user")

    result = _create_directory(admin_user, "my-data")

    assert result["is_directory"] is True
    assert result["name"] == "my-data"

    # Verify in tree
    tree = _get_user_library_tree(admin_user)
    assert any(entry["name"] == "my-data" for entry in tree)


def test_user_library_toggle_sync(reset: None) -> None:  # noqa: ARG001
    """Test toggling sync status for a file."""
    admin_user: DATestUser = UserManager.create(name="admin_user")

    # Upload a file
    result = _upload_files(admin_user, "/", [("test.txt", b"hello")])
    document_id = result["entries"][0]["id"]

    # Initially sync is enabled
    assert result["entries"][0]["sync_enabled"] is True

    # Disable sync
    _toggle_sync(admin_user, document_id, False)

    # Verify sync is disabled
    tree = _get_user_library_tree(admin_user)
    entry = next((e for e in tree if e["id"] == document_id), None)
    assert entry is not None
    assert entry["sync_enabled"] is False


def test_user_library_delete_file(reset: None) -> None:  # noqa: ARG001
    """Test deleting a file."""
    admin_user: DATestUser = UserManager.create(name="admin_user")

    # Upload a file
    result = _upload_files(admin_user, "/", [("delete-me.txt", b"temp")])
    document_id = result["entries"][0]["id"]

    # Delete it
    _delete_file(admin_user, document_id)

    # Verify it's gone
    tree = _get_user_library_tree(admin_user)
    assert not any(entry["id"] == document_id for entry in tree)


def test_user_library_isolation_between_users(reset: None) -> None:  # noqa: ARG001
    """Test that users can only see their own files."""
    admin_user: DATestUser = UserManager.create(name="admin_user")
    other_user: DATestUser = UserManager.create(name="other_user")

    # Admin uploads a file
    _upload_files(admin_user, "/", [("admin-file.txt", b"admin data")])

    # Other user uploads a file
    _upload_files(other_user, "/", [("other-file.txt", b"other data")])

    # Admin should only see their file
    admin_tree = _get_user_library_tree(admin_user)
    assert any(e["name"] == "admin-file.txt" for e in admin_tree)
    assert not any(e["name"] == "other-file.txt" for e in admin_tree)

    # Other user should only see their file
    other_tree = _get_user_library_tree(other_user)
    assert any(e["name"] == "other-file.txt" for e in other_tree)
    assert not any(e["name"] == "admin-file.txt" for e in other_tree)
