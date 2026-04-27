"""Integration tests for persona access enforcement on chat session creation.

Covers the `/chat/create-chat-session` endpoint and the implicit session-creation
path inside `/chat/send-chat-message` when `chat_session_info` is provided.
"""

import json
import os

import pytest
import requests

from tests.integration.common_utils.constants import API_SERVER_URL
from tests.integration.common_utils.managers.persona import PersonaManager
from tests.integration.common_utils.managers.user import UserManager
from tests.integration.common_utils.managers.user_group import UserGroupManager
from tests.integration.common_utils.test_models import DATestUser

# The fix in `create_chat_session_from_request` runs unconditionally, including
# on CE. Group-restricted personas only exist under EE, though — on CE every
# non-admin sees public personas and admins see everything, so no CE user is
# ever locked out by the access check. These tests therefore only exercise the
# EE code path where a meaningful block can occur.
pytestmark = pytest.mark.skipif(
    os.environ.get("ENABLE_PAID_ENTERPRISE_EDITION_FEATURES", "").lower() != "true",
    reason="Persona group restrictions are enterprise only",
)


@pytest.fixture()
def admin_and_basic_user(
    reset: None,  # noqa: ARG001
) -> tuple[DATestUser, DATestUser]:
    admin_user = UserManager.create(name="admin_user")
    basic_user = UserManager.create(name="basic_user")
    return admin_user, basic_user


def test_create_chat_session_with_unauthorized_persona_returns_403(
    admin_and_basic_user: tuple[DATestUser, DATestUser],
) -> None:
    admin_user, basic_user = admin_and_basic_user

    restricted_group = UserGroupManager.create(
        user_performing_action=admin_user,
        name="restricted_group",
        user_ids=[],  # basic_user is NOT in this group
    )
    restricted_persona = PersonaManager.create(
        user_performing_action=admin_user,
        name="Restricted Persona",
        description="Only accessible to restricted_group",
        is_public=False,
        groups=[restricted_group.id],
    )

    response = requests.post(
        f"{API_SERVER_URL}/chat/create-chat-session",
        json={"persona_id": restricted_persona.id, "description": "Attempted bypass"},
        headers=basic_user.headers,
    )

    assert response.status_code == 403
    assert "persona" in response.json()["detail"].lower()


def test_create_chat_session_with_authorized_persona_succeeds(
    admin_and_basic_user: tuple[DATestUser, DATestUser],
) -> None:
    admin_user, basic_user = admin_and_basic_user

    allowed_group = UserGroupManager.create(
        user_performing_action=admin_user,
        name="allowed_group",
        user_ids=[basic_user.id],
    )
    allowed_persona = PersonaManager.create(
        user_performing_action=admin_user,
        name="Allowed Persona",
        description="Accessible to basic_user",
        is_public=False,
        groups=[allowed_group.id],
    )

    response = requests.post(
        f"{API_SERVER_URL}/chat/create-chat-session",
        json={"persona_id": allowed_persona.id, "description": "Authorized"},
        headers=basic_user.headers,
    )

    assert response.status_code == 200
    assert "chat_session_id" in response.json()


def test_create_chat_session_with_public_persona_succeeds(
    admin_and_basic_user: tuple[DATestUser, DATestUser],
) -> None:
    admin_user, basic_user = admin_and_basic_user

    public_persona = PersonaManager.create(
        user_performing_action=admin_user,
        name="Public Persona",
        description="Visible to all",
        is_public=True,
    )

    response = requests.post(
        f"{API_SERVER_URL}/chat/create-chat-session",
        json={"persona_id": public_persona.id, "description": "Public access"},
        headers=basic_user.headers,
    )

    assert response.status_code == 200


def test_create_chat_session_with_default_persona_succeeds(
    admin_and_basic_user: tuple[DATestUser, DATestUser],
) -> None:
    _, basic_user = admin_and_basic_user

    response = requests.post(
        f"{API_SERVER_URL}/chat/create-chat-session",
        json={"persona_id": 0, "description": "Default persona"},
        headers=basic_user.headers,
    )

    assert response.status_code == 200


def test_send_chat_message_with_unauthorized_persona_in_session_info_is_blocked(
    admin_and_basic_user: tuple[DATestUser, DATestUser],
) -> None:
    """The same check must apply when a session is created implicitly via send-chat-message."""
    admin_user, basic_user = admin_and_basic_user

    restricted_group = UserGroupManager.create(
        user_performing_action=admin_user,
        name="restricted_group_send",
        user_ids=[],
    )
    restricted_persona = PersonaManager.create(
        user_performing_action=admin_user,
        name="Restricted Persona For Send",
        description="Only accessible to restricted_group_send",
        is_public=False,
        groups=[restricted_group.id],
    )

    response = requests.post(
        f"{API_SERVER_URL}/chat/send-chat-message",
        json={
            "message": "hello",
            "chat_session_info": {
                "persona_id": restricted_persona.id,
                "description": "Attempted bypass via message send",
            },
            "stream": True,
        },
        headers=basic_user.headers,
        stream=True,
    )

    # Streaming endpoint always returns 200 and emits an error packet inside the stream.
    # The important property is that the unauthorized persona never produces a valid
    # response — a packet containing an access-denied error is surfaced.
    saw_access_error = False
    for raw_line in response.iter_lines():
        if not raw_line:
            continue
        try:
            payload = json.loads(raw_line)
        except json.JSONDecodeError:
            continue
        err = payload.get("error")
        if isinstance(err, str) and "persona" in err.lower():
            saw_access_error = True
            break

    assert saw_access_error, (
        "Expected an access-denied error in the stream when sending a message "
        "with an unauthorized persona in chat_session_info."
    )
