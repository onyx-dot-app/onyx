import json

import pytest
import requests
from sqlalchemy import select

from onyx.configs.app_configs import INTEGRATION_TESTS_MODE
from onyx.db.engine.sql_engine import get_session_with_current_tenant
from onyx.db.models import Tool
from onyx.server.query_and_chat.models import CreateChatMessageRequest
from onyx.server.query_and_chat.streaming_models import StreamingType
from onyx.tools.constants import SEARCH_TOOL_ID
from tests.integration.common_utils.constants import API_SERVER_URL
from tests.integration.common_utils.managers.chat import ChatSessionManager
from tests.integration.common_utils.managers.llm_provider import LLMProviderManager
from tests.integration.common_utils.test_models import DATestUser


pytestmark = pytest.mark.skipif(
    not INTEGRATION_TESTS_MODE,
    reason="mock_llm_response is only available when INTEGRATION_TESTS_MODE=true",
)

_DUMMY_OPENAI_API_KEY = "sk-mock-llm-workflow-tests"


def _get_internal_search_tool_id() -> int:
    with get_session_with_current_tenant() as db_session:
        search_tool = db_session.execute(
            select(Tool).where(Tool.in_code_tool_id == SEARCH_TOOL_ID)
        ).scalar_one_or_none()
        assert search_tool is not None, "SearchTool must exist for this test"
        return search_tool.id


def test_mock_llm_response_single_tool_call_debug(admin_user: DATestUser) -> None:
    LLMProviderManager.create(
        user_performing_action=admin_user,
        api_key=_DUMMY_OPENAI_API_KEY,
    )
    chat_session = ChatSessionManager.create(user_performing_action=admin_user)
    search_tool_id = _get_internal_search_tool_id()

    response = ChatSessionManager.send_message(
        chat_session_id=chat_session.id,
        message="run the search tool",
        user_performing_action=admin_user,
        forced_tool_ids=[search_tool_id],
        mock_llm_response='{"name":"internal_search","arguments":{"queries":["alpha"]}}',
    )

    assert response.error is None
    assert len(response.tool_call_debug) == 1
    assert response.tool_call_debug[0].tool_name == "internal_search"
    assert response.tool_call_debug[0].tool_args == {"queries": ["alpha"]}


def test_mock_llm_response_parallel_tool_call_debug(admin_user: DATestUser) -> None:
    LLMProviderManager.create(
        user_performing_action=admin_user,
        api_key=_DUMMY_OPENAI_API_KEY,
    )
    chat_session = ChatSessionManager.create(user_performing_action=admin_user)
    search_tool_id = _get_internal_search_tool_id()

    mock_response = "\n".join(
        [
            '{"name":"internal_search","arguments":{"queries":["alpha"]}}',
            '{"name":"internal_search","arguments":{"queries":["beta"]}}',
        ]
    )
    response = ChatSessionManager.send_message(
        chat_session_id=chat_session.id,
        message="run the search tool twice",
        user_performing_action=admin_user,
        forced_tool_ids=[search_tool_id],
        mock_llm_response=mock_response,
    )

    assert response.error is None
    assert len(response.tool_call_debug) == 2
    assert [entry.tool_name for entry in response.tool_call_debug] == [
        "internal_search",
        "internal_search",
    ]
    assert [entry.tool_args for entry in response.tool_call_debug] == [
        {"queries": ["alpha"]},
        {"queries": ["beta"]},
    ]


def test_tool_call_debug_packet_contract(admin_user: DATestUser) -> None:
    LLMProviderManager.create(
        user_performing_action=admin_user,
        api_key=_DUMMY_OPENAI_API_KEY,
    )
    chat_session = ChatSessionManager.create(user_performing_action=admin_user)
    search_tool_id = _get_internal_search_tool_id()

    req = CreateChatMessageRequest(
        chat_session_id=chat_session.id,
        parent_message_id=None,
        message="verify tool call packet contract",
        file_descriptors=[],
        search_doc_ids=[],
        retrieval_options=None,
        forced_tool_ids=[search_tool_id],
        mock_llm_response='{"name":"internal_search","arguments":{"queries":["alpha"]}}',
    )

    tool_call_debug_packets: list[dict] = []
    max_packets = 500
    with requests.post(
        f"{API_SERVER_URL}/chat/send-message",
        json=req.model_dump(),
        headers=admin_user.headers,
        stream=True,
        cookies=admin_user.cookies,
        timeout=(5, 30),
    ) as response:
        assert response.status_code == 200

        for packet_count, line in enumerate(response.iter_lines(), start=1):
            if packet_count > max_packets:
                pytest.fail(
                    "Exceeded packet limit while waiting for tool_call_debug packet"
                )

            if not line:
                continue
            packet = json.loads(line.decode("utf-8"))

            if "error" in packet:
                pytest.fail(f"Received stream error packet: {packet['error']}")

            packet_obj = packet.get("obj") or {}
            packet_type = packet_obj.get("type")
            if packet_type == StreamingType.TOOL_CALL_DEBUG.value:
                tool_call_debug_packets.append(packet)
                break
            if packet_type == StreamingType.STOP.value:
                break

    assert len(tool_call_debug_packets) == 1

    packet = tool_call_debug_packets[0]
    packet_obj = packet["obj"]
    placement = packet.get("placement") or {}

    assert packet_obj["type"] == StreamingType.TOOL_CALL_DEBUG.value
    assert packet_obj["tool_name"] == "internal_search"
    assert packet_obj["tool_args"] == {"queries": ["alpha"]}
    assert isinstance(packet_obj["tool_call_id"], str) and packet_obj["tool_call_id"]

    assert isinstance(placement.get("turn_index"), int)
    assert isinstance(placement.get("tab_index"), int)
