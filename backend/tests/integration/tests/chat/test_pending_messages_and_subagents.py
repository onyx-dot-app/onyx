"""Pending human messages and background subagents through the real chat API."""

import json
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
    requires_code_mode,
)
from tests.integration.common_utils.managers.persona import PersonaManager
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
    # The released answer can finish before the turn reads Stop. Either way
    # the queue pauses, and a finished answer keeps its status.
    stopped = _detail(session.id, admin_user)
    [stopped_status] = [
        message.response_status
        for message in stopped.messages
        if message.message_type == MessageType.ASSISTANT
    ]
    assert stopped_status in (RunStatus.CANCELLED, RunStatus.COMPLETE)

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


def test_interrupt_while_a_response_streams(
    admin_user: DATestUser, mock_llm: MockLLMScript
) -> None:
    """An interrupting message stops the streaming answer, keeps its partial
    text, and starts before messages queued earlier."""
    nonce = uuid4().hex
    question = f"Write a long answer. {nonce}"
    queued, urgent = "Queued earlier", "Interrupt with this"
    mock_llm.conversation(
        nonce,
        Reply(
            text="Partial answer.\n\nThe rest of the answer.",
            pause_after_first_chunk=nonce,
            heartbeat_while_paused=True,
        ),
        Reply(
            text="Answer to the interruption.",
            conditions=RequestConditions(prompt_contains=[urgent]),
        ),
        Reply(
            text="Answer to the queued message.",
            conditions=RequestConditions(prompt_contains=[queued]),
        ),
        conditions=RequestConditions(prompt_contains=[nonce]),
    )
    session = ChatSessionManager.create(user_performing_action=admin_user)
    with ThreadPoolExecutor(max_workers=1) as executor:
        try:
            held = executor.submit(
                ChatSessionManager.send_message, session.id, question, admin_user
            )
            _wait_until(
                lambda: bool(mock_llm.requests_in(nonce)), "the answer is streaming"
            )
            _submit(session.id, admin_user, queued)
            client.post(
                _pending_url(session.id),
                json=PendingChatMessageRequest(
                    message=urgent, delivery=MessageDelivery.INTERRUPT
                ).model_dump(mode="json"),
                headers=admin_user.headers,
            ).raise_for_status()
            held.result(timeout=WAIT_TIMEOUT_S)
        finally:
            mock_llm.release_gate(nonce)

    def answered() -> bool:
        detail = _detail(session.id, admin_user)
        return (
            len(_texts(detail, MessageType.ASSISTANT)) == 3 and not detail.is_processing
        )

    _wait_until(answered, "the interruption and the queue are answered")
    detail = _detail(session.id, admin_user)
    assert _texts(detail, MessageType.USER) == [question, urgent, queued]
    stopped, *answers = sorted(
        (
            message
            for message in detail.messages
            if message.message_type == MessageType.ASSISTANT
        ),
        key=lambda message: message.message_id,
    )
    assert stopped.response_status == RunStatus.CANCELLED
    assert stopped.message.startswith("Partial answer")
    assert "rest of the answer" not in stopped.message
    assert [message.message for message in answers] == [
        "Answer to the interruption.",
        "Answer to the queued message.",
    ]
    assert _pending(session.id, admin_user) == []


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
        # Like the web composer, record the sent model as the chat's model;
        # turns that the server starts use it.
        client.put(
            f"{API_SERVER_URL}/chat/update-chat-session-model",
            json={
                "chat_session_id": str(session.id),
                "new_alternate_model": f"{chosen.name}__{chosen.provider}__"
                f"{CHOSEN_MODEL}__mc:{chosen.model_configuration_ids[0]}",
            },
            headers=admin_user.headers,
        ).raise_for_status()
        started = ChatSessionManager.send_message(
            session.id,
            question,
            admin_user,
            llm_override=LLMOverride(
                model_configuration_id=chosen.model_configuration_ids[0]
            ),
            accepts_follow_ups=True,
        )
        assert started.error is None
        assert started.full_message == "Research started."
        _wait_until(
            lambda: bool(mock_llm.requests_in(child_task)), "the child is running"
        )

        # The finished root releases the chat while its child works.
        def released_with_active_child() -> bool:
            status = _status(session.id, admin_user)
            return status.has_active_subagents and not status.is_processing

        _wait_until(released_with_active_child, "the root releases the chat")

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


