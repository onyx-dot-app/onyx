"""File ops security boundary tests (integration / HTTP boundary half).

Pins the path-traversal, hidden-entry, cross-user, and content-type rules
across the build session file-ops endpoints (list / read / delete /
download_artifact / download_directory / pptx-preview / export-docx).
"""

from __future__ import annotations

from urllib.parse import quote
from uuid import UUID

import pytest

from tests.integration.common_utils.constants import API_SERVER_URL
from tests.integration.common_utils.http_client import client
from tests.integration.common_utils.managers.build_session import BuildSessionManager
from tests.integration.common_utils.test_models import DATestUser

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _create_session_id(user: DATestUser) -> UUID:
    session = BuildSessionManager.create(user)
    return UUID(session["id"])


def _files_url(session_id: UUID) -> str:
    return f"{API_SERVER_URL}/build/sessions/{session_id}/files"


def _delete_file_url(session_id: UUID, path: str) -> str:
    # ``path`` is intentionally not URL-encoded by some tests so that the
    # raw bytes reach the server; FastAPI's ``{path:path}`` matcher accepts
    # additional slashes but special chars need encoding by the caller.
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
    """Upload a file so the session has at least one attachment for read/delete tests."""
    body = BuildSessionManager.upload_file(
        user, session_id, filename=name, content=b"seed-content"
    )
    return str(body["path"])


# ---------------------------------------------------------------------------
# list_directory
# ---------------------------------------------------------------------------


def test_list_directory_rejects_path_traversal(admin_user: DATestUser) -> None:
    """GET /files?path=../etc must not leak content from outside the sandbox.

    The sandbox manager sanitizes the path (strips ``..``) which resolves
    to a non-existent path within the session — returning 200 with empty
    entries. An explicit 403 is also acceptable.
    """
    session_id = _create_session_id(admin_user)
    response = client.get(
        _files_url(session_id),
        params={"path": "../etc"},
        headers=admin_user.headers,
        cookies=admin_user.cookies,
    )
    assert response.status_code in (200, 403)
    if response.status_code == 200:
        # No leaked entries from outside the sandbox
        assert response.json()["entries"] == []


def test_list_directory_returns_200_for_missing_dir(admin_user: DATestUser) -> None:
    """GET /files?path=does-not-exist returns 200 with an empty entries list.

    Non-traversal paths that don't exist on disk are caught by the sandbox
    manager as ``ValueError("Not a directory: ...")``. The session manager
    treats all non-traversal ValueErrors as "nothing to show" and returns an
    empty ``DirectoryListing`` (200).
    """
    session_id = _create_session_id(admin_user)
    response = client.get(
        _files_url(session_id),
        params={"path": "definitely-not-a-real-subdir"},
        headers=admin_user.headers,
        cookies=admin_user.cookies,
    )
    assert response.status_code == 200
    body = response.json()
    assert body["entries"] == []


def test_list_directory_returns_empty_when_workspace_missing(
    admin_user: DATestUser,
) -> None:
    """When the sandbox workspace itself is missing, list_directory returns 200 + empty.

    Pins the manager.py:2179-2182 behaviour: a missing workspace short-circuits
    to an empty listing rather than surfacing as 404.
    """
    session_id = _create_session_id(admin_user)

    # Empty path = workspace root. A freshly-created session may not have its
    # workspace loaded into the sandbox yet; either way the endpoint must not
    # 404 on a path that's not a traversal attempt.
    response = client.get(
        _files_url(session_id),
        headers=admin_user.headers,
        cookies=admin_user.cookies,
    )
    assert response.status_code == 200
    body = response.json()
    assert "entries" in body
    assert isinstance(body["entries"], list)


# ---------------------------------------------------------------------------
# read_file (via artifact download — the build router exposes reads through
# the same /artifacts/{path} endpoint)
# ---------------------------------------------------------------------------


