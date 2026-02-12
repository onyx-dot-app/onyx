from onyx.configs import app_configs
from onyx.configs.constants import DocumentSource
from onyx.server.query_and_chat.models import OptionalSearchSetting
from onyx.server.query_and_chat.models import RetrievalDetails
from onyx.tools.constants import SEARCH_TOOL_ID
from tests.integration.common_utils.managers.cc_pair import CCPairManager
from tests.integration.common_utils.managers.chat import ChatSessionManager
from tests.integration.common_utils.managers.llm_provider import LLMProviderManager
from tests.integration.common_utils.managers.persona import PersonaManager
from tests.integration.common_utils.managers.tool import ToolManager
from tests.integration.common_utils.test_models import DATestUser
from tests.integration.common_utils.test_models import ToolName


_DUMMY_OPENAI_API_KEY = "sk-mock-tool-policy-tests"


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


def _get_internal_search_tool_id(admin_user: DATestUser) -> int:
    tools = ToolManager.list_tools(user_performing_action=admin_user)
    for tool in tools:
        if tool.in_code_tool_id == SEARCH_TOOL_ID:
            return tool.id
    raise AssertionError("SearchTool must exist for this test")


def _ensure_llm_provider(admin_user: DATestUser) -> None:
    LLMProviderManager.create(
        user_performing_action=admin_user,
        api_key=_DUMMY_OPENAI_API_KEY,
    )


def test_forced_tool_executes_when_available(admin_user: DATestUser) -> None:
    _assert_integration_mode_enabled()
    _seed_connector_for_search_tool(admin_user)
    _ensure_llm_provider(admin_user)

    search_tool_id = _get_internal_search_tool_id(admin_user)
    persona = PersonaManager.create(
        tool_ids=[search_tool_id], user_performing_action=admin_user
    )
    chat_session = ChatSessionManager.create(
        persona_id=persona.id, user_performing_action=admin_user
    )

    response = ChatSessionManager.send_message(
        chat_session_id=chat_session.id,
        message="force the search tool",
        user_performing_action=admin_user,
        forced_tool_ids=[search_tool_id],
        mock_llm_response='{"name":"internal_search","arguments":{"queries":["alpha"]}}',
    )

    assert response.error is None, f"Unexpected stream error: {response.error}"
    assert any(
        tool.tool_name == ToolName.INTERNAL_SEARCH for tool in response.used_tools
    )
    assert len(response.tool_call_debug) == 1
    assert response.tool_call_debug[0].tool_name == "internal_search"
    assert response.tool_call_debug[0].tool_args == {"queries": ["alpha"]}


def test_forced_tool_rejected_when_not_in_persona_tools(
    admin_user: DATestUser,
) -> None:
    _assert_integration_mode_enabled()
    _seed_connector_for_search_tool(admin_user)
    _ensure_llm_provider(admin_user)

    search_tool_id = _get_internal_search_tool_id(admin_user)
    persona = PersonaManager.create(tool_ids=[], user_performing_action=admin_user)
    chat_session = ChatSessionManager.create(
        persona_id=persona.id, user_performing_action=admin_user
    )

    response = ChatSessionManager.send_message(
        chat_session_id=chat_session.id,
        message="try forcing a missing tool",
        user_performing_action=admin_user,
        forced_tool_ids=[search_tool_id],
    )

    assert response.error is not None
    assert response.error.error == f"Forced tool {search_tool_id} not found in tools"
    assert response.used_tools == []


def test_allowed_tool_ids_excludes_tools_outside_allowlist(
    admin_user: DATestUser,
) -> None:
    _assert_integration_mode_enabled()
    _seed_connector_for_search_tool(admin_user)
    _ensure_llm_provider(admin_user)

    search_tool_id = _get_internal_search_tool_id(admin_user)
    persona = PersonaManager.create(
        tool_ids=[search_tool_id], user_performing_action=admin_user
    )
    chat_session = ChatSessionManager.create(
        persona_id=persona.id, user_performing_action=admin_user
    )

    response = ChatSessionManager.send_message(
        chat_session_id=chat_session.id,
        message="attempt tool use with empty allowlist",
        user_performing_action=admin_user,
        allowed_tool_ids=[],
        mock_llm_response='{"name":"internal_search","arguments":{"queries":["beta"]}}',
    )

    assert response.error is None, f"Unexpected stream error: {response.error}"
    assert response.used_tools == []
    assert response.tool_call_debug == []


def test_forced_and_allowlist_conflict_returns_validation_error(
    admin_user: DATestUser,
) -> None:
    _assert_integration_mode_enabled()
    _seed_connector_for_search_tool(admin_user)
    _ensure_llm_provider(admin_user)

    search_tool_id = _get_internal_search_tool_id(admin_user)
    persona = PersonaManager.create(
        tool_ids=[search_tool_id], user_performing_action=admin_user
    )
    chat_session = ChatSessionManager.create(
        persona_id=persona.id, user_performing_action=admin_user
    )

    response = ChatSessionManager.send_message(
        chat_session_id=chat_session.id,
        message="force a tool blocked by allowlist",
        user_performing_action=admin_user,
        allowed_tool_ids=[],
        forced_tool_ids=[search_tool_id],
    )

    assert response.error is not None
    assert response.error.error == f"Forced tool {search_tool_id} not found in tools"
    assert response.used_tools == []


def test_run_search_always_maps_to_forced_search_tool(admin_user: DATestUser) -> None:
    _assert_integration_mode_enabled()
    _seed_connector_for_search_tool(admin_user)
    _ensure_llm_provider(admin_user)

    search_tool_id = _get_internal_search_tool_id(admin_user)
    persona = PersonaManager.create(
        tool_ids=[search_tool_id], user_performing_action=admin_user
    )
    chat_session = ChatSessionManager.create(
        persona_id=persona.id, user_performing_action=admin_user
    )

    response = ChatSessionManager.send_message(
        chat_session_id=chat_session.id,
        message="always run search",
        user_performing_action=admin_user,
        retrieval_options=RetrievalDetails(run_search=OptionalSearchSetting.ALWAYS),
        mock_llm_response='{"name":"internal_search","arguments":{"queries":["gamma"]}}',
    )

    assert response.error is None, f"Unexpected stream error: {response.error}"
    assert any(
        tool.tool_name == ToolName.INTERNAL_SEARCH for tool in response.used_tools
    )
    assert len(response.tool_call_debug) == 1
    assert response.tool_call_debug[0].tool_name == "internal_search"
    assert response.tool_call_debug[0].tool_args == {"queries": ["gamma"]}
