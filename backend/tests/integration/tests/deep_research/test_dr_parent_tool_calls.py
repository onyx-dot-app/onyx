from sqlalchemy import select

from onyx.configs import app_configs
from onyx.configs.constants import DocumentSource
from onyx.db.engine.sql_engine import get_session_with_current_tenant
from onyx.db.models import ToolCall
from onyx.deep_research.dr_mock_tools import (
    GENERATE_PLAN_TOOL_NAME,
    GENERATE_REPORT_TOOL_NAME,
    RESEARCH_AGENT_TASK_KEY,
    RESEARCH_AGENT_TOOL_NAME,
)
from onyx.llm.mock_llm_script import MockLLMStep, MockToolCall
from tests.integration.common_utils.managers.cc_pair import CCPairManager
from tests.integration.common_utils.managers.chat import ChatSessionManager
from tests.integration.common_utils.managers.llm_provider import LLMProviderManager
from tests.integration.common_utils.test_models import DATestUser

_DUMMY_OPENAI_API_KEY = "sk-mock-llm-workflow-tests"

_STRAY_CALL_ID = "call_dr_stray_search"
_RESEARCH_CALL_ID = "call_dr_research_agent"
_CHILD_SEARCH_CALL_ID = "call_dr_child_search"
_RESEARCH_TASK = "Find the zebra-linkage onboarding policy"
_FINAL_REPORT = "The zebra-linkage policy is documented."


def _deep_research_script() -> list[MockLLMStep]:
    return [
        MockLLMStep(
            tool_calls=[MockToolCall(name=GENERATE_PLAN_TOOL_NAME)],
            match_prompt_contains="You are a clarification agent",
        ),
        MockLLMStep(
            text="1. Look up the onboarding policy",
            match_prompt_contains="You are a research planner agent",
        ),
        # The non-research call comes first so the research call is not at index 0.
        MockLLMStep(
            tool_calls=[
                MockToolCall(
                    id=_STRAY_CALL_ID,
                    name="internal_search",
                    arguments={"queries": ["stray"]},
                ),
                MockToolCall(
                    id=_RESEARCH_CALL_ID,
                    name=RESEARCH_AGENT_TOOL_NAME,
                    arguments={RESEARCH_AGENT_TASK_KEY: _RESEARCH_TASK},
                ),
            ],
            match_prompt_contains="You are an orchestrator agent for deep research",
        ),
        MockLLMStep(
            tool_calls=[
                MockToolCall(
                    id=_CHILD_SEARCH_CALL_ID,
                    name="internal_search",
                    arguments={"queries": ["zebra-linkage onboarding"]},
                )
            ],
            match_prompt_contains=_RESEARCH_TASK,
        ),
        MockLLMStep(
            tool_calls=[MockToolCall(name=GENERATE_REPORT_TOOL_NAME)],
            match_prompt_contains=_CHILD_SEARCH_CALL_ID,
        ),
        MockLLMStep(
            text="Intermediate zebra-linkage findings.",
            match_prompt_contains="You are a highly capable and precise research sub-agent",
        ),
        MockLLMStep(
            tool_calls=[MockToolCall(name=GENERATE_REPORT_TOOL_NAME)],
            match_prompt_contains=_RESEARCH_CALL_ID,
        ),
        MockLLMStep(
            text=_FINAL_REPORT,
            match_prompt_contains="You are the final answer generator",
        ),
    ]


def test_research_child_tool_calls_attach_to_research_call(
    admin_user: DATestUser,
) -> None:
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
    chat_session = ChatSessionManager.create(user_performing_action=admin_user)

    response = ChatSessionManager.send_message(
        chat_session_id=chat_session.id,
        message="What is the zebra-linkage onboarding policy?",
        user_performing_action=admin_user,
        deep_research=True,
        mock_llm_script=_deep_research_script(),
    )

    assert response.error is None, f"Unexpected stream error: {response.error}"
    assert response.full_message == _FINAL_REPORT

    with get_session_with_current_tenant() as db_session:
        saved_calls = {
            tool_call.tool_call_id: tool_call
            for tool_call in db_session.scalars(
                select(ToolCall).where(ToolCall.chat_session_id == chat_session.id)
            )
        }

        # The orchestrator runs only research_agent calls.
        assert _STRAY_CALL_ID not in saved_calls

        research_call = saved_calls[_RESEARCH_CALL_ID]
        assert research_call.parent_chat_message_id == response.assistant_message_id
        assert research_call.parent_tool_call_id is None

        assert _CHILD_SEARCH_CALL_ID in saved_calls, (
            "The research child's search was not saved under the research call."
        )
        child_search = saved_calls[_CHILD_SEARCH_CALL_ID]
        assert child_search.parent_tool_call_id == research_call.id
        assert child_search.parent_chat_message_id is None
        assert child_search.tool_call_arguments == {
            "queries": ["zebra-linkage onboarding"]
        }