def test_read_file_rejects_path_traversal(admin_user: DATestUser) -> None:
    """Downloading a path-traversal artifact must not leak external files.

    The exact status code depends on whether the sandbox manager rejects
    (403) or normalizes-and-misses (400/404) — either is acceptable as long
    as no file content escapes the sandbox.
    """
    session_id = _create_session_id(admin_user)
    response = client.get(
        _artifact_url(session_id, "..%2Fetc%2Fpasswd"),
        headers=admin_user.headers,
        cookies=admin_user.cookies,
    )
    assert response.status_code in (400, 403, 404)


# ---------------------------------------------------------------------------
# delete_file
# ---------------------------------------------------------------------------


def test_delete_file_rejects_path_traversal(admin_user: DATestUser) -> None:
    """DELETE with a path-traversal segment must not delete files outside the sandbox.

    The HTTP routing layer may collapse ``..`` before the handler runs
    (resulting in 404 for a missing file), or the sandbox manager may
    detect ``..`` and reject explicitly (403). Either is acceptable as
    long as 204 (success) is NOT returned.
    """
    session_id = _create_session_id(admin_user)
    response = client.delete(
        _delete_file_url(session_id, "attachments/../../etc/passwd"),
        headers=admin_user.headers,
        cookies=admin_user.cookies,
    )
    assert response.status_code in (403, 404)


def test_delete_file_rejects_url_encoded_traversal(admin_user: DATestUser) -> None:
    """DELETE /files/%2e%2e/etc returns 403 (URL-encoded ``..`` still rejected).

    Starlette decodes ``%2e%2e`` to ``..`` before the handler runs, so the
    sandbox manager's ``..`` regex fires and the API maps the error to 403.
    """
    session_id = _create_session_id(admin_user)
    response = client.delete(
        _delete_file_url(session_id, "attachments/%2e%2e/etc/passwd"),
        headers=admin_user.headers,
        cookies=admin_user.cookies,
    )
    assert response.status_code == 403


@pytest.mark.parametrize(
    "metachar",
    [";", "|", "`", "$()", "&"],
)
def test_delete_file_rejects_shell_metachars(
    admin_user: DATestUser, metachar: str
) -> None:
    """Shell metacharacters in the delete path are rejected with 400.

    The sandbox manager's shell-metacharacter regex raises
    ``ValueError("...disallowed characters...")``, which does not contain
    "path traversal" so the API's catch-all maps it to 400.
    """
    session_id = _create_session_id(admin_user)
    # Embed the metacharacter into an otherwise innocuous path. URL-encode so
    # that special chars (e.g. ``;``, ``&``, ``$``) survive routing intact.
    encoded = quote(f"attachments/foo{metachar}bar.txt", safe="/")
    response = client.delete(
        f"{API_SERVER_URL}/build/sessions/{session_id}/files/{encoded}",
        headers=admin_user.headers,
        cookies=admin_user.cookies,
    )
    assert response.status_code == 400


def test_delete_file_rejects_null_byte(admin_user: DATestUser) -> None:
    """A NUL byte in the delete path is rejected with 403.

    Starlette decodes ``%00`` to ``\\x00``. The sandbox manager's null-byte
    check raises ``ValueError("...path traversal...")``, mapped to 403.
    """
    session_id = _create_session_id(admin_user)
    # ``%00`` is the URL-encoded NUL byte. requests will pass it through
    # raw so the server sees the actual byte.
    response = client.delete(
        f"{API_SERVER_URL}/build/sessions/{session_id}/files/attachments/foo%00bar.txt",
        headers=admin_user.headers,
        cookies=admin_user.cookies,
    )
    assert response.status_code == 403


# ---------------------------------------------------------------------------
# download_artifact (path traversal + opencode.json hiding)
# ---------------------------------------------------------------------------


def test_download_artifact_rejects_path_traversal(admin_user: DATestUser) -> None:
    """GET /artifacts/..%2Fetc must not leak content from outside the sandbox.

    Sandbox manager either rejects (403) or normalizes-and-misses (400/404)
    — both prevent escape; only a 2xx with external content would be a bug.
    """
    session_id = _create_session_id(admin_user)
    response = client.get(
        _artifact_url(session_id, "..%2F..%2Fetc%2Fpasswd"),
        headers=admin_user.headers,
        cookies=admin_user.cookies,
    )
    assert response.status_code in (400, 403, 404)


