from typing import Any

import pytest

from tests.integration.common_utils.constants import API_SERVER_URL
from tests.integration.common_utils.managers.chat import ChatSessionManager
from tests.integration.common_utils.managers.llm_provider import LLMProviderManager
from tests.integration.common_utils.managers.user import UserManager
from tests.integration.common_utils.test_models import DATestUser


def test_send_message_simple_with_history(reset: None) -> None:
    admin_user: DATestUser = UserManager.create(name="admin_user")
    LLMProviderManager.create(user_performing_action=admin_user)

    test_chat_session = ChatSessionManager.create(user_performing_action=admin_user)

    response = ChatSessionManager.send_message(
        chat_session_id=test_chat_session.id,
        message="this is a test message",
        user_performing_action=admin_user,
    )

    assert len(response.full_message) > 0


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
