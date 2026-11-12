import json

import pytest

from onyx.configs import app_configs
from onyx.configs.constants import DocumentSource
from onyx.tools.constants import SEARCH_TOOL_ID
from tests.integration.common_utils.managers.cc_pair import CCPairManager
from tests.integration.common_utils.managers.chat import ChatSessionManager
from tests.integration.common_utils.managers.llm_provider import LLMProviderManager
from tests.integration.common_utils.managers.mock_llm import (
    MockLLMScript,
    requires_code_mode,
    tool_call_reply,
)
from tests.integration.common_utils.managers.persona import PersonaManager
from tests.integration.common_utils.managers.project import ProjectManager
from tests.integration.common_utils.managers.tool import ToolManager
from tests.integration.common_utils.test_models import DATestUser, ToolName
from tests.integration.mock_services.mock_llm_server.models import (
    Reply,
    RequestConditions,
    ToolCall,
)

_DUMMY_OPENAI_API_KEY = "sk-mock-tool-policy-tests"
_SEARCH_CALL_ID = "call_search_1"
_ANSWER = "Here is what the search found."


def _assert_integration_mode_enabled() -> None:
    assert app_configs.INTEGRATION_TESTS_MODE is True, (
        "Integration tests require INTEGRATION_TESTS_MODE=true."
    )


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


def _script_preferred_search(mock_llm: MockLLMScript, query: str) -> None:
    """The preferred search remains optional while definitions stay stable."""
    mock_llm.conversation(
        "chat",
        tool_call_reply(
            ToolCall(
                id=_SEARCH_CALL_ID,
                name="internal_search",
                arguments={"queries": [query]},
            ),
            tool_choice="auto",
        ),
        Reply(
            text=_ANSWER,
            conditions=RequestConditions(has_results_for=[_SEARCH_CALL_ID]),
        ),
    )


def test_preferred_tool_executes_when_available(
    admin_user: DATestUser, mock_llm: MockLLMScript
) -> None:
    _assert_integration_mode_enabled()
    _seed_connector_for_search_tool(admin_user)
    _script_preferred_search(mock_llm, "alpha")

    search_tool_id = _get_internal_search_tool_id(admin_user)
    persona = PersonaManager.create(
        tool_ids=[search_tool_id], user_performing_action=admin_user
    )
    chat_session = ChatSessionManager.create(
        persona_id=persona.id, user_performing_action=admin_user
    )

    response = ChatSessionManager.send_message(
        chat_session_id=chat_session.id,
        message="prefer the search tool",
        user_performing_action=admin_user,
        preferred_tool_id=search_tool_id,
    )

    assert response.error is None, f"Unexpected stream error: {response.error}"
    assert any(
        tool.tool_name == ToolName.INTERNAL_SEARCH for tool in response.used_tools
    )
    # Code mode also reports the `execute_code` call that ran the search.
    [search] = [
        entry
        for entry in response.tool_call_debug
        if entry.tool_name == "internal_search"
    ]
    assert search.tool_args == {"queries": ["alpha"]}


