"""Interactive Craft turn API tests.

These tests exercise the HTTP boundary for the no-migration background-turn
flow: ``POST /send-message`` starts work and returns turn metadata, while
``GET /turns/{turn_id}/events`` is attach-only.
"""

from __future__ import annotations

import uuid

from tests.integration.common_utils.constants import API_SERVER_URL
from tests.integration.common_utils.http_client import client
from tests.integration.common_utils.managers.build_session import BuildSessionManager
from tests.integration.common_utils.managers.user import UserManager
from tests.integration.common_utils.test_models import DATestUser


def test_send_message_starts_background_turn_and_is_idempotent(
    admin_user: DATestUser,
) -> None:
    body = BuildSessionManager.create(admin_user)
    session_id = uuid.UUID(body["id"])
    request_id = f"req-{uuid.uuid4()}"

    first = BuildSessionManager.start_turn(
        admin_user,
        session_id,
        "hello",
        client_request_id=request_id,
    )
    same = BuildSessionManager.start_turn(
        admin_user,
        session_id,
        "hello",
        client_request_id=request_id,
    )

    assert first["turn_id"] == same["turn_id"]
    assert first["session_id"] == str(session_id)
    assert first["status"] in {"QUEUED", "RUNNING"}
    assert first["turn_index"] == 0

    active_turn = BuildSessionManager.get_active_turn(admin_user, session_id)
    if active_turn is not None:
        assert active_turn["turn_id"] == first["turn_id"]

    messages = BuildSessionManager.list_messages(admin_user, session_id)
    user_messages = [msg for msg in messages if msg["type"] == "user"]
    assert len(user_messages) == 1
    assert user_messages[0]["turn_index"] == 0


def test_send_message_rejects_concurrent_active_turn(
    admin_user: DATestUser,
) -> None:
    body = BuildSessionManager.create(admin_user)
    session_id = uuid.UUID(body["id"])

    BuildSessionManager.start_turn(
        admin_user,
        session_id,
        "hello",
        client_request_id=f"req-{uuid.uuid4()}",
    )

    response = client.post(
        f"{API_SERVER_URL}/build/sessions/{session_id}/send-message",
        json={
            "content": "again",
            "client_request_id": f"req-{uuid.uuid4()}",
        },
        headers=admin_user.headers,
        cookies=admin_user.cookies,
    )

    assert response.status_code == 409
    assert response.json()["detail"] == "This session is busy with a previous turn."


def test_send_message_404_for_other_users_session(
    admin_user: DATestUser,
) -> None:
    body = BuildSessionManager.create(admin_user)
    session_id = body["id"]
    other_user = UserManager.create(name=f"otheruser-{uuid.uuid4().hex[:8]}")

    response = client.post(
        f"{API_SERVER_URL}/build/sessions/{session_id}/send-message",
        json={"content": "hello"},
        headers=other_user.headers,
        cookies=other_user.cookies,
    )

    assert response.status_code == 404


def test_turn_events_requires_active_turn(
    admin_user: DATestUser,
) -> None:
    body = BuildSessionManager.create(admin_user)
    session_id = uuid.UUID(body["id"])

    response = client.get(
        f"{API_SERVER_URL}/build/sessions/{session_id}/turns/{uuid.uuid4()}/events",
        headers=admin_user.headers,
        cookies=admin_user.cookies,
    )

    assert response.status_code == 409
    assert response.json()["detail"] == "Interactive turn is not running"
