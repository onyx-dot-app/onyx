"""Interactive Craft turn API tests (HTTP contract half).

These tests exercise the HTTP boundary for the background-turn flow:
``POST /send-message`` starts work and returns turn metadata, while
``GET /turns/{turn_id}/events`` is attach-only. They run in the standard
integration matrix against the in-process app with a stubbed sandbox manager
(see ``conftest.py``).

The turn runner executes in a background thread. To keep the
concurrent-turn-rejection assertion deterministic in-process, that test pins
the runner inside the stub's ``send_message`` until it has issued the second
request, so the active-turn marker is guaranteed to still be present.
"""

from __future__ import annotations

import threading
import uuid
from collections.abc import Generator
from uuid import UUID

import pytest

from onyx.server.features.build.sandbox.base import SandboxEvent
from tests.common.craft.stubs import StubSandboxManager
from tests.integration.common_utils.constants import API_SERVER_URL
from tests.integration.common_utils.http_client import client
from tests.integration.common_utils.managers.build_session import BuildSessionManager
from tests.integration.common_utils.managers.user import UserManager
from tests.integration.common_utils.test_models import DATestLLMProvider
from tests.integration.common_utils.test_models import DATestUser


def test_send_message_rejects_concurrent_active_turn(
    admin_user: DATestUser,
    _stub_sandbox_manager: StubSandboxManager,
    llm_provider: DATestLLMProvider,  # noqa: ARG001
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    body = BuildSessionManager.create(admin_user)
    session_id = uuid.UUID(body["id"])

    # Pin the background runner inside send_message so the first turn stays
    # active while we fire the second request. The runner thread blocks on
    # ``release`` (yielding nothing) until we let it finish.
    release = threading.Event()

    def _blocking_send_message(
        *_args: object, **_kwargs: object
    ) -> Generator[SandboxEvent, None, None]:
        release.wait(timeout=30.0)
        return
        yield  # pragma: no cover — makes this a generator

    monkeypatch.setattr(_stub_sandbox_manager, "send_message", _blocking_send_message)

    try:
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
    finally:
        release.set()


def test_send_message_404_for_other_users_session(
    shared_session: tuple[DATestUser, UUID],
) -> None:
    _owner, session_id = shared_session
    other_user = UserManager.create(name=f"otheruser-{uuid.uuid4().hex[:8]}")

    response = client.post(
        f"{API_SERVER_URL}/build/sessions/{session_id}/send-message",
        json={"content": "hello"},
        headers=other_user.headers,
        cookies=other_user.cookies,
    )

    assert response.status_code == 404


def test_turn_events_requires_active_turn(
    shared_session: tuple[DATestUser, UUID],
) -> None:
    owner, session_id = shared_session

    response = client.get(
        f"{API_SERVER_URL}/build/sessions/{session_id}/turns/{uuid.uuid4()}/events",
        headers=owner.headers,
        cookies=owner.cookies,
    )

    assert response.status_code == 409
    assert response.json()["detail"] == "Interactive turn is not running"
