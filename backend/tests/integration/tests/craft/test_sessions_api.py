"""Session lifecycle tests against a real provisioned sandbox."""

from __future__ import annotations

import uuid
from typing import Any
from uuid import UUID

from onyx.db.enums import SharingScope
from onyx.redis.redis_pool import get_redis_client
from onyx.server.features.build.session.api import RESTORE_LOCK_TIMEOUT_SECONDS
from shared_configs.configs import POSTGRES_DEFAULT_SCHEMA_STANDARD_VALUE
from tests.integration.common_utils.constants import API_SERVER_URL
from tests.integration.common_utils.http_client import client
from tests.integration.common_utils.managers.build_session import BuildSessionManager
from tests.integration.common_utils.managers.settings import SettingsManager
from tests.integration.common_utils.managers.user import UserManager
from tests.integration.common_utils.test_models import DATestLLMProvider
from tests.integration.common_utils.test_models import DATestSettings
from tests.integration.common_utils.test_models import DATestUser


def _create_session(user: DATestUser) -> dict[str, Any]:
    return BuildSessionManager.create(user)


def _send_one_message(user: DATestUser, session_id: uuid.UUID) -> None:
    BuildSessionManager.start_turn(
        user,
        session_id,
        "hello",
        client_request_id=f"session-list-{uuid.uuid4()}",
    )


def test_create_session_returns_200_with_session_and_sandbox_shape(
    admin_user: DATestUser,
    llm_provider: DATestLLMProvider,  # noqa: ARG001 — ensures a default LLM exists
) -> None:
    response = client.post(
        f"{API_SERVER_URL}/build/sessions",
        json={"headless": False},
        headers=admin_user.headers,
        cookies=admin_user.cookies,
    )
    assert response.status_code == 200
    body = response.json()
    assert body["user_id"] == admin_user.id
    assert body["sandbox"] is not None


def test_set_sharing_scope_changes_webapp_visibility(
    admin_user: DATestUser,
    basic_user: DATestUser,
    llm_provider: DATestLLMProvider,  # noqa: ARG001
) -> None:
    body = _create_session(admin_user)
    session_uuid = uuid.UUID(body["id"])
    webapp_url = f"{API_SERVER_URL}/build/sessions/{body['id']}/webapp"

    private_response = client.get(
        webapp_url,
        headers=basic_user.headers,
        cookies=basic_user.cookies,
        follow_redirects=False,
    )
    assert private_response.status_code == 404

    BuildSessionManager.set_sharing(admin_user, session_uuid, SharingScope.PUBLIC_ORG)

    public_response = client.get(
        webapp_url,
        headers=basic_user.headers,
        cookies=basic_user.cookies,
        follow_redirects=False,
    )
    assert public_response.status_code in (200, 502, 503, 504)
    assert "text/html" in public_response.headers.get("content-type", "").lower()


def test_restore_session_returns_409_when_lock_held(
    admin_user: DATestUser,
    llm_provider: DATestLLMProvider,  # noqa: ARG001
) -> None:
    body = _create_session(admin_user)
    session_id = body["id"]
    sandbox_id = body["sandbox"]["id"]

    redis_client = get_redis_client(tenant_id=POSTGRES_DEFAULT_SCHEMA_STANDARD_VALUE)
    lock = redis_client.lock(
        f"sandbox_restore:{sandbox_id}", timeout=RESTORE_LOCK_TIMEOUT_SECONDS
    )
    assert lock.acquire(blocking=False)
    try:
        response = client.post(
            f"{API_SERVER_URL}/build/sessions/{session_id}/restore",
            headers=admin_user.headers,
            cookies=admin_user.cookies,
        )
        assert response.status_code == 409
        assert response.json()["detail"] == "Restore already in progress"
    finally:
        lock.release()


def test_create_session_requires_auth() -> None:
    response = client.post(
        f"{API_SERVER_URL}/build/sessions",
        json={},
        headers={"Content-Type": "application/json"},
    )
    assert response.status_code in (401, 403)


def test_get_session_404_for_other_users_session(
    shared_session: tuple[DATestUser, UUID],
) -> None:
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


def test_rename_session_with_null_name_no_message_uses_id_fallback(
    admin_user: DATestUser,
    llm_provider: DATestLLMProvider,  # noqa: ARG001
) -> None:
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
    assert payload["name"] == f"Build Session {session_id[:8]}"


def test_rename_session_with_null_name_falls_back_when_llm_call_fails(
    admin_user: DATestUser,
    llm_provider: DATestLLMProvider,  # noqa: ARG001
) -> None:
    body = _create_session(admin_user)
    session_id = body["id"]

    prompt = "hello"
    BuildSessionManager.start_turn(
        admin_user,
        uuid.UUID(session_id),
        prompt,
        client_request_id=f"rename-{uuid.uuid4()}",
    )

    response = client.put(
        f"{API_SERVER_URL}/build/sessions/{session_id}/name",
        json={"name": None},
        headers=admin_user.headers,
        cookies=admin_user.cookies,
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["name"] != f"Build Session {session_id[:8]}"
    assert payload["name"] == prompt


def test_limited_role_check_uses_account_type_not_permission_flags(
    admin_user: DATestUser,  # noqa: ARG001 — needed so admin exists for SettingsManager
) -> None:
    SettingsManager.update_settings(
        DATestSettings(anonymous_user_enabled=True),
        user_performing_action=admin_user,
    )
    try:
        anon_user = UserManager.get_anonymous_user()
        response = client.post(
            f"{API_SERVER_URL}/build/sessions",
            json={},
            headers=anon_user.headers,
            cookies=anon_user.cookies,
        )
        assert response.status_code in (401, 403)
    finally:
        SettingsManager.update_settings(
            DATestSettings(anonymous_user_enabled=False),
            user_performing_action=admin_user,
        )
