"""File ops security boundary tests (HTTP boundary half)."""

from __future__ import annotations

from urllib.parse import quote
from uuid import UUID

import pytest

from onyx.server.features.build.sandbox.factory import get_sandbox_manager
from tests.integration.common_utils.constants import API_SERVER_URL
from tests.integration.common_utils.http_client import client
from tests.integration.common_utils.managers.build_session import BuildSessionManager
from tests.integration.common_utils.managers.build_session import SessionWithSandbox
from tests.integration.common_utils.test_models import DATestUser
from tests.integration.tests.craft.conftest import SharedSession


def _create_session_id(user: DATestUser) -> UUID:
    session = BuildSessionManager.create(user)
    return UUID(session.id)


def _create_session_with_sandbox(user: DATestUser) -> SessionWithSandbox:
    return BuildSessionManager.create_with_sandbox(user)


def _files_url(session_id: UUID) -> str:
    return f"{API_SERVER_URL}/build/sessions/{session_id}/files"


def _delete_file_url(session_id: UUID, path: str) -> str:
    return f"{API_SERVER_URL}/build/sessions/{session_id}/files/{path}"


def _artifact_url(session_id: UUID, path: str) -> str:
    return f"{API_SERVER_URL}/build/sessions/{session_id}/artifacts/{path}"


def _download_directory_url(session_id: UUID, path: str) -> str:
    return f"{API_SERVER_URL}/build/sessions/{session_id}/download-directory/{path}"


def _pptx_preview_url(session_id: UUID, path: str) -> str:
    return f"{API_SERVER_URL}/build/sessions/{session_id}/pptx-preview/{path}"


def _export_docx_url(session_id: UUID, path: str) -> str:
    return f"{API_SERVER_URL}/build/sessions/{session_id}/export-docx/{path}"


def _seed_file(user: DATestUser, session_id: UUID, name: str = "seed.txt") -> str:
    body = BuildSessionManager.upload_file(
        user, session_id, filename=name, content=b"seed-content"
    )
    return str(body.path)


def test_list_directory_rejects_path_traversal(
    shared_session: SharedSession,
) -> None:
    owner, session_id = shared_session
    response = client.get(
        _files_url(session_id),
        params={"path": "../etc"},
        headers=owner.headers,
        cookies=owner.cookies,
    )
    # list_directory sanitizes by stripping ".." (never raises traversal), so a
    # traversal path resolves to a missing dir and returns an empty 200 listing.
    assert response.status_code == 200
    assert response.json()["entries"] == []


def test_list_directory_returns_200_for_missing_dir(
    shared_session: SharedSession,
) -> None:
    owner, session_id = shared_session
    response = client.get(
        _files_url(session_id),
        params={"path": "definitely-not-a-real-subdir"},
        headers=owner.headers,
        cookies=owner.cookies,
    )
    assert response.status_code == 200
    body = response.json()
    assert body["entries"] == []


def test_list_directory_returns_empty_when_workspace_missing(
    shared_session: SharedSession,
) -> None:
    owner, session_id = shared_session

    response = client.get(
        _files_url(session_id),
        headers=owner.headers,
        cookies=owner.cookies,
    )
    assert response.status_code == 200
    body = response.json()
    assert "entries" in body
    assert isinstance(body["entries"], list)


def test_read_file_rejects_path_traversal(
    shared_session: SharedSession,
) -> None:
    owner, session_id = shared_session
    response = client.get(
        _artifact_url(session_id, "..%2Fetc%2Fpasswd"),
        headers=owner.headers,
        cookies=owner.cookies,
    )
    # read_file strips ".." and resolves to a missing file -> 404.
    assert response.status_code == 404


def test_delete_file_rejects_path_traversal(
    shared_session: SharedSession,
) -> None:
    owner, session_id = shared_session
    response = client.delete(
        _delete_file_url(session_id, "attachments/../../etc/passwd"),
        headers=owner.headers,
        cookies=owner.cookies,
    )
    # httpx normalizes raw "../" before sending, so the server sees a non-existent path -> 404.
    assert response.status_code == 404


def test_delete_file_rejects_url_encoded_traversal(
    shared_session: SharedSession,
) -> None:
    owner, session_id = shared_session
    response = client.delete(
        _delete_file_url(session_id, "attachments/%2e%2e/etc/passwd"),
        headers=owner.headers,
        cookies=owner.cookies,
    )
    assert response.status_code == 403


@pytest.mark.parametrize(
    "metachar",
    [";", "|", "`", "$()", "&"],
)
def test_delete_file_rejects_shell_metachars(
    shared_session: SharedSession, metachar: str
) -> None:
    owner, session_id = shared_session
    encoded = quote(f"attachments/foo{metachar}bar.txt", safe="/")
    response = client.delete(
        f"{API_SERVER_URL}/build/sessions/{session_id}/files/{encoded}",
        headers=owner.headers,
        cookies=owner.cookies,
    )
    assert response.status_code == 400


