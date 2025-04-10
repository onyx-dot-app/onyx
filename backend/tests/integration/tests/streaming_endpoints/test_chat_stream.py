from typing import Any

import pytest

from tests.integration.common_utils.constants import API_SERVER_URL
from tests.integration.common_utils.managers.chat import ChatSessionManager
from tests.integration.common_utils.managers.llm_provider import LLMProviderManager
from tests.integration.common_utils.test_models import DATestUser
from tests.integration.tests.streaming_endpoints.conftest import DocumentBuilderType


def test_send_message_simple_with_history(reset: None, admin_user: DATestUser) -> None:
    LLMProviderManager.create(user_performing_action=admin_user)

    test_chat_session = ChatSessionManager.create(user_performing_action=admin_user)

    response = ChatSessionManager.send_message(
        chat_session_id=test_chat_session.id,
        message="this is a test message",
        user_performing_action=admin_user,
    )

    assert len(response.full_message) > 0


def test_send_message__basic_searches(
    reset: None, admin_user: DATestUser, document_builder: DocumentBuilderType
) -> None:
    MESSAGE = "run a search for 'test'"
    SHORT_DOC_CONTENT = "test"
    LONG_DOC_CONTENT = "blah blah blah blah" * 100

    LLMProviderManager.create(user_performing_action=admin_user)

    short_doc = document_builder([SHORT_DOC_CONTENT])[0]

    test_chat_session = ChatSessionManager.create(user_performing_action=admin_user)
    response = ChatSessionManager.send_message(
        chat_session_id=test_chat_session.id,
        message=MESSAGE,
        user_performing_action=admin_user,
    )
    assert response.top_documents is not None
    assert len(response.top_documents) == 1
    assert response.top_documents[0].document_id == short_doc.id

    # make sure this doc is really long so that it will be split into multiple chunks
    long_doc = document_builder([LONG_DOC_CONTENT])[0]

    # new chat session for simplicity
    test_chat_session = ChatSessionManager.create(user_performing_action=admin_user)
    response = ChatSessionManager.send_message(
        chat_session_id=test_chat_session.id,
        message=MESSAGE,
        user_performing_action=admin_user,
    )
    assert response.top_documents is not None
    assert len(response.top_documents) == 2
    # short doc should be more relevant and thus first
    assert response.top_documents[0].document_id == short_doc.id
    assert response.top_documents[1].document_id == long_doc.id


@pytest.mark.skip(
    reason="enable for autorun when we have a testing environment with semantically useful data"
)
def test_send_message_simple_with_history_buffered() -> None:
    import requests

    API_KEY = ""  # fill in for this to work
    headers = {}
    headers["Authorization"] = f"Bearer {API_KEY}"

    req: dict[str, Any] = {}

    req["persona_id"] = 0
    req["description"] = "test_send_message_simple_with_history_buffered"
    response = requests.post(
        f"{API_SERVER_URL}/chat/create-chat-session", headers=headers, json=req
    )
    chat_session_id = response.json()["chat_session_id"]

    req = {}
    req["chat_session_id"] = chat_session_id
    req["message"] = "What does onyx do?"
    req["use_agentic_search"] = True

    response = requests.post(
        f"{API_SERVER_URL}/chat/send-message-simple-api", headers=headers, json=req
    )

    r_json = response.json()

    # all of these should exist and be greater than length 1
    assert len(r_json.get("answer", "")) > 0
    assert len(r_json.get("agent_sub_questions", "")) > 0
    assert len(r_json.get("agent_answers")) > 0
    assert len(r_json.get("agent_sub_queries")) > 0
    assert "agent_refined_answer_improvement" in r_json

    # top level answer should match the one we select out of agent_answers
    answer_level = 0
    agent_level_answer = ""

    agent_refined_answer_improvement = r_json.get("agent_refined_answer_improvement")
    if agent_refined_answer_improvement:
        answer_level = len(r_json["agent_answers"]) - 1

    answers = r_json["agent_answers"][str(answer_level)]
    for answer in answers:
        if answer["answer_type"] == "agent_level_answer":
            agent_level_answer = answer["answer"]
            break

    assert r_json["answer"] == agent_level_answer
    assert response.status_code == 200
