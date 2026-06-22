"""Session lifecycle tests (HTTP contract half).

These tests exercise the FE-visible session HTTP API at ``/build/sessions``.
They run in the standard integration matrix against the in-process
``TestClient`` with a stubbed sandbox manager (see ``conftest.py``), so session
create/delete provision instantly without a real container.
"""

from __future__ import annotations

import uuid
from typing import Any

from tests.integration.common_utils.constants import API_SERVER_URL
from tests.integration.common_utils.http_client import client
from tests.integration.common_utils.managers.build_session import BuildSessionManager
from tests.integration.common_utils.managers.settings import SettingsManager
from tests.integration.common_utils.managers.user import UserManager
from tests.integration.common_utils.test_models import DATestLLMProvider
from tests.integration.common_utils.test_models import DATestSettings
from tests.integration.common_utils.test_models import DATestUser

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _create_session(user: DATestUser) -> dict[str, Any]:
    """Create a session and return the parsed response body."""
    return BuildSessionManager.create(user)


def _send_one_message(user: DATestUser, session_id: uuid.UUID) -> None:
    """Send a message and wait only until the USER row is persisted.

    The background-turn endpoint commits the USER message row before returning
    turn metadata. Tests using this helper must not depend on assistant-message
    rows being persisted.
    """
    BuildSessionManager.start_turn(
        user,
        session_id,
        "hello",
        client_request_id=f"session-list-{uuid.uuid4()}",
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_create_session_requires_auth() -> None:
    """POST /build/sessions without an auth cookie/header is rejected."""
    response = client.post(
        f"{API_SERVER_URL}/build/sessions",
        json={},
        headers={"Content-Type": "application/json"},
    )
    # The build router gates access through ``require_onyx_craft_enabled`` →
    # ``require_permission(BASIC_ACCESS)`` → ``current_user``. Onyx's
    # ``BasicAuthenticationError`` returns 403 for unauthenticated callers
    # (not 401). Either is acceptable so long as it's a 4xx auth failure.
    assert response.status_code in (401, 403)


def test_get_session_404_for_other_users_session(
    shared_session: tuple[DATestUser, uuid.UUID],
) -> None:
    """Fetching another user's session by id returns 404 (ownership-gated).

    Ownership-gated and scope-independent (``get_session`` filters by user id),
    so the shared session is fine here even if a sibling flips its
    sharing scope.
    """
    _owner, session_id = shared_session

    other_user = UserManager.create(name=f"other-{uuid.uuid4().hex[:8]}")
    response = client.get(
        f"{API_SERVER_URL}/build/sessions/{session_id}",
        headers=other_user.headers,
        cookies=other_user.cookies,
    )
    assert response.status_code == 404


def test_list_sessions_only_returns_callers_interactive_sessions(
    admin_user: DATestUser,
    llm_provider: DATestLLMProvider,  # noqa: ARG001
) -> None:
    """The sidebar listing is per-user and excludes other users' sessions.

    ``get_user_build_sessions`` also filters to ``origin=INTERACTIVE`` and
    sessions with at least one message — both are exercised here implicitly:
    the foreign session is INTERACTIVE-with-message yet still excluded.
    """
    mine = _create_session(admin_user)
    _send_one_message(admin_user, uuid.UUID(mine["id"]))

    other_user = UserManager.create(name=f"other-{uuid.uuid4().hex[:8]}")
    theirs = _create_session(other_user)
    _send_one_message(other_user, uuid.UUID(theirs["id"]))

    sessions = BuildSessionManager.list_sessions(admin_user)
    ids = {s["id"] for s in sessions}
    assert mine["id"] in ids
    assert theirs["id"] not in ids


def test_delete_session_returns_204_and_actually_deletes(
    admin_user: DATestUser,
    llm_provider: DATestLLMProvider,  # noqa: ARG001
) -> None:
    """DELETE returns 204 and a follow-up GET on the same id returns 404."""
    body = _create_session(admin_user)
    session_id = body["id"]

    response = client.delete(
        f"{API_SERVER_URL}/build/sessions/{session_id}",
        headers=admin_user.headers,
        cookies=admin_user.cookies,
    )
    assert response.status_code == 204

    follow_up = client.get(
        f"{API_SERVER_URL}/build/sessions/{session_id}",
        headers=admin_user.headers,
        cookies=admin_user.cookies,
    )
    assert follow_up.status_code == 404


def test_pre_provisioned_check_returns_valid_for_empty_session(
    admin_user: DATestUser,
    llm_provider: DATestLLMProvider,  # noqa: ARG001
) -> None:
    """An empty (just-created) session reports ``valid=true`` with its id."""
    body = _create_session(admin_user)
    session_id = body["id"]

    response = client.get(
        f"{API_SERVER_URL}/build/sessions/{session_id}/pre-provisioned-check",
        headers=admin_user.headers,
        cookies=admin_user.cookies,
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["valid"] is True
    assert payload["session_id"] == session_id


def test_pre_provisioned_check_returns_invalid_after_first_message(
    admin_user: DATestUser,
    llm_provider: DATestLLMProvider,  # noqa: ARG001
) -> None:
    """Once a USER message exists, the same session is no longer "valid"."""
    body = _create_session(admin_user)
    session_id = body["id"]

    _send_one_message(admin_user, uuid.UUID(session_id))

    response = client.get(
        f"{API_SERVER_URL}/build/sessions/{session_id}/pre-provisioned-check",
        headers=admin_user.headers,
        cookies=admin_user.cookies,
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["valid"] is False
    assert payload["session_id"] is None


def test_rename_session_with_null_name_uses_llm_then_fallback_chain(
    admin_user: DATestUser,
    llm_provider: DATestLLMProvider,  # noqa: ARG001
) -> None:
    """PUT /name with ``{name: null}`` resolves a non-empty name via the chain.

    ``_generate_session_name`` walks three branches:
      1. If there's no first user message → ``Build Session {id[:8]}``.
      2. If the LLM call succeeds → the generated name (truncated to 50 chars).
      3. If the LLM call raises → first 40 chars of the user message.

    Without messages we must hit branch 1; we assert exactly that, because
    it's the only branch with a deterministic output an HTTP-only test can
    pin. The chain itself is unit-tested at the manager level.
    """
    body = _create_session(admin_user)
    session_id = body["id"]

    response = client.put(
        f"{API_SERVER_URL}/build/sessions/{session_id}/name",
        json={"name": None},
        headers=admin_user.headers,
        cookies=admin_user.cookies,
    )
    assert response.status_code == 200
    payload = response.json()
    # Branch 1 fallback: "Build Session {id[:8]}".
    assert payload["name"] == f"Build Session {session_id[:8]}"


def test_limited_role_check_uses_account_type_not_permission_flags(
    admin_user: DATestUser,  # noqa: ARG001 — needed so admin exists for SettingsManager
) -> None:
    """Account-type-restricted users are blocked from Craft regardless of any
    permission grant they might have. Regression for SHA ``ac89b42b38``: that
    commit moved the limited check off the role bit and onto ``account_type``,
    via ``current_user`` → ``is_limited_user``.

    We use the anonymous user (``account_type=AccountType.ANONYMOUS``), which
    ``is_limited_user`` always rejects. Even with ``anonymous_user_enabled``
    flipped to True (so the anonymous user is otherwise allowed to hit
    public endpoints), the Craft router must still 401/403 them out.
    """
    try:
        # Enable anonymous browsing so the request reaches require_permission;
        # if we left it off, the request would fail authentication before the
        # is_limited_user check ever ran — different regression branch.
        SettingsManager.update_settings(
            DATestSettings(anonymous_user_enabled=True),
            user_performing_action=admin_user,
        )

        anon_user = UserManager.get_anonymous_user()

        response = client.post(
            f"{API_SERVER_URL}/build/sessions",
            json={},
            headers=anon_user.headers,
            cookies=anon_user.cookies,
        )
        # current_user rejects limited account types with BasicAuthenticationError
        # (HTTP 403); some auth-failure paths surface as 401.
        assert response.status_code in (401, 403)
    finally:
        # Restore the default so subsequent tests see the normal config.
        SettingsManager.update_settings(
            DATestSettings(anonymous_user_enabled=False),
            user_performing_action=admin_user,
        )
