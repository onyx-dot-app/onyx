"""Resume-stream contract: an in-flight run's buffered stream can be replayed
and tailed by a second client, get-chat-session exposes the resumable run while
it is in flight, and completed or idle sessions 404 so clients fall back to the
persisted message.

The api_server runs in-process via TestClient here, which buffers a streaming
response until the app's generator finishes — a mid-stream client disconnect
cannot be simulated. The send therefore runs in a background thread and the
main thread attaches to the in-flight run; the disconnect path itself is
covered by the unit suite."""

import json
import threading
import time
from uuid import UUID

from onyx.configs.constants import MessageType
from tests.integration.common_utils.constants import API_SERVER_URL
from tests.integration.common_utils.http_client import client
from tests.integration.common_utils.managers.chat import ChatSessionManager
from tests.integration.common_utils.managers.llm_provider import LLMProviderManager
from tests.integration.common_utils.test_models import DATestChatSession
from tests.integration.common_utils.test_models import DATestUser

TERMINATED_RESPONSE_MESSAGE = (
    "Response was terminated prior to completion, try regenerating."
)
_IN_FLIGHT_WAIT_S = 30
# Long enough that the run is still generating when the main thread attaches.
_SLOW_PROMPT = "Tell me a three-paragraph story about a lighthouse."


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
    response = client.get(
        f"{API_SERVER_URL}/chat/get-chat-session/{chat_session_id}",
        headers=user.headers,
        cookies=user.cookies,
    )
    response.raise_for_status()
    return response.json()


def _send_in_background(
    test_chat_session: DATestChatSession, user: DATestUser, message: str
) -> threading.Event:
    """Run a full send on a worker thread; the returned event fires when it ends."""
    done = threading.Event()

    def _send() -> None:
        try:
            ChatSessionManager.send_message(
                chat_session_id=test_chat_session.id,
                message=message,
                user_performing_action=user,
            )
        finally:
            done.set()

    threading.Thread(target=_send, daemon=True).start()
    return done


def _wait_for_current_run(
    chat_session_id: UUID, user: DATestUser, send_done: threading.Event
) -> dict | None:
    """Poll session detail until current_run appears; None if the run ends first."""
    deadline = time.monotonic() + _IN_FLIGHT_WAIT_S
    while time.monotonic() < deadline:
        current_run = _get_session_detail(chat_session_id, user).get("current_run")
        if current_run is not None:
            return current_run
        if send_done.is_set():
            return None
        time.sleep(0.1)
    return None


def _wait_for_completed_assistant_message(
    test_chat_session: DATestChatSession, user: DATestUser, max_seconds: int = 60
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


def test_resume_replays_and_tails_in_flight_run(admin_user: DATestUser) -> None:
    LLMProviderManager.create(user_performing_action=admin_user)
    test_chat_session = ChatSessionManager.create(user_performing_action=admin_user)

    send_done = _send_in_background(test_chat_session, admin_user, _SLOW_PROMPT)
    current_run = _wait_for_current_run(test_chat_session.id, admin_user, send_done)
    assert current_run is not None, "run never became visible as in-flight"

    # Second client attaches mid-run: cursor-0 replay plus live tail to the end.
    lines = _resume_lines(test_chat_session.id, admin_user)
    assert lines is not None, "in-flight run should be resumable"
    packet_types = {
        line["obj"]["type"] for line in lines if isinstance(line.get("obj"), dict)
    }
    assert "message_delta" in packet_types or "message_start" in packet_types, (
        f"resume should replay answer packets, got types: {packet_types}"
    )

    assert send_done.wait(timeout=120)
    final_message = _wait_for_completed_assistant_message(test_chat_session, admin_user)
    assert final_message != TERMINATED_RESPONSE_MESSAGE
    assert len(final_message) > 0


def test_resume_after_completion_returns_404(admin_user: DATestUser) -> None:
    LLMProviderManager.create(user_performing_action=admin_user)
    test_chat_session = ChatSessionManager.create(user_performing_action=admin_user)

    response = ChatSessionManager.send_message(
        chat_session_id=test_chat_session.id,
        message="hello",
        user_performing_action=admin_user,
    )
    assert response.error is None

    # The processing fence clears at completion, so resume is in-flight-only;
    # settled sessions are read from the persisted message instead.
    assert _resume_lines(test_chat_session.id, admin_user) is None


def test_resume_idle_session_returns_404(admin_user: DATestUser) -> None:
    test_chat_session = ChatSessionManager.create(user_performing_action=admin_user)
    assert _resume_lines(test_chat_session.id, admin_user) is None


def test_get_chat_session_exposes_current_run(admin_user: DATestUser) -> None:
    LLMProviderManager.create(user_performing_action=admin_user)
    test_chat_session = ChatSessionManager.create(user_performing_action=admin_user)

    send_done = _send_in_background(test_chat_session, admin_user, _SLOW_PROMPT)
    current_run = _wait_for_current_run(test_chat_session.id, admin_user, send_done)
    assert current_run is not None, "in-flight run must be exposed as current_run"
    assert current_run["run_id"] > 0

    assert send_done.wait(timeout=120)
    final_message = _wait_for_completed_assistant_message(test_chat_session, admin_user)
    assert final_message != TERMINATED_RESPONSE_MESSAGE
