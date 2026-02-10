from onyx.configs import app_configs
from onyx.configs.constants import DocumentSource
from onyx.tools.constants import SEARCH_TOOL_ID
from tests.integration.common_utils.managers.cc_pair import CCPairManager
from tests.integration.common_utils.managers.chat import ChatSessionManager
from tests.integration.common_utils.managers.llm_provider import LLMProviderManager
from tests.integration.common_utils.managers.tool import ToolManager
from tests.integration.common_utils.test_models import DATestUser


_DUMMY_OPENAI_API_KEY = "sk-mock-llm-workflow-tests"


def _get_internal_search_tool_id(admin_user: DATestUser) -> int:
    tools = ToolManager.list_tools(user_performing_action=admin_user)
    for tool in tools:
        if tool.in_code_tool_id == SEARCH_TOOL_ID:
            return tool.id
    raise AssertionError("SearchTool must exist for this test")


def _assert_integration_mode_enabled() -> None:
    assert (
        app_configs.INTEGRATION_TESTS_MODE is True
    ), "Integration tests require INTEGRATION_TESTS_MODE=true."


def _seed_connector_for_search_tool(admin_user: DATestUser) -> None:
    # SearchTool is only exposed when at least one non-default connector exists.
    CCPairManager.create_from_scratch(
        source=DocumentSource.INGESTION_API,
        user_performing_action=admin_user,
    )


def test_mock_llm_response_single_tool_call_debug(admin_user: DATestUser) -> None:
    _assert_integration_mode_enabled()
    _seed_connector_for_search_tool(admin_user)

    LLMProviderManager.create(
        user_performing_action=admin_user,
        api_key=_DUMMY_OPENAI_API_KEY,
    )
    chat_session = ChatSessionManager.create(user_performing_action=admin_user)
    search_tool_id = _get_internal_search_tool_id(admin_user)

    response = ChatSessionManager.send_message(
        chat_session_id=chat_session.id,
        message="run the search tool",
        user_performing_action=admin_user,
        forced_tool_ids=[search_tool_id],
        mock_llm_response='{"name":"internal_search","arguments":{"queries":["alpha"]}}',
    )

    assert response.error is None, f"Unexpected stream error: {response.error}"
    assert len(response.tool_call_debug) == 1
    assert response.tool_call_debug[0].tool_name == "internal_search"
    assert response.tool_call_debug[0].tool_args == {"queries": ["alpha"]}


def test_mock_llm_response_parallel_tool_call_debug(admin_user: DATestUser) -> None:
    _assert_integration_mode_enabled()
    _seed_connector_for_search_tool(admin_user)

    LLMProviderManager.create(
        user_performing_action=admin_user,
        api_key=_DUMMY_OPENAI_API_KEY,
    )
    chat_session = ChatSessionManager.create(user_performing_action=admin_user)
    search_tool_id = _get_internal_search_tool_id(admin_user)

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

    assert response.error is None, f"Unexpected stream error: {response.error}"
    assert len(response.tool_call_debug) == 2
    assert [entry.tool_name for entry in response.tool_call_debug] == [
        "internal_search",
        "internal_search",
    ]
    assert [entry.tool_args for entry in response.tool_call_debug] == [
        {"queries": ["alpha"]},
        {"queries": ["beta"]},
    ]
