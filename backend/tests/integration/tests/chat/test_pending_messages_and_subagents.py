"""Incognito chat limits through the real chat API."""

from collections.abc import Generator
from uuid import UUID, uuid4

import pytest

from onyx.coding_agent.tool_definitions import CODING_AGENT_TOOL_NAME
from onyx.configs.constants import MessageType
from onyx.server.query_and_chat.models import (
    ChatSessionCreationRequest,
    ChatSessionDetailResponse,
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

SECURITY_URL = f"{API_SERVER_URL}/admin/security"


def _detail(session_id: UUID, user: DATestUser) -> ChatSessionDetailResponse:
    response = client.get(
        f"{API_SERVER_URL}/chat/get-chat-session/{session_id}",
        headers=user.headers,
    )
    response.raise_for_status()
    return ChatSessionDetailResponse.model_validate(response.json())


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
    """Incognito rejects deep research and offers the model no coding agent."""
    nonce = uuid4().hex
    mock_llm.conversation(
        nonce,
        Reply(text="Private answer."),
        conditions=RequestConditions(prompt_contains=[nonce]),
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
            private_id, f"Private chat. {nonce}", admin_user
        )
        assert private.full_message == "Private answer."
    finally:
        client.delete(
            f"{API_SERVER_URL}/chat/delete-chat-session/{private_id}",
            headers=admin_user.headers,
        ).raise_for_status()
    [private_request] = mock_llm.requests_in(nonce)
    assert CODING_AGENT_TOOL_NAME not in private_request.tools
