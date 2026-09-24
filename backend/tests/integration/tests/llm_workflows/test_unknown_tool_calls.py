from typing import Any
from uuid import UUID

from onyx.configs import app_configs
from onyx.configs.constants import DocumentSource
from onyx.llm.mock_llm_script import MockLLMStep, MockToolCall
from onyx.prompts.tool_prompts import TOOL_CALL_FAILURE_PROMPT
from onyx.server.query_and_chat.streaming_models import StreamingType
from tests.integration.common_utils.constants import API_SERVER_URL
from tests.integration.common_utils.http_client import client
from tests.integration.common_utils.managers.cc_pair import CCPairManager
from tests.integration.common_utils.managers.chat import ChatSessionManager
from tests.integration.common_utils.managers.llm_provider import LLMProviderManager
from tests.integration.common_utils.test_models import DATestUser

_DUMMY_OPENAI_API_KEY = "sk-mock-llm-workflow-tests"
_UNKNOWN_TOOL_NAME = "tool_that_does_not_exist"


def _setup(admin_user: DATestUser) -> UUID:
    assert app_configs.INTEGRATION_TESTS_MODE is True, (
        "Integration tests require INTEGRATION_TESTS_MODE=true."
    )
    # SearchTool is only exposed when at least one non-default connector exists.
    CCPairManager.create_from_scratch(
        source=DocumentSource.INGESTION_API,
        user_performing_action=admin_user,
    )
    LLMProviderManager.create(
        user_performing_action=admin_user,
        api_key=_DUMMY_OPENAI_API_KEY,
    )
    return ChatSessionManager.create(user_performing_action=admin_user).id


def _failure_response_marker(tool_call_id: str) -> str:
    # A tool message renders as its content followed by its tool_call_id.
    return f"{TOOL_CALL_FAILURE_PROMPT}\n{tool_call_id}"


def _replayed_packet_types(chat_session_id: UUID, user: DATestUser) -> list[str]:
    response = client.get(
        f"{API_SERVER_URL}/chat/get-chat-session/{chat_session_id}",
        headers=user.headers,
        cookies=user.cookies,
    )
    response.raise_for_status()
    packet_lists: list[list[dict[str, Any]]] = response.json()["packets"]
    assert len(packet_lists) == 1
    return [packet["obj"]["type"] for packet in packet_lists[0]]


def test_unknown_call_in_mixed_batch_gets_failure_response(
    admin_user: DATestUser,
) -> None:
    chat_session_id = _setup(admin_user)

    response = ChatSessionManager.send_message(
        chat_session_id=chat_session_id,
        message="what is the answer?",
        user_performing_action=admin_user,
        mock_llm_script=[
            MockLLMStep(
                tool_calls=[
                    MockToolCall(
                        id="call_search_alpha",
                        name="internal_search",
                        arguments={"queries": ["alpha"]},
                    ),
                    MockToolCall(
                        id="call_search_beta",
                        name="internal_search",
                        arguments={"queries": ["beta"]},
                    ),
                    MockToolCall(
                        id="call_unknown_tool",
                        name=_UNKNOWN_TOOL_NAME,
                        arguments={"x": 1},
                    ),
                ],
            ),
            MockLLMStep(
                text="The answer is 42.",
                match_prompt_contains=_failure_response_marker("call_unknown_tool"),
            ),
        ],
    )

    assert response.error is None, f"Unexpected stream error: {response.error}"
    assert [tc.tool_call_id for tc in response.tool_call_debug] == [
        "call_search_alpha",
        "call_search_beta",
        "call_unknown_tool",
    ]
    assert response.full_message == "The answer is 42."

    packet_types = [packet["obj"]["type"] for packet in response.packets]
    assert packet_types.count(StreamingType.SEARCH_TOOL_START.value) == 1

    replayed = _replayed_packet_types(chat_session_id, admin_user)
    assert replayed.count(StreamingType.SEARCH_TOOL_START.value) == 1
    assert StreamingType.CUSTOM_TOOL_START.value not in replayed


def test_all_unknown_calls_get_failure_responses_and_retry(
    admin_user: DATestUser,
) -> None:
    chat_session_id = _setup(admin_user)

    response = ChatSessionManager.send_message(
        chat_session_id=chat_session_id,
        message="what is the answer?",
        user_performing_action=admin_user,
        mock_llm_script=[
            MockLLMStep(
                tool_calls=[
                    MockToolCall(
                        id="call_only_unknown",
                        name=_UNKNOWN_TOOL_NAME,
                        arguments={"x": 1},
                    )
                ],
            ),
            MockLLMStep(
                text="Recovered.",
                match_prompt_contains=_failure_response_marker("call_only_unknown"),
            ),
        ],
    )

    assert response.error is None, f"Unexpected stream error: {response.error}"
    assert [tc.tool_call_id for tc in response.tool_call_debug] == ["call_only_unknown"]
    assert response.full_message == "Recovered."

    replayed = _replayed_packet_types(chat_session_id, admin_user)
    assert StreamingType.SEARCH_TOOL_START.value not in replayed
    assert StreamingType.CUSTOM_TOOL_START.value not in replayed
