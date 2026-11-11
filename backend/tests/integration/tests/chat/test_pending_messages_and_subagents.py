"""Pending human messages and background subagents through the real chat API."""

import time
from collections.abc import Callable, Generator
from concurrent.futures import ThreadPoolExecutor
from uuid import UUID, uuid4

import pytest

from onyx.agents.models import MessageDelivery, RunStatus
from onyx.chat.models import PendingChatMessage
from onyx.coding_agent.tool_definitions import CODING_AGENT_TOOL_NAME
from onyx.configs.constants import MessageType
from onyx.llm.override_models import LLMOverride
from onyx.server.query_and_chat.models import (
    ChatSessionCreationRequest,
    ChatSessionDetailResponse,
    ChatSessionProcessingStatus,
    PendingChatMessageRequest,
)
from onyx.tools.constants import SEND_MESSAGE_TOOL_NAME, SPAWN_AGENT_TOOL_NAME
from tests.integration.common_utils.constants import API_SERVER_URL
from tests.integration.common_utils.http_client import client
from tests.integration.common_utils.managers.chat import ChatSessionManager
from tests.integration.common_utils.managers.llm_provider import LLMProviderManager
from tests.integration.common_utils.managers.mock_llm import (
    MockLLMManager,
    MockLLMScript,
)
from tests.integration.common_utils.test_models import DATestUser
from tests.integration.mock_services.mock_llm_server.models import (
    Reply,
    RequestConditions,
    ToolCall,
)

WAIT_TIMEOUT_S = 60
SECURITY_URL = f"{API_SERVER_URL}/admin/security"
SUBAGENT_TOOLS = {
    SPAWN_AGENT_TOOL_NAME,
    SEND_MESSAGE_TOOL_NAME,
    "list_agents",
    "interrupt_agent",
}
CHOSEN_MODEL = "mock-chosen-model"


def _wait_until(condition: Callable[[], bool], description: str) -> None:
    deadline = time.monotonic() + WAIT_TIMEOUT_S
    while time.monotonic() < deadline:
        if condition():
            return
        time.sleep(0.2)
    raise AssertionError(f"Timed out waiting until {description}")


def _status(session_id: UUID, user: DATestUser) -> ChatSessionProcessingStatus:
    response = client.get(
        f"{API_SERVER_URL}/chat/chat-session/{session_id}/status",
        headers=user.headers,
    )
    response.raise_for_status()
    return ChatSessionProcessingStatus.model_validate(response.json())


def _detail(session_id: UUID, user: DATestUser) -> ChatSessionDetailResponse:
    # Unlike /status, reading the session never dispatches queued work.
    response = client.get(
        f"{API_SERVER_URL}/chat/get-chat-session/{session_id}",
        headers=user.headers,
    )
    response.raise_for_status()
    return ChatSessionDetailResponse.model_validate(response.json())


def _texts(detail: ChatSessionDetailResponse, message_type: MessageType) -> list[str]:
    return [
        message.message
        for message in sorted(detail.messages, key=lambda m: m.message_id)
        if message.message_type == message_type
    ]


def _pending_url(session_id: UUID) -> str:
    return f"{API_SERVER_URL}/chat/chat-session/{session_id}/pending-messages"


def _submit(session_id: UUID, user: DATestUser, message: str) -> PendingChatMessage:
    response = client.post(
        _pending_url(session_id),
        json=PendingChatMessageRequest(
            message=message, delivery=MessageDelivery.QUEUE
        ).model_dump(mode="json"),
        headers=user.headers,
    )
    response.raise_for_status()
    return PendingChatMessage.model_validate(response.json())


def _pending(session_id: UUID, user: DATestUser) -> list[str]:
    response = client.get(_pending_url(session_id), headers=user.headers)
    response.raise_for_status()
    return [PendingChatMessage.model_validate(item).message for item in response.json()]