@requires_code_mode(True)
def test_a_background_agent_runs_programs_in_code_mode(
    admin_user: DATestUser, mock_llm: MockLLMScript
) -> None:
    """In code mode the root keeps `spawn_agent` as a tool of its own, and the
    child calls tools from its own `execute_code` programs."""
    nonce = uuid4().hex
    child_task = f"Compute the answer. {uuid4().hex}"
    mock_llm.conversation(
        nonce,
        Reply(
            tool_calls=[
                ToolCall(
                    id="spawn-compute",
                    name=SPAWN_AGENT_TOOL_NAME,
                    arguments={"name": "compute", "instruction": child_task},
                )
            ],
            conditions=RequestConditions(
                offers=[SPAWN_AGENT_TOOL_NAME, "execute_code"]
            ),
        ),
        Reply(
            text="Computing in the background.",
            conditions=RequestConditions(has_results_for=["spawn-compute"]),
        ),
        Reply(
            text="The child computed forty-two.",
            conditions=RequestConditions(prompt_contains=["Child program printed"]),
        ),
        conditions=RequestConditions(prompt_contains=[nonce]),
    )
    mock_llm.conversation(
        child_task,
        Reply(
            tool_calls=[
                ToolCall(
                    id="child-program",
                    name="execute_code",
                    arguments={"code": "print(6 * 7)"},
                )
            ],
            conditions=RequestConditions(offers=["execute_code"]),
        ),
        Reply(
            text="Child program printed 42.",
            conditions=RequestConditions(has_results_for=["child-program"]),
        ),
        conditions=RequestConditions(prompt_contains=[child_task]),
    )
    session = ChatSessionManager.create(user_performing_action=admin_user)
    started = ChatSessionManager.send_message(
        session.id,
        f"Compute in the background. {nonce}",
        admin_user,
        accepts_follow_ups=True,
    )
    assert started.error is None
    assert started.full_message == "Computing in the background."

    def follow_up_finished() -> bool:
        detail = _detail(session.id, admin_user)
        return (
            "The child computed forty-two." in _texts(detail, MessageType.ASSISTANT)
            and not detail.is_processing
            and not _status(session.id, admin_user).has_active_subagents
        )

    _wait_until(follow_up_finished, "the child result is answered")
    _, child_answer_request = mock_llm.requests_in(child_task)
    assert "42" in (child_answer_request.tool_result("child-program") or "")


def test_turns_the_server_starts_use_the_current_tool_selection(
    admin_user: DATestUser, mock_llm: MockLLMScript
) -> None:
    """The chat keeps the user's tool selection: a queued turn offers the
    tools selected when it starts, not the tools of the last sent message."""
    nonce = uuid4().hex
    enabled, blocked = "Queued with the tool", "Queued without the tool"
    created = client.post(
        f"{API_SERVER_URL}/admin/tool/custom",
        json={
            "name": f"selection-{nonce}",
            "description": "Ping a service",
            "definition": {
                "openapi": "3.0.0",
                "info": {"title": "Ping", "description": "Ping", "version": "1.0.0"},
                "servers": [{"url": "https://example.com"}],
                "paths": {
                    "/ping": {
                        "get": {
                            "summary": "Ping the service",
                            "operationId": "ping",
                            "responses": {"200": {"description": "ok"}},
                        }
                    }
                },
            },
            "custom_headers": [],
            "passthrough_auth": False,
        },
        headers=admin_user.headers,
    )
    created.raise_for_status()
    tool_id = int(created.json()["id"])
    tool_name = f"custom__{tool_id}__ping"
    persona = PersonaManager.create(
        tool_ids=[tool_id], user_performing_action=admin_user
    )
    mock_llm.conversation(
        nonce,
        Reply(text="Answer without the tool."),
        Reply(
            text="Answer with the tool.",
            conditions=RequestConditions(prompt_contains=[enabled]),
        ),
        Reply(
            text="Answer without the tool again.",
            conditions=RequestConditions(prompt_contains=[blocked]),
        ),
        conditions=RequestConditions(prompt_contains=[nonce]),
    )
    selection_url = f"{API_SERVER_URL}/chat/chat-session/{{}}/tool-selection"
    try:
        session = ChatSessionManager.create(
            persona_id=persona.id, user_performing_action=admin_user
        )
        sent = ChatSessionManager.send_message(
            session.id, f"Start without tools. {nonce}", admin_user, allowed_tool_ids=[]
        )
        assert sent.error is None
        for message, selection, answer in (
            (enabled, [tool_id], "Answer with the tool."),
            (blocked, [], "Answer without the tool again."),
        ):
            client.patch(
                selection_url.format(session.id),
                json={"allowed_tool_ids": selection, "preferred_tool_id": None},
                headers=admin_user.headers,
            ).raise_for_status()
            _submit(session.id, admin_user, message)

            def answered(answer: str = answer) -> bool:
                detail = _detail(session.id, admin_user)
                return (
                    answer in _texts(detail, MessageType.ASSISTANT)
                    and not detail.is_processing
                )

            _wait_until(answered, f"the queued turn answers: {answer}")
    finally:
        assert PersonaManager.delete(persona, user_performing_action=admin_user)
        client.delete(
            f"{API_SERVER_URL}/admin/tool/custom/{tool_id}", headers=admin_user.headers
        ).raise_for_status()
    # Code mode defers the tool: a program finds it with `tool_search`.
    assert [
        tool_name in request.tools
        or "tool_search(" in json.dumps(request.body.get("tools", []))
        for request in mock_llm.requests_in(nonce)
    ] == [False, True, False]


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
    ChatSessionManager.send_message(
        normal.id, f"Normal chat. {nonce}", admin_user, accepts_follow_ups=True
    )
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
        # The rejected request saved no question or response.
        assert not [
            message
            for message in _detail(private_id, admin_user).messages
            if message.message_type in (MessageType.USER, MessageType.ASSISTANT)
        ]
        private = ChatSessionManager.send_message(
            private_id, f"Private chat. {nonce}", admin_user, accepts_follow_ups=True
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