@pytest.mark.parametrize("allow_search", [True, False])
def test_search_preference_uses_inline_project_files(
    admin_user: DATestUser, mock_llm: MockLLMScript, allow_search: bool
) -> None:
    _assert_integration_mode_enabled()
    _seed_connector_for_search_tool(admin_user)
    search_tool_id = _get_internal_search_tool_id(admin_user)
    project = ProjectManager.create(
        name="Inline project search preference", user_performing_action=admin_user
    )
    evidence = "The project access code is HARBOR-5729."
    uploaded = ProjectManager.upload_files(
        project_id=project.id,
        files=[("access-code.txt", evidence.encode())],
        user_performing_action=admin_user,
    )
    assert len(uploaded.user_files) == 1
    assert not uploaded.rejected_files
    assert uploaded.user_files[0].token_count
    if allow_search:
        mock_llm.conversation(
            "inline-project",
            Reply(
                text="The code is HARBOR-5729.",
                conditions=RequestConditions(
                    prompt_contains=[evidence], does_not_offer=["internal_search"]
                ),
            ),
        )
    chat_session = ChatSessionManager.create(
        project_id=project.id, user_performing_action=admin_user
    )
    response = ChatSessionManager.send_message(
        chat_session_id=chat_session.id,
        message="What is the project access code?",
        user_performing_action=admin_user,
        preferred_tool_id=search_tool_id,
        allowed_tool_ids=None if allow_search else [],
    )

    if not allow_search:
        assert response.error is not None
        assert (
            response.error.error
            == f"Preferred tool {search_tool_id} not found in tools"
        )
        assert not response.used_tools
        return

    assert response.error is None, f"Unexpected stream error: {response.error}"
    assert response.full_message == "The code is HARBOR-5729."
    assert not response.used_tools
    [request] = mock_llm.requests_in("inline-project")
    # In code mode, an offered search is a function in the execute_code
    # description rather than a tool of its own.
    assert "internal_search" not in json.dumps(request.body.get("tools", []))
    assert "The user selected these operations" not in request.prompt_text


def test_preferred_tool_rejected_when_not_in_persona_tools(
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
        message="prefer a missing tool",
        user_performing_action=admin_user,
        preferred_tool_id=search_tool_id,
    )

    assert response.error is not None
    assert response.error.error == f"Preferred tool {search_tool_id} not found in tools"
    assert response.used_tools == []


def test_allowed_tool_ids_excludes_tools_outside_allowlist(
    admin_user: DATestUser, mock_llm: MockLLMScript
) -> None:
    _assert_integration_mode_enabled()
    _seed_connector_for_search_tool(admin_user)
    # Tool-call JSON in the text must not run a tool that was not offered.
    mock_llm.conversation(
        "chat",
        Reply(
            text='{"name":"internal_search","arguments":{"queries":["beta"]}}',
            conditions=RequestConditions(does_not_offer=["internal_search"]),
        ),
    )

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
    )

    assert response.error is None, f"Unexpected stream error: {response.error}"
    assert response.used_tools == []
    assert response.tool_call_debug == []
    [request] = mock_llm.requests_in("chat")
    assert "internal_search" not in json.dumps(request.body.get("tools", []))


def test_preferred_and_allowlist_conflict_returns_validation_error(
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
        message="prefer a tool blocked by allowlist",
        user_performing_action=admin_user,
        allowed_tool_ids=[],
        preferred_tool_id=search_tool_id,
    )

    assert response.error is not None
    assert response.error.error == f"Preferred tool {search_tool_id} not found in tools"
    assert response.used_tools == []


def test_preference_is_optional_and_does_not_leak_into_followup(
    admin_user: DATestUser, mock_llm: MockLLMScript
) -> None:
    _assert_integration_mode_enabled()
    _seed_connector_for_search_tool(admin_user)
    mock_llm.conversation(
        "chat",
        Reply(
            text="No search needed.", conditions=RequestConditions(tool_choice="auto")
        ),
        Reply(
            text="Follow-up answer.", conditions=RequestConditions(tool_choice="auto")
        ),
    )
    search_tool_id = _get_internal_search_tool_id(admin_user)
    persona = PersonaManager.create(
        tool_ids=[search_tool_id], user_performing_action=admin_user
    )
    chat_session = ChatSessionManager.create(
        persona_id=persona.id, user_performing_action=admin_user
    )
    first = ChatSessionManager.send_message(
        chat_session_id=chat_session.id,
        message="Hello",
        user_performing_action=admin_user,
        preferred_tool_id=search_tool_id,
    )
    second = ChatSessionManager.send_message(
        chat_session_id=chat_session.id,
        message="Hello again",
        user_performing_action=admin_user,
    )
    assert first.error is second.error is None
    assert first.used_tools == second.used_tools == []
    first_request, second_request = mock_llm.requests_in("chat")
    # Code mode names the search as a function of execute_code programs.
    assert (
        "The user selected these operations for this request: internal_search"
        in str(first_request.body["messages"])
    )
    assert "The user selected these operations" not in str(
        second_request.body["messages"]
    )
    assert first_request.body["tools"] == second_request.body["tools"]
    mock_llm.verify()