def test_pending_messages_queue_withdraw_stop_and_send_now(
    admin_user: DATestUser, mock_llm: MockLLMScript
) -> None:
    """Queued messages wait for the running answer, Stop pauses them, and
    Send now starts one message ahead of the rest of the queue."""
    nonce = uuid4().hex
    question = f"Explain queued messages. {nonce}"
    first, sent_now, withdrawn = "First queued", "Send this now", "Withdraw this"
    edited = "Edited after withdrawal"
    mock_llm.conversation(
        nonce,
        Reply(text="Working on it.\n\nDone.", pause_after_first_chunk=nonce),
        Reply(
            text="Answer to the urgent message.",
            conditions=RequestConditions(prompt_contains=[sent_now]),
        ),
        Reply(
            text="Answer to the first message.",
            conditions=RequestConditions(prompt_contains=[first]),
        ),
        Reply(
            text="Answer to the edited message.",
            conditions=RequestConditions(prompt_contains=[edited]),
        ),
        conditions=RequestConditions(prompt_contains=[nonce]),
    )
    session = ChatSessionManager.create(user_performing_action=admin_user)
    with ThreadPoolExecutor(max_workers=1) as executor:
        try:
            held = executor.submit(
                ChatSessionManager.send_message, session.id, question, admin_user
            )
            # The answer is running once the model receives its request.
            _wait_until(
                lambda: bool(mock_llm.requests_in(nonce)), "the answer is running"
            )

            # Messages submitted during the answer wait in submission order.
            _submit(session.id, admin_user, first)
            urgent = _submit(session.id, admin_user, sent_now)
            discarded = _submit(session.id, admin_user, withdrawn)
            assert _pending(session.id, admin_user) == [first, sent_now, withdrawn]

            # Withdrawing returns the text for editing and removes it; the
            # edited text joins the end of the queue.
            withdraw_url = f"{_pending_url(session.id)}/{discarded.id}"
            response = client.delete(withdraw_url, headers=admin_user.headers)
            response.raise_for_status()
            assert PendingChatMessage.model_validate(response.json()).message == (
                withdrawn
            )
            assert (
                client.delete(withdraw_url, headers=admin_user.headers).status_code
                == 409
            )
            _submit(session.id, admin_user, edited)
            assert _pending(session.id, admin_user) == [first, sent_now, edited]

            # Stop ends the answer and pauses the queue.
            client.post(
                f"{API_SERVER_URL}/chat/stop-chat-session/{session.id}",
                headers=admin_user.headers,
            ).raise_for_status()
            mock_llm.release_gate(nonce)
            held.result(timeout=WAIT_TIMEOUT_S)
            _wait_until(
                lambda: not _status(session.id, admin_user).is_processing,
                "the stopped answer releases the chat",
            )
        finally:
            mock_llm.release_gate(nonce)
    status = _status(session.id, admin_user)
    assert not status.has_startable_input
    assert _pending(session.id, admin_user) == [first, sent_now, edited]
    stopped = _detail(session.id, admin_user)
    assert [
        message.response_status
        for message in stopped.messages
        if message.message_type == MessageType.ASSISTANT
    ] == [RunStatus.CANCELLED]

    # Send now starts its message; the rest of the queue follows in order.
    client.post(
        f"{_pending_url(session.id)}/{urgent.id}/interrupt", headers=admin_user.headers
    ).raise_for_status()

    def queue_drained() -> bool:
        detail = _detail(session.id, admin_user)
        return (
            len(_texts(detail, MessageType.ASSISTANT)) == 4 and not detail.is_processing
        )

    _wait_until(queue_drained, "the queued messages are answered")
    detail = _detail(session.id, admin_user)
    assert _texts(detail, MessageType.USER) == [question, sent_now, first, edited]
    assert _texts(detail, MessageType.ASSISTANT)[1:] == [
        "Answer to the urgent message.",
        "Answer to the first message.",
        "Answer to the edited message.",
    ]
    assert _pending(session.id, admin_user) == []
    assert not _status(session.id, admin_user).has_startable_input


