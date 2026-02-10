import pytest
from sqlalchemy import select

from onyx.configs.app_configs import INTEGRATION_TESTS_MODE
from onyx.db.engine.sql_engine import get_session_with_current_tenant
from onyx.db.models import Tool
from onyx.tools.constants import SEARCH_TOOL_ID
from tests.integration.common_utils.managers.chat import ChatSessionManager
from tests.integration.common_utils.managers.llm_provider import LLMProviderManager
from tests.integration.common_utils.test_models import DATestUser


pytestmark = pytest.mark.skipif(
    not INTEGRATION_TESTS_MODE,
    reason="mock_llm_response is only available when INTEGRATION_TESTS_MODE=true",
)


def _get_internal_search_tool_id() -> int:
    with get_session_with_current_tenant() as db_session:
        search_tool = db_session.execute(
            select(Tool).where(Tool.in_code_tool_id == SEARCH_TOOL_ID)
        ).scalar_one_or_none()
        assert search_tool is not None, "SearchTool must exist for this test"
        return search_tool.id


def test_mock_llm_response_single_tool_call_debug(admin_user: DATestUser) -> None:
    LLMProviderManager.create(user_performing_action=admin_user)
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
    LLMProviderManager.create(user_performing_action=admin_user)
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
