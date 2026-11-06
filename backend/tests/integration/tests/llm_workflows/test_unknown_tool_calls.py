from typing import Any
from uuid import UUID

from onyx.configs.constants import DocumentSource
from onyx.server.query_and_chat.streaming_models import StreamingType
from tests.integration.common_utils.constants import API_SERVER_URL
from tests.integration.common_utils.http_client import client
from tests.integration.common_utils.managers.cc_pair import CCPairManager
from tests.integration.common_utils.managers.chat import ChatSessionManager
from tests.integration.common_utils.managers.mock_llm import MockLLMScript
from tests.integration.common_utils.test_models import DATestUser
from tests.integration.mock_services.mock_llm_server.models import (
    RecordedRequest,
    Reply,
    RequestConditions,
    ToolCall,
)

_UNKNOWN_TOOL_NAME = "tool_that_does_not_exist"
_UNAVAILABLE_TOOL_RESULT = f"Tool {_UNKNOWN_TOOL_NAME} is unavailable for this step."


def _setup(admin_user: DATestUser) -> UUID:
    # internal_search is only offered when a non-default connector exists.
    CCPairManager.create_from_scratch(
        source=DocumentSource.INGESTION_API,
        user_performing_action=admin_user,
    )
    return ChatSessionManager.create(user_performing_action=admin_user).id


def _assistant_tool_call_ids(request: RecordedRequest) -> list[list[str]]:
    return [
        [call.id for call in message.tool_calls]
        for message in request.messages
        if message.role == "assistant" and message.tool_calls
    ]


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
    admin_user: DATestUser, mock_llm: MockLLMScript
) -> None:
    chat_session_id = _setup(admin_user)
    mock_llm.conversation(
        "chat",
        Reply(
            tool_calls=[
                ToolCall(
                    id="call_search_alpha",
                    name="internal_search",
                    arguments={"queries": ["alpha"]},
                ),
                ToolCall(
                    id="call_search_beta",
                    name="internal_search",
                    arguments={"queries": ["beta"]},
                ),
                ToolCall(
                    id="call_unknown_tool",
                    name=_UNKNOWN_TOOL_NAME,
                    arguments={"x": 1},
                ),
            ],
            conditions=RequestConditions(offers=["internal_search"]),
        ),
        Reply(
            text="The answer is 42.",
            conditions=RequestConditions(has_results_for=["call_unknown_tool"]),
        ),
    )

    response = ChatSessionManager.send_message(
        chat_session_id=chat_session_id,
        message="what is the answer?",
        user_performing_action=admin_user,
    )

    assert response.error is None, f"Unexpected stream error: {response.error}"
    assert [tc.tool_call_id for tc in response.tool_call_debug] == [
        "call_search_alpha",
        "call_search_beta",
        "call_unknown_tool",
    ]
    assert response.full_message == "The answer is 42."

    packet_types = [packet["obj"]["type"] for packet in response.packets]
    assert packet_types.count(StreamingType.SEARCH_TOOL_START.value) == 2

    # Batched retrieval preserves each model call and its matching result.
    _, answer_request = mock_llm.requests_in("chat")
    assert _assistant_tool_call_ids(answer_request) == [
        ["call_search_alpha", "call_search_beta", "call_unknown_tool"]
    ]
    assert answer_request.tool_result_ids() == [
        "call_search_alpha",
        "call_search_beta",
        "call_unknown_tool",
    ]
    assert answer_request.tool_result("call_unknown_tool") == _UNAVAILABLE_TOOL_RESULT
    assert answer_request.tool_result("call_search_beta") is not None

    replayed = _replayed_packet_types(chat_session_id, admin_user)
    assert replayed.count(StreamingType.SEARCH_TOOL_START.value) == 2
    assert replayed.count(StreamingType.CUSTOM_TOOL_START.value) == 1


def test_all_unknown_calls_get_failure_responses_and_retry(
    admin_user: DATestUser, mock_llm: MockLLMScript
) -> None:
    chat_session_id = _setup(admin_user)
    mock_llm.conversation(
        "chat",
        Reply(
            tool_calls=[
                ToolCall(
                    id="call_only_unknown",
                    name=_UNKNOWN_TOOL_NAME,
                    arguments={"x": 1},
                )
            ],
            conditions=RequestConditions(has_tools=True),
        ),
        Reply(
            text="Recovered.",
            conditions=RequestConditions(has_results_for=["call_only_unknown"]),
        ),
    )

    response = ChatSessionManager.send_message(
        chat_session_id=chat_session_id,
        message="what is the answer?",
        user_performing_action=admin_user,
    )

    assert response.error is None, f"Unexpected stream error: {response.error}"
    assert [tc.tool_call_id for tc in response.tool_call_debug] == ["call_only_unknown"]
    assert response.full_message == "Recovered."

    _, retry_request = mock_llm.requests_in("chat")
    assert _assistant_tool_call_ids(retry_request) == [["call_only_unknown"]]
    assert retry_request.tool_result_ids() == ["call_only_unknown"]
    assert retry_request.tool_result("call_only_unknown") == _UNAVAILABLE_TOOL_RESULT

    replayed = _replayed_packet_types(chat_session_id, admin_user)
    assert StreamingType.SEARCH_TOOL_START.value not in replayed
    assert replayed.count(StreamingType.CUSTOM_TOOL_START.value) == 1