def test_background_agent_result_wakes_the_idle_chat(
    admin_user: DATestUser, mock_llm: MockLLMScript
) -> None:
    """A finished root releases the chat while its child runs; the child's
    result starts a follow-up under a hidden question. Turns that the server
    starts use the model the user chose, not the default model."""
    nonce = uuid4().hex
    question = f"Research in the background. {nonce}"
    child_task = f"Find the answer. {uuid4().hex}"
    queued = "A question while research runs"
    child_result = "Private child result: forty-two."
    mock_llm.conversation(
        nonce,
        Reply(
            tool_calls=[
                ToolCall(
                    id="spawn-research",
                    name="spawn_agent",
                    arguments={"name": "research", "instruction": child_task},
                )
            ]
        ),
        Reply(
            text="Research started.",
            conditions=RequestConditions(has_results_for=["spawn-research"]),
        ),
        Reply(
            text="Answer while research runs.",
            conditions=RequestConditions(prompt_contains=[queued]),
        ),
        Reply(
            text="Final answer: forty-two.",
            conditions=RequestConditions(prompt_contains=[child_result]),
        ),
        conditions=RequestConditions(prompt_contains=[nonce]),
    )
    mock_llm.conversation(
        child_task,
        Reply(text=child_result, pause_after_first_chunk=child_task),
        conditions=RequestConditions(prompt_contains=[child_task]),
    )
    chosen = MockLLMManager.create(
        mock_llm.api_base, admin_user, model_name=CHOSEN_MODEL, make_default=False
    )
    session = ChatSessionManager.create(user_performing_action=admin_user)
    try:
        started = ChatSessionManager.send_message(
            session.id,
            question,
            admin_user,
            llm_override=LLMOverride(
                model_configuration_id=chosen.model_configuration_ids[0]
            ),
        )
        assert started.error is None
        assert started.full_message == "Research started."
        _wait_until(
            lambda: bool(mock_llm.requests_in(child_task)), "the child is running"
        )

        # The finished root releases the chat while its child works.
        status = _status(session.id, admin_user)
        assert status.has_active_subagents
        assert not status.is_processing

        # A queued message starts a turn without waiting for the child.
        _submit(session.id, admin_user, queued)

        def queued_answered() -> bool:
            detail = _detail(session.id, admin_user)
            return (
                "Answer while research runs." in _texts(detail, MessageType.ASSISTANT)
                and not detail.is_processing
            )

        _wait_until(queued_answered, "the queued message is answered")
        assert _status(session.id, admin_user).has_active_subagents

        # The child's result wakes the idle chat.
        mock_llm.release_gate(child_task)

        def follow_up_finished() -> bool:
            detail = _detail(session.id, admin_user)
            return (
                "Final answer: forty-two." in _texts(detail, MessageType.ASSISTANT)
                and not detail.is_processing
                and not _status(session.id, admin_user).has_active_subagents
            )

        _wait_until(follow_up_finished, "the child result is answered")
    finally:
        mock_llm.release_gate(child_task)
        LLMProviderManager.delete(chosen, user_performing_action=admin_user)

    detail = _detail(session.id, admin_user)
    # The follow-up's question is hidden and has no text.
    assert _texts(detail, MessageType.USER) == [question, queued]
    assert _texts(detail, MessageType.AGENT_RESULTS) == [""]
    assert _texts(detail, MessageType.ASSISTANT) == [
        "Research started.",
        "Answer while research runs.",
        "Final answer: forty-two.",
    ]
    status = _status(session.id, admin_user)
    assert not status.has_active_subagents
    assert not status.has_startable_input
    # The queued turn and the result follow-up both use the chosen model.
    root_requests = mock_llm.requests_in(nonce)
    assert len(root_requests) == 4
    assert {request.body["model"] for request in root_requests} == {CHOSEN_MODEL}


@pytest.fixture
def incognito_enabled(admin_user: DATestUser) -> Generator[None, None, None]:
    response = client.get(SECURITY_URL, headers=admin_user.headers)
    response.raise_for_status()
    previous = {
        key: response.json()[key]
        for key in ("incognito_availability", "incognito_record_mode")
    }
    client.put(
        SECURITY_URL,
        json={
            "incognito_availability": "everyone",
            "incognito_record_mode": "usage_only",
        },
        headers=admin_user.headers,
    ).raise_for_status()
    yield
    client.put(
        SECURITY_URL, json=previous, headers=admin_user.headers
    ).raise_for_status()


def test_incognito_chat_has_no_child_agents(
    admin_user: DATestUser,
    mock_llm: MockLLMScript,
    incognito_enabled: None,  # noqa: ARG001
) -> None:
    """Incognito rejects deep research and offers the model no child-agent tools."""
    nonce = uuid4().hex
    mock_llm.conversation(
        nonce,
        Reply(text="Normal answer."),
        Reply(text="Private answer."),
        conditions=RequestConditions(prompt_contains=[nonce]),
    )
    normal = ChatSessionManager.create(user_performing_action=admin_user)
    ChatSessionManager.send_message(normal.id, f"Normal chat. {nonce}", admin_user)
    created = client.post(
        f"{API_SERVER_URL}/chat/create-chat-session",
        json=ChatSessionCreationRequest(persona_id=0, incognito=True).model_dump(
            mode="json"
        ),
        headers=admin_user.headers,
    )
    created.raise_for_status()
    private_id = UUID(created.json()["chat_session_id"])
    try:
        research = ChatSessionManager.send_message(
            private_id, f"Research privately. {nonce}", admin_user, deep_research=True
        )
        assert research.error is not None
        assert research.error.error == (
            "Deep research is not available in incognito. "
            "Start a normal chat to use it."
        )
        private = ChatSessionManager.send_message(
            private_id, f"Private chat. {nonce}", admin_user
        )
        assert private.full_message == "Private answer."
    finally:
        client.delete(
            f"{API_SERVER_URL}/chat/delete-chat-session/{private_id}",
            headers=admin_user.headers,
        ).raise_for_status()
    normal_request, private_request = mock_llm.requests_in(nonce)
    assert SUBAGENT_TOOLS <= set(normal_request.tools)
    assert not {*SUBAGENT_TOOLS, CODING_AGENT_TOOL_NAME} & set(private_request.tools)