@requires_code_mode(False)
def test_parallel_tool_calls_each_get_a_debug_entry(
    admin_user: DATestUser, mock_llm: MockLLMScript
) -> None:
    _assert_integration_mode_enabled()
    _seed_connector_for_search_tool(admin_user)
    call_ids = ["call_search_alpha", "call_search_beta"]
    mock_llm.conversation(
        "chat",
        Reply(
            tool_calls=[
                ToolCall(
                    id=call_id,
                    name="internal_search",
                    arguments={"queries": [query]},
                )
                for call_id, query in zip(call_ids, ["alpha", "beta"], strict=True)
            ],
            conditions=RequestConditions(
                offers=["internal_search"],
                tool_choice="auto",
            ),
        ),
        # The merged search call keeps the first call's id.
        Reply(text=_ANSWER, conditions=RequestConditions(has_results_for=call_ids[:1])),
    )

    search_tool_id = _get_internal_search_tool_id(admin_user)
    persona = PersonaManager.create(
        tool_ids=[search_tool_id], user_performing_action=admin_user
    )
    chat_session = ChatSessionManager.create(
        persona_id=persona.id, user_performing_action=admin_user
    )

    response = ChatSessionManager.send_message(
        chat_session_id=chat_session.id,
        message="run the search tool twice",
        user_performing_action=admin_user,
        preferred_tool_id=search_tool_id,
    )

    assert response.error is None, f"Unexpected stream error: {response.error}"
    assert [entry.tool_name for entry in response.tool_call_debug] == [
        "internal_search",
        "internal_search",
    ]
    assert [entry.tool_args for entry in response.tool_call_debug] == [
        {"queries": ["alpha"]},
        {"queries": ["beta"]},
    ]
    assert [entry.tool_call_id for entry in response.tool_call_debug] == call_ids


@requires_code_mode(False)
def test_preferred_tool_call_written_as_xml_executes(
    admin_user: DATestUser, mock_llm: MockLLMScript
) -> None:
    """Explicit XML tool calls still execute when the request has a preference."""
    _assert_integration_mode_enabled()
    _seed_connector_for_search_tool(admin_user)
    mock_llm.conversation(
        "chat",
        Reply(
            text=(
                '<function_calls><invoke name="internal_search">'
                '<parameter name="queries">["delta"]</parameter>'
                "</invoke></function_calls>"
            ),
            conditions=RequestConditions(
                offers=["internal_search"],
                tool_choice="auto",
            ),
        ),
        Reply(text=_ANSWER, conditions=RequestConditions(tool_choice="auto")),
    )

    search_tool_id = _get_internal_search_tool_id(admin_user)
    persona = PersonaManager.create(
        tool_ids=[search_tool_id], user_performing_action=admin_user
    )
    chat_session = ChatSessionManager.create(
        persona_id=persona.id, user_performing_action=admin_user
    )

    response = ChatSessionManager.send_message(
        chat_session_id=chat_session.id,
        message="use the search tool",
        user_performing_action=admin_user,
        preferred_tool_id=search_tool_id,
    )

    assert response.error is None, f"Unexpected stream error: {response.error}"
    assert len(response.tool_call_debug) == 1
    assert response.tool_call_debug[0].tool_name == "internal_search"
    assert response.tool_call_debug[0].tool_args == {"queries": ["delta"]}
    _, answer_request = mock_llm.requests_in("chat")
    assert answer_request.tool_result_ids(), "expected the search result in history"
