"""Real HTTP streams replay accepted output, tail generation, and match saved history."""

import json
import socket
import threading
import time
from collections.abc import Iterator
from uuid import UUID

import httpx
import pytest
import uvicorn
from fastapi.testclient import TestClient

from onyx.cache.factory import get_cache_backend
from onyx.cache.interface import CacheBackend
from onyx.chat.stream_buffer import _chunk_key, _meta_key
from onyx.configs.constants import MessageType
from onyx.server.query_and_chat.models import (
    ChatSessionDetailResponse,
    SendMessageRequest,
)
from onyx.server.query_and_chat.streaming_models import (
    AgentResponseDelta,
    ChatHeartbeat,
    Packet,
)
from tests.integration.common_utils.constants import API_SERVER_URL
from tests.integration.common_utils.http_client import client
from tests.integration.common_utils.managers.chat import ChatSessionManager
from tests.integration.common_utils.managers.mock_llm import MockLLMScript
from tests.integration.common_utils.test_models import DATestUser
from tests.integration.mock_services.mock_llm_server.models import (
    Reply,
    RequestConditions,
)


@pytest.fixture(scope="module")
def streaming_api(_test_client: TestClient) -> Iterator[str]:
    """Serve the initialized application without buffering streaming responses."""
    started = threading.Event()

    class StreamingServer(uvicorn.Server):
        async def startup(self, sockets: list[socket.socket] | None = None) -> None:
            await super().startup(sockets)
            started.set()

    server = StreamingServer(
        uvicorn.Config(
            _test_client.app,
            host="127.0.0.1",
            port=0,
            lifespan="off",
            log_level="warning",
        )
    )
    assert _test_client.portal is not None
    worker = _test_client.portal.start_task_soon(server.serve)
    try:
        assert started.wait(15), "Streaming API did not start"
        port = server.servers[0].sockets[0].getsockname()[1]
        yield f"http://127.0.0.1:{port}"
    finally:
        server.should_exit = True
        worker.result(timeout=15)


def _answer_deltas(
    response: httpx.Response, *, include_heartbeats: bool = False
) -> Iterator[str]:
    response.raise_for_status()
    for line in response.iter_lines():
        if not line:
            continue
        # Message ID announcements and heartbeat lines do not contain packets.
        data = json.loads(line)
        assert "error" not in data, data
        if "obj" in data:
            packet = Packet.model_validate(data)
            if isinstance(packet.obj, AgentResponseDelta) and packet.obj.content:
                yield packet.obj.content
            elif include_heartbeats and isinstance(packet.obj, ChatHeartbeat):
                yield ""


def _get_session_detail(
    chat_session_id: UUID, user: DATestUser
) -> ChatSessionDetailResponse:
    response = client.get(
        f"{API_SERVER_URL}/chat/get-chat-session/{chat_session_id}",
        headers=user.headers,
        cookies=user.cookies,
    )
    response.raise_for_status()
    return ChatSessionDetailResponse.model_validate(response.json())


def _wait_for_buffer(cache: CacheBackend, session_id: UUID, stream_id: int) -> None:
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        if cache.exists(_meta_key(session_id, stream_id)):
            return
        time.sleep(0.01)
    pytest.fail("The active stream did not publish its resume buffer")


def test_resume_replays_and_tails_in_flight_run(
    admin_user: DATestUser, mock_llm: MockLLMScript, streaming_api: str
) -> None:
    answer = "First part. Second part. Final part."
    mock_llm.conversation(
        "resume",
        Reply(text=answer, pause_after_first_chunk="resume"),
        conditions=RequestConditions(prompt_contains=["resume-contract"]),
    )
    session = ChatSessionManager.create(user_performing_action=admin_user)
    request = SendMessageRequest(
        chat_session_id=session.id,
        message="Explain resume-contract.",
        parent_message_id=None,
        allowed_tool_ids=[],
    )
    try:
        with httpx.Client(
            base_url=streaming_api,
            headers=admin_user.headers,
            cookies=admin_user.cookies,
            timeout=30,
        ) as http:
            with http.stream(
                "POST", "/chat/send-chat-message", json=request.model_dump(mode="json")
            ) as original:
                sent = _answer_deltas(original, include_heartbeats=True)
                first = next(sent)
                assert first and first != answer
                # Generation stays gated until both HTTP streams send a keepalive.
                assert next(sent) == ""
                current = _get_session_detail(session.id, admin_user).current_stream
                assert current is not None and current.stream_id > 0
                _wait_for_buffer(get_cache_backend(), session.id, current.stream_id)

                with http.stream(
                    "GET", f"/chat/chat-session/{session.id}/resume-stream?cursor=0"
                ) as resumed:
                    replay = _answer_deltas(resumed, include_heartbeats=True)
                    assert next(replay) == first
                    assert next(replay) == ""
                    # Both clients saw the prefix before generation can finish.
                    mock_llm.release_gate("resume")
                    replayed_text = first + "".join(replay)
                original_text = first + "".join(sent)

        history = ChatSessionManager.get_chat_history(
            chat_session=session, user_performing_action=admin_user
        )
        saved = [
            row.message for row in history if row.message_type == MessageType.ASSISTANT
        ]
        assert saved == [answer]
        assert replayed_text == original_text == saved[0]
        assert _get_session_detail(session.id, admin_user).current_stream is None
    finally:
        mock_llm.release_gate("resume")


