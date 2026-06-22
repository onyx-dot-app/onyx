"""File ops security boundary tests (HTTP contract half).

Pins the hidden-entry, opencode.json-hiding, and cross-user rules across the
build session file-ops endpoints. These checks are resolved before (or
independently of) any real filesystem access, so they run in the standard
integration matrix against the in-process app with a stubbed sandbox manager
(see ``conftest.py``). The path-traversal / metachar / null-byte validation
and the real upload-stats assertions need the real sandbox manager and stay in
the compose lane.
"""

from __future__ import annotations

from uuid import UUID

from tests.integration.common_utils.constants import API_SERVER_URL
from tests.integration.common_utils.http_client import client
from tests.integration.common_utils.managers.build_session import BuildSessionManager
from tests.integration.common_utils.test_models import DATestLLMProvider
from tests.integration.common_utils.test_models import DATestUser

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _create_session_id(user: DATestUser) -> UUID:
    session = BuildSessionManager.create(user)
    return UUID(session["id"])


def _files_url(session_id: UUID) -> str:
    return f"{API_SERVER_URL}/build/sessions/{session_id}/files"


def _artifact_url(session_id: UUID, path: str) -> str:
    return f"{API_SERVER_URL}/build/sessions/{session_id}/artifacts/{path}"


# ---------------------------------------------------------------------------
# download_artifact — opencode.json hiding
# ---------------------------------------------------------------------------


def test_download_artifact_hides_opencode_json(
    shared_session: tuple[DATestUser, UUID],
) -> None:
    """Direct download of ``opencode.json`` returns 404 even if the file exists."""
    owner, session_id = shared_session
    response = client.get(
        _artifact_url(session_id, "opencode.json"),
        headers=owner.headers,
        cookies=owner.cookies,
    )
    assert response.status_code == 404


# ---------------------------------------------------------------------------
# list_directory — hidden-entry filtering
# ---------------------------------------------------------------------------


def test_list_directory_filters_hidden_entries(
    shared_session: tuple[DATestUser, UUID],
) -> None:
    """``opencode.json``, ``.env`` and other HIDDEN_PATTERNS entries are never
    surfaced by the list endpoint.

    The upload API blocks creation of dotted/system files (sanitiser strips
    the leading dot, and ``.env`` is on the BLOCKED list at the filename
    level via the SAFE_FILENAME_PATTERN). We rely on the actual hidden
    filters baked into the manager — we just assert that no listing ever
    returns the forbidden names.
    """
    owner, session_id = shared_session
    # Seed a couple of normal files so the listing isn't trivially empty.
    BuildSessionManager.upload_file(
        owner, session_id, filename="alpha.txt", content=b"a"
    )
    BuildSessionManager.upload_file(
        owner, session_id, filename="beta.txt", content=b"b"
    )

    listing = BuildSessionManager.list_files(owner, session_id)
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
    admin_user: DATestUser,
    basic_user: DATestUser,
    llm_provider: DATestLLMProvider,  # noqa: ARG001
) -> None:
    """User A asking for User B's session via any file-op endpoint sees 404."""
    foreign_session_id = _create_session_id(basic_user)

    response = client.get(
        _files_url(foreign_session_id),
        headers=admin_user.headers,
        cookies=admin_user.cookies,
    )
    assert response.status_code == 404