def test_delete_file_rejects_null_byte(
    shared_session: SharedSession,
) -> None:
    owner, session_id = shared_session
    response = client.delete(
        f"{API_SERVER_URL}/build/sessions/{session_id}/files/attachments/foo%00bar.txt",
        headers=owner.headers,
        cookies=owner.cookies,
    )
    assert response.status_code == 403


def test_delete_missing_file_returns_404(
    shared_session: SharedSession,
) -> None:
    owner, session_id = shared_session
    response = client.delete(
        _delete_file_url(session_id, "attachments/does-not-exist-abc123.txt"),
        headers=owner.headers,
        cookies=owner.cookies,
    )
    assert response.status_code == 404


def test_download_artifact_rejects_path_traversal(
    shared_session: SharedSession,
) -> None:
    owner, session_id = shared_session
    response = client.get(
        _artifact_url(session_id, "..%2F..%2Fetc%2Fpasswd"),
        headers=owner.headers,
        cookies=owner.cookies,
    )
    # read_file strips ".." and resolves to a missing file -> 404.
    assert response.status_code == 404


def test_upload_stats_empty_session_has_no_attachments(
    admin_user: DATestUser,
) -> None:
    session_id = _create_session_id(admin_user)

    listing = BuildSessionManager.list_files(admin_user, session_id, path="attachments")
    files = [e for e in listing.entries if not e.is_directory]
    assert files == []


def test_upload_stats_reflect_uploaded_files(admin_user: DATestUser) -> None:
    session_id = _create_session_id(admin_user)

    first = b"hello"
    second = b"world!"
    BuildSessionManager.upload_file(
        admin_user, session_id, filename="file1.txt", content=first
    )
    BuildSessionManager.upload_file(
        admin_user, session_id, filename="file2.txt", content=second
    )

    listing = BuildSessionManager.list_files(admin_user, session_id, path="attachments")
    files = [e for e in listing.entries if not e.is_directory]
    sizes_by_name = {e.name: e.size for e in files}

    assert sizes_by_name == {"file1.txt": len(first), "file2.txt": len(second)}


def test_download_directory_zip_respects_traversal_rules(
    shared_session: SharedSession,
) -> None:
    owner, session_id = shared_session
    response = client.get(
        _download_directory_url(session_id, "..%2Fetc"),
        headers=owner.headers,
        cookies=owner.cookies,
    )
    assert response.status_code == 404


def test_pptx_preview_rejects_non_pptx(
    shared_session: SharedSession,
) -> None:
    owner, session_id = shared_session
    response = client.get(
        _pptx_preview_url(session_id, "outputs/report.docx"),
        headers=owner.headers,
        cookies=owner.cookies,
    )
    assert response.status_code == 400


def test_export_docx_rejects_non_md(
    shared_session: SharedSession,
) -> None:
    owner, session_id = shared_session
    # Seed a real .txt so the endpoint reaches the extension check, not "not found".
    seed_path = _seed_file(owner, session_id, name="notes.txt")
    response = client.get(
        _export_docx_url(session_id, seed_path),
        headers=owner.headers,
        cookies=owner.cookies,
    )
    assert response.status_code == 400


def test_download_artifact_hides_opencode_json(
    admin_user: DATestUser,
) -> None:
    session_id, sandbox_id = _create_session_with_sandbox(admin_user)
    get_sandbox_manager().write_sandbox_file(
        sandbox_id,
        f"sessions/{session_id}/opencode.json",
        '{"model": "test"}',
    )

    response = client.get(
        _artifact_url(session_id, "opencode.json"),
        headers=admin_user.headers,
        cookies=admin_user.cookies,
    )
    assert response.status_code == 404


def test_list_directory_filters_hidden_entries(
    admin_user: DATestUser,
) -> None:
    session_id, sandbox_id = _create_session_with_sandbox(admin_user)
    manager = get_sandbox_manager()

    hidden_names = {".venv/keep", "node_modules/keep", "opencode.json", ".env"}
    visible_names = {"alpha.txt", "beta.txt"}

    for rel in hidden_names | visible_names:
        manager.write_sandbox_file(
            sandbox_id,
            f"sessions/{session_id}/{rel}",
            "x",
        )

    listing = BuildSessionManager.list_files(admin_user, session_id)
    names = {entry.name for entry in listing.entries}

    assert ".venv" not in names
    assert "node_modules" not in names
    assert "opencode.json" not in names
    assert ".env" not in names
    assert visible_names <= names


def test_cross_user_file_access_returns_404(
    shared_session: SharedSession, admin_user: DATestUser
) -> None:
    _owner, session_id = shared_session

    response = client.get(
        _files_url(session_id),
        headers=admin_user.headers,
        cookies=admin_user.cookies,
    )
    assert response.status_code == 404