def test_resume_after_completion_returns_404(
    admin_user: DATestUser, mock_llm: MockLLMScript
) -> None:
    mock_llm.conversation(
        "complete",
        Reply(text="Done."),
        conditions=RequestConditions(prompt_contains=["completion-contract"]),
    )
    session = ChatSessionManager.create(user_performing_action=admin_user)
    response = ChatSessionManager.send_message(
        chat_session_id=session.id,
        message="completion-contract",
        allowed_tool_ids=[],
        user_performing_action=admin_user,
    )
    assert response.error is None
    assert response.full_message == "Done."
    resumed = client.get(
        f"{API_SERVER_URL}/chat/chat-session/{session.id}/resume-stream",
        headers=admin_user.headers,
        cookies=admin_user.cookies,
    )
    assert resumed.status_code == 404


def test_resume_idle_session_returns_404(admin_user: DATestUser) -> None:
    session = ChatSessionManager.create(user_performing_action=admin_user)
    response = client.get(
        f"{API_SERVER_URL}/chat/chat-session/{session.id}/resume-stream",
        headers=admin_user.headers,
        cookies=admin_user.cookies,
    )
    assert response.status_code == 404


@pytest.mark.parametrize("evicted_record", ["chunk", "metadata"])
def test_evicted_resume_buffer_preserves_completion_and_next_turn(
    admin_user: DATestUser,
    mock_llm: MockLLMScript,
    streaming_api: str,
    evicted_record: str,
) -> None:
    answer = "The accepted answer survives cache eviction."
    mock_llm.conversation(
        "eviction",
        Reply(text=answer, pause_after_first_chunk="eviction"),
        Reply(text="The next turn works."),
        conditions=RequestConditions(prompt_contains=["eviction-contract"]),
    )
    session = ChatSessionManager.create(user_performing_action=admin_user)
    request = SendMessageRequest(
        chat_session_id=session.id,
        message="Explain eviction-contract.",
        parent_message_id=None,
        allowed_tool_ids=[],
    )
    try:
        with httpx.Client(
            base_url=streaming_api,
            headers=admin_user.headers,
            cookies=admin_user.cookies,
            timeout=30,
        ) as http:
            with http.stream(
                "POST", "/chat/send-chat-message", json=request.model_dump(mode="json")
            ) as original:
                sent = _answer_deltas(original)
                first = next(sent)
                assert first and first != answer
                current = _get_session_detail(session.id, admin_user).current_stream
                assert current is not None
                cache = get_cache_backend()
                _wait_for_buffer(cache, session.id, current.stream_id)
                resume_url = f"/chat/chat-session/{session.id}/resume-stream?cursor=0"
                # Wait for the shared buffer to contain the prefix before evicting it.
                with http.stream("GET", resume_url) as replay:
                    assert next(_answer_deltas(replay)) == first

                key = (
                    _chunk_key(session.id, current.stream_id, 0)
                    if evicted_record == "chunk"
                    else _meta_key(session.id, current.stream_id)
                )
                assert cache.exists(key)
                cache.delete(key)
                with http.stream("GET", resume_url) as failed_resume:
                    if evicted_record == "chunk":
                        assert failed_resume.status_code == 200
                        assert list(failed_resume.iter_lines()) == []
                    else:
                        assert failed_resume.status_code == 404
                        assert "No resumable stream" in failed_resume.read().decode()
                assert (
                    _get_session_detail(session.id, admin_user).current_stream
                    is not None
                )
                mock_llm.release_gate("eviction")
                assert first + "".join(sent) == answer

        settled = _get_session_detail(session.id, admin_user)
        assert settled.current_stream is None
        assert [
            message.message
            for message in settled.messages
            if message.message_type == MessageType.ASSISTANT
        ] == [answer]
        followup = ChatSessionManager.send_message(
            chat_session_id=session.id,
            message="Continue eviction-contract.",
            allowed_tool_ids=[],
            user_performing_action=admin_user,
        )
        assert followup.error is None
        assert followup.full_message == "The next turn works."
        continued = mock_llm.requests_in("eviction")[-1]
        assert any(
            message.role == "assistant" and message.content == answer
            for message in continued.messages
        )
        history = _get_session_detail(session.id, admin_user)
        assert [
            message.message
            for message in history.messages
            if message.message_type == MessageType.ASSISTANT
        ] == [answer, "The next turn works."]
    finally:
        mock_llm.release_gate("eviction")
