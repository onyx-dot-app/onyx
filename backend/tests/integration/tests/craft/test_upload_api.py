"""File upload tests (integration / HTTP half).

Exercises the upload endpoint via the live API server so we pin both the
happy-path response shape and the boundary error mapping (auth, foreign
session, size/count/cumulative caps, blocked extensions, Unicode filenames).
"""

from __future__ import annotations

from uuid import UUID

from tests.integration.common_utils.constants import API_SERVER_URL
from tests.integration.common_utils.http_client import client
from tests.integration.common_utils.managers.build_session import BuildSessionManager
from tests.integration.common_utils.test_models import DATestUser


def _create_session_id(user: DATestUser) -> UUID:
    """Create a build session and return its UUID."""
    session = BuildSessionManager.create(user)
    return UUID(session["id"])


def _upload_url(session_id: UUID) -> str:
    return f"{API_SERVER_URL}/build/sessions/{session_id}/upload"


def test_upload_endpoint_201(admin_user: DATestUser) -> None:
    """POST returns 201 with a body containing {filename, path, size_bytes}."""
    session_id = _create_session_id(admin_user)
    body = BuildSessionManager.upload_file(
        admin_user,
        session_id,
        filename="hello.txt",
        content=b"hello world",
    )

    assert body["filename"] == "hello.txt"
    assert isinstance(body["path"], str) and body["path"].endswith("hello.txt")
    assert body["size_bytes"] == len(b"hello world")


def test_upload_endpoint_requires_auth(admin_user: DATestUser) -> None:
    """POST with no auth token returns 401 (or 403)."""
    # admin_user is just used to ensure a session exists; we then strip auth.
    session_id = _create_session_id(admin_user)

    response = client.post(
        _upload_url(session_id),
        files={"file": ("hello.txt", b"hello", "application/octet-stream")},
        headers={},
        cookies=None,
    )
    # Onyx auth middleware returns either 401 or 403 for unauthenticated
    # requests against BASIC_ACCESS endpoints.
    assert response.status_code in (401, 403)


def test_upload_endpoint_404_for_other_users_session(
    admin_user: DATestUser, basic_user: DATestUser
) -> None:
    """Uploading to another user's session returns 404."""
    foreign_session_id = _create_session_id(admin_user)

    headers = {
        k: v for k, v in basic_user.headers.items() if k.lower() != "content-type"
    }
    response = client.post(
        _upload_url(foreign_session_id),
        files={"file": ("hello.txt", b"hi", "application/octet-stream")},
        headers=headers,
        cookies=basic_user.cookies,
    )
    assert response.status_code == 404


def test_upload_over_per_file_cap_returns_400(admin_user: DATestUser) -> None:
    """A file exceeding the per-file cap is rejected with 400.

    The ``validate_file`` helper catches oversized files and the endpoint
    returns 400 (not 413) because the check is application-level, not a
    framework payload-size guard.
    """
    session_id = _create_session_id(admin_user)

    # CI lowers BUILD_MAX_UPLOAD_FILE_SIZE_MB to 2; a 3 MiB payload trips it.
    oversized = b"\x00" * (3 * 1024 * 1024)
    headers = {
        k: v for k, v in admin_user.headers.items() if k.lower() != "content-type"
    }
    response = client.post(
        _upload_url(session_id),
        files={"file": ("big.txt", oversized, "application/octet-stream")},
        headers=headers,
        cookies=admin_user.cookies,
    )
    # Per-file cap → 400 from validate_file.
    assert response.status_code == 400


def test_upload_at_count_cap_returns_429(admin_user: DATestUser) -> None:
    """An upload exceeding MAX_UPLOAD_FILES_PER_SESSION is rejected with 429.

    ``UploadLimitExceededError`` is mapped to 429 (Too Many Requests) by the
    upload endpoint.
    """
    session_id = _create_session_id(admin_user)

    # CI lowers BUILD_MAX_UPLOAD_FILES_PER_SESSION to 5.
    for i in range(5):
        BuildSessionManager.upload_file(
            admin_user,
            session_id,
            filename=f"file_{i}.txt",
            content=b"x",
        )

    # 6th upload should hit the count cap.
    headers = {
        k: v for k, v in admin_user.headers.items() if k.lower() != "content-type"
    }
    response = client.post(
        _upload_url(session_id),
        files={"file": ("file_overflow.txt", b"x", "application/octet-stream")},
        headers=headers,
        cookies=admin_user.cookies,
    )
    # Count cap → 429 from UploadLimitExceededError.
    assert response.status_code == 429


def test_upload_over_cumulative_cap_returns_429(admin_user: DATestUser) -> None:
    """Pushing total session usage past MAX_TOTAL_UPLOAD_SIZE_BYTES is rejected with 429.

    ``UploadLimitExceededError`` is mapped to 429 (Too Many Requests) by the
    upload endpoint.
    """
    session_id = _create_session_id(admin_user)

    # CI lowers per-file cap to 2 MiB and total cap to 4 MiB.
    # Two 1.5 MiB uploads (3 MiB) succeed; the third tips total past 4 MiB.
    chunk = b"\x00" * (1024 * 1024 + 512 * 1024)  # 1.5 MiB
    for i in range(2):
        BuildSessionManager.upload_file(
            admin_user,
            session_id,
            filename=f"chunk_{i}.txt",
            content=chunk,
        )

    headers = {
        k: v for k, v in admin_user.headers.items() if k.lower() != "content-type"
    }
    response = client.post(
        _upload_url(session_id),
        files={"file": ("chunk_overflow.txt", chunk, "application/octet-stream")},
        headers=headers,
        cookies=admin_user.cookies,
    )
    # Cumulative cap → 429 from UploadLimitExceededError.
    assert response.status_code == 429


def test_upload_rejects_blocked_extension_via_http(admin_user: DATestUser) -> None:
    """Uploading evil.exe is rejected with a 4xx (blocked extension)."""
    session_id = _create_session_id(admin_user)

    headers = {
        k: v for k, v in admin_user.headers.items() if k.lower() != "content-type"
    }
    response = client.post(
        _upload_url(session_id),
        files={"file": ("evil.exe", b"MZ\x90\x00", "application/octet-stream")},
        headers=headers,
        cookies=admin_user.cookies,
    )
    assert 400 <= response.status_code < 500
    # Sanity check: this must NOT silently succeed.
    assert response.status_code != 201


def test_upload_with_unicode_filename_persists_correctly(
    admin_user: DATestUser,
) -> None:
    """A Unicode filename round-trips through upload + download.

    The Content-Disposition response header for download uses RFC 5987 for
    non-Latin-1 filenames; here we confirm the file is reachable and its
    bytes survive the round trip.
    """
    session_id = _create_session_id(admin_user)

    original_bytes = "héllo wörld 你好 🌍".encode("utf-8")
    # The upload endpoint sanitizes filenames (replaces non [a-zA-Z0-9._-]
    # with underscores), so we focus the round-trip assertion on the bytes;
    # the response also tells us where the file ended up.
    upload_response = BuildSessionManager.upload_file(
        admin_user,
        session_id,
        filename="héllo wörld 你好.txt",
        content=original_bytes,
    )
    sanitized_name = upload_response["filename"]
    relative_path = upload_response["path"]

    # The sanitizer keeps the .txt suffix.
    assert sanitized_name.endswith(".txt")
    assert relative_path.endswith(sanitized_name)

    downloaded = BuildSessionManager.download_artifact(
        admin_user, session_id, relative_path
    )
    assert downloaded == original_bytes