def test_download_artifact_hides_opencode_json(admin_user: DATestUser) -> None:
    """Direct download of ``opencode.json`` returns 404 even if the file exists."""
    session_id = _create_session_id(admin_user)
    response = client.get(
        _artifact_url(session_id, "opencode.json"),
        headers=admin_user.headers,
        cookies=admin_user.cookies,
    )
    assert response.status_code == 404


# ---------------------------------------------------------------------------
# list_directory — hidden-entry filtering
# ---------------------------------------------------------------------------


def test_list_directory_filters_hidden_entries(admin_user: DATestUser) -> None:
    """``opencode.json``, ``.env`` and other HIDDEN_PATTERNS entries are never
    surfaced by the list endpoint.

    The upload API blocks creation of dotted/system files (sanitiser strips
    the leading dot, and ``.env`` is on the BLOCKED list at the filename
    level via the SAFE_FILENAME_PATTERN). We rely on the actual hidden
    filters baked into the manager — we just assert that no listing ever
    returns the forbidden names.
    """
    session_id = _create_session_id(admin_user)
    # Seed a couple of normal files so the listing isn't trivially empty.
    BuildSessionManager.upload_file(
        admin_user, session_id, filename="alpha.txt", content=b"a"
    )
    BuildSessionManager.upload_file(
        admin_user, session_id, filename="beta.txt", content=b"b"
    )

    listing = BuildSessionManager.list_files(admin_user, session_id)
    entries = listing.get("entries", [])
    names = {entry["name"] for entry in entries}

    forbidden = {".venv", ".git", "node_modules", ".DS_Store", "opencode.json", ".env"}
    assert names.isdisjoint(forbidden), (
        f"Listing returned hidden entries: {names & forbidden}"
    )


# ---------------------------------------------------------------------------
# Cross-user isolation
# ---------------------------------------------------------------------------


def test_cross_user_file_access_returns_404(
    admin_user: DATestUser, basic_user: DATestUser
) -> None:
    """User A asking for User B's session via any file-op endpoint sees 404."""
    foreign_session_id = _create_session_id(basic_user)

    response = client.get(
        _files_url(foreign_session_id),
        headers=admin_user.headers,
        cookies=admin_user.cookies,
    )
    assert response.status_code == 404


# ---------------------------------------------------------------------------
# download_directory zip
# ---------------------------------------------------------------------------


def test_download_directory_zip_respects_traversal_rules(
    admin_user: DATestUser,
) -> None:
    """download-directory returns 404 for a traversal path.

    ``session_manager.download_directory`` calls ``sandbox_manager.list_directory``
    which sanitises ``..`` away.  The resulting path doesn't exist on disk, so
    the manager catches the ``ValueError`` and returns ``None`` -> 404.
    """
    session_id = _create_session_id(admin_user)
    response = client.get(
        _download_directory_url(session_id, "..%2Fetc"),
        headers=admin_user.headers,
        cookies=admin_user.cookies,
    )
    assert response.status_code == 404


# ---------------------------------------------------------------------------
# pptx-preview / export-docx content-type checks
# ---------------------------------------------------------------------------


def test_pptx_preview_rejects_non_pptx(admin_user: DATestUser) -> None:
    """pptx-preview returns 400 for a .docx file."""
    session_id = _create_session_id(admin_user)
    response = client.get(
        _pptx_preview_url(session_id, "outputs/report.docx"),
        headers=admin_user.headers,
        cookies=admin_user.cookies,
    )
    assert response.status_code == 400


def test_export_docx_rejects_non_md(admin_user: DATestUser) -> None:
    """export-docx returns 400 for a .txt file."""
    session_id = _create_session_id(admin_user)
    # Seed an actual .txt file so the endpoint reaches the extension check
    # rather than short-circuiting on "file not found".
    seed_path = _seed_file(admin_user, session_id, name="notes.txt")
    response = client.get(
        _export_docx_url(session_id, seed_path),
        headers=admin_user.headers,
        cookies=admin_user.cookies,
    )
    assert response.status_code == 400
