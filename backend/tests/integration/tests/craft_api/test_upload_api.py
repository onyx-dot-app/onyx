"""File upload tests (HTTP contract half).

Pins the upload endpoint's auth and cross-user-ownership boundaries. Both are
resolved before any file write, so they run in the standard integration matrix
against the in-process app with a stubbed sandbox manager (see ``conftest.py``).
The cap enforcement (per-file / count / cumulative) and the real round-trip
write+download checks need the real sandbox manager and stay in the compose
lane.
"""

from __future__ import annotations

from uuid import UUID

from tests.integration.common_utils.constants import API_SERVER_URL
from tests.integration.common_utils.http_client import client
from tests.integration.common_utils.test_models import DATestUser


def _upload_url(session_id: UUID) -> str:
    return f"{API_SERVER_URL}/build/sessions/{session_id}/upload"


def test_upload_endpoint_requires_auth(
    shared_session: tuple[DATestUser, UUID],
) -> None:
    """POST with no auth token returns 401 (or 403)."""
    # The session just needs to exist; we then strip auth.
    _owner, session_id = shared_session

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
    shared_session: tuple[DATestUser, UUID], basic_user: DATestUser
) -> None:
    """Uploading to another user's session returns 404."""
    _owner, foreign_session_id = shared_session

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
