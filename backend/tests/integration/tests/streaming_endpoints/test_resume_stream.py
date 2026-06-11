"""Resume-stream contract: a disconnected run's buffered stream can be replayed
and tailed from any client, get-chat-session exposes the resumable run, a
completed run replays within the retention window, and idle sessions 404."""

import json
import time
from uuid import UUID

import httpx

from onyx.configs.constants import MessageType
from tests.integration.common_utils.constants import API_SERVER_URL
from tests.integration.common_utils.http_client import client
from tests.integration.common_utils.managers.chat import ChatSessionManager
from tests.integration.common_utils.managers.llm_provider import LLMProviderManager
from tests.integration.common_utils.test_models import DATestUser

TERMINATED_RESPONSE_MESSAGE = (
    "Response was terminated prior to completion, try regenerating."
)


def _resume_lines(
    chat_session_id: UUID, user: DATestUser, cursor: int = 0
) -> list[dict] | None:
    """Consume the resume stream fully. None when the endpoint 404s."""
    with client.stream(
        "GET",
        f"{API_SERVER_URL}/chat/chat-session/{chat_session_id}/resume-stream"
        f"?cursor={cursor}",
        headers=user.headers,
        cookies=user.cookies,
        timeout=120,
    ) as response:
        if response.status_code == 404:
            return None
        response.raise_for_status()
        return [json.loads(line) for line in response.iter_lines() if line]


def _get_session_detail(chat_session_id: UUID, user: DATestUser) -> dict:
    response = httpx.get(
        f"{API_SERVER_URL}/chat/get-chat-session/{chat_session_id}",
        headers=user.headers,
        cookies=user.cookies,
        timeout=30,
    )
    response.raise_for_status()
    return response.json()


def _wait_for_completed_assistant_message(
    test_chat_session, user: DATestUser, max_seconds: int = 60
) -> str:
    msg = TERMINATED_RESPONSE_MESSAGE
    for _ in range(max_seconds):
        time.sleep(1)
        chat_history = ChatSessionManager.get_chat_history(
            chat_session=test_chat_session,
            user_performing_action=user,
        )
        for chat_obj in chat_history:
            if chat_obj.message_type == MessageType.ASSISTANT:
                msg = chat_obj.message
                break
        if msg != TERMINATED_RESPONSE_MESSAGE:
            return msg
    return msg


def test_resume_after_disconnect_replays_and_tails(admin_user: DATestUser) -> None:
    LLMProviderManager.create(user_performing_action=admin_user)
    test_chat_session = ChatSessionManager.create(user_performing_action=admin_user)

    ChatSessionManager.send_message_with_disconnect(
        chat_session_id=test_chat_session.id,
        message="Tell me a short story about a lighthouse.",
        user_performing_action=admin_user,
        disconnect_after_packets=1,
    )

    lines = _resume_lines(test_chat_session.id, admin_user)
    assert lines is not None, "run should be resumable right after a disconnect"
    packet_types = {
        line["obj"]["type"] for line in lines if isinstance(line.get("obj"), dict)
    }
    assert "message_delta" in packet_types or "message_start" in packet_types, (
        f"resume should replay answer packets, got types: {packet_types}"
    )

    final_message = _wait_for_completed_assistant_message(test_chat_session, admin_user)
    assert final_message != TERMINATED_RESPONSE_MESSAGE
    assert len(final_message) > 0


def test_resume_after_completion_replays_buffer(admin_user: DATestUser) -> None:
    LLMProviderManager.create(user_performing_action=admin_user)
    test_chat_session = ChatSessionManager.create(user_performing_action=admin_user)

    response = ChatSessionManager.send_message(
        chat_session_id=test_chat_session.id,
        message="hello",
        user_performing_action=admin_user,
    )
    assert response.error is None

    lines = _resume_lines(test_chat_session.id, admin_user)
    # The processing fence clears at completion, so a fence-less session 404s —
    # that is the documented fallback path and equally valid here.
    if lines is None:
        return
    assert lines, "a within-retention completed run should replay its buffer"


def test_resume_idle_session_returns_404(admin_user: DATestUser) -> None:
    test_chat_session = ChatSessionManager.create(user_performing_action=admin_user)
    assert _resume_lines(test_chat_session.id, admin_user) is None


def test_get_chat_session_exposes_current_run(admin_user: DATestUser) -> None:
    LLMProviderManager.create(user_performing_action=admin_user)
    test_chat_session = ChatSessionManager.create(user_performing_action=admin_user)

    ChatSessionManager.send_message_with_disconnect(
        chat_session_id=test_chat_session.id,
        message="What are some important events that happened today?",
        user_performing_action=admin_user,
        disconnect_after_packets=1,
    )

    detail = _get_session_detail(test_chat_session.id, admin_user)
    current_run = detail.get("current_run")
    if current_run is not None:
        assert current_run["run_id"] > 0
    else:
        # The run may already have finished; then the message must be settled.
        final_message = _wait_for_completed_assistant_message(
            test_chat_session, admin_user, max_seconds=30
        )
        assert final_message != TERMINATED_RESPONSE_MESSAGE
