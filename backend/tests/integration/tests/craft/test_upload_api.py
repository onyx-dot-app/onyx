"""File upload tests (HTTP half)."""

from __future__ import annotations

from uuid import UUID

from tests.integration.common_utils.constants import API_SERVER_URL
from tests.integration.common_utils.http_client import client
from tests.integration.common_utils.managers.build_session import BuildSessionManager
from tests.integration.common_utils.test_models import DATestUser
from tests.integration.tests.craft.conftest import SharedSession
from tests.integration.tests.craft.user_library_http import multipart_headers


def _create_session_id(user: DATestUser) -> UUID:
    session = BuildSessionManager.create(user)
    return UUID(session.id)


def _upload_url(session_id: UUID) -> str:
    return f"{API_SERVER_URL}/build/sessions/{session_id}/upload"


def test_upload_endpoint_returns_file_metadata(admin_user: DATestUser) -> None:
    session_id = _create_session_id(admin_user)
    body = BuildSessionManager.upload_file(
        admin_user,
        session_id,
        filename="hello.txt",
        content=b"hello world",
    )

    assert body.filename == "hello.txt"
    assert isinstance(body.path, str) and body.path.endswith("hello.txt")
    assert body.size_bytes == len(b"hello world")


def test_upload_over_per_file_cap_returns_400(
    shared_session: SharedSession,
) -> None:
    owner, session_id = shared_session

    # CI lowers BUILD_MAX_UPLOAD_FILE_SIZE_MB to 2; a 3 MiB payload trips it.
    oversized = b"\x00" * (3 * 1024 * 1024)
    headers = multipart_headers(owner)
    response = client.post(
        _upload_url(session_id),
        files={"file": ("big.txt", oversized, "application/octet-stream")},
        headers=headers,
        cookies=owner.cookies,
    )
    assert response.status_code == 400


def test_upload_at_count_cap_returns_429(admin_user: DATestUser) -> None:
    session_id = _create_session_id(admin_user)

    # CI lowers BUILD_MAX_UPLOAD_FILES_PER_SESSION to 5.
    for i in range(5):
        BuildSessionManager.upload_file(
            admin_user,
            session_id,
            filename=f"file_{i}.txt",
            content=b"x",
        )

    headers = multipart_headers(admin_user)
    response = client.post(
        _upload_url(session_id),
        files={"file": ("file_overflow.txt", b"x", "application/octet-stream")},
        headers=headers,
        cookies=admin_user.cookies,
    )
    assert response.status_code == 429


def test_upload_over_cumulative_cap_returns_429(admin_user: DATestUser) -> None:
    session_id = _create_session_id(admin_user)

    # CI lowers per-file cap to 2 MiB and total cap to 4 MiB; the third tips past 4.
    chunk = b"\x00" * (1024 * 1024 + 512 * 1024)  # 1.5 MiB
    for i in range(2):
        BuildSessionManager.upload_file(
            admin_user,
            session_id,
            filename=f"chunk_{i}.txt",
            content=chunk,
        )

    headers = multipart_headers(admin_user)
    response = client.post(
        _upload_url(session_id),
        files={"file": ("chunk_overflow.txt", chunk, "application/octet-stream")},
        headers=headers,
        cookies=admin_user.cookies,
    )
    assert response.status_code == 429


def test_upload_accepts_any_extension_via_http(admin_user: DATestUser) -> None:
    """Uploads are not restricted by extension/MIME; a .exe uploads fine."""
    session_id = _create_session_id(admin_user)

    headers = multipart_headers(admin_user)
    response = client.post(
        _upload_url(session_id),
        files={"file": ("evil.exe", b"MZ\x90\x00", "application/octet-stream")},
        headers=headers,
        cookies=admin_user.cookies,
    )
    assert response.status_code == 200


def test_upload_with_unicode_filename_persists_correctly(
    admin_user: DATestUser,
) -> None:
    """A Unicode filename round-trips through upload + download."""
    session_id = _create_session_id(admin_user)

    original_bytes = "héllo wörld 你好 🌍".encode("utf-8")
    # The endpoint sanitizes filenames, so assert on the round-tripped bytes.
    upload_response = BuildSessionManager.upload_file(
        admin_user,
        session_id,
        filename="héllo wörld 你好.txt",
        content=original_bytes,
    )
    sanitized_name = upload_response.filename
    relative_path = upload_response.path

    assert sanitized_name.endswith(".txt")
    assert relative_path.endswith(sanitized_name)

    downloaded = BuildSessionManager.download_artifact(
        admin_user, session_id, relative_path
    )
    assert downloaded == original_bytes


def test_upload_endpoint_requires_auth(
    shared_session: SharedSession,
) -> None:
    """POST with no auth token returns 401 (or 403)."""
    _owner, session_id = shared_session

    response = client.post(
        _upload_url(session_id),
        files={"file": ("hello.txt", b"hello", "application/octet-stream")},
        headers={},
        cookies=None,
    )
    assert response.status_code in (401, 403)


def test_upload_endpoint_404_for_other_users_session(
    shared_session: SharedSession, basic_user: DATestUser
) -> None:
    """Uploading to another user's session returns 404 (existence-hiding)."""
    _owner, foreign_session_id = shared_session

    headers = multipart_headers(basic_user)
    response = client.post(
        _upload_url(foreign_session_id),
        files={"file": ("hello.txt", b"hi", "application/octet-stream")},
        headers=headers,
        cookies=basic_user.cookies,
    )
    assert response.status_code == 404
