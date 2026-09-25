from sqlalchemy import select

from onyx.configs.constants import DocumentSource
from onyx.db.engine.sql_engine import get_session_with_current_tenant
from onyx.db.models import ToolCall as ToolCallModel
from onyx.deep_research.dr_mock_tools import (
    GENERATE_PLAN_TOOL_NAME,
    GENERATE_REPORT_TOOL_NAME,
    RESEARCH_AGENT_TASK_KEY,
    RESEARCH_AGENT_TOOL_NAME,
)
from onyx.tools.tool_implementations.search.search_tool import SearchTool
from tests.integration.common_utils.managers.cc_pair import CCPairManager
from tests.integration.common_utils.managers.chat import ChatSessionManager
from tests.integration.common_utils.test_models import DATestUser
from tests.integration.mock_services.mock_llm_server.handle import ScriptHandle
from tests.integration.mock_services.mock_llm_server.models import (
    Matcher,
    Step,
    ToolCall,
)

_STRAY_CALL_ID = "call_dr_stray_search"
_RESEARCH_CALL_ID = "call_dr_research_agent"
_CHILD_SEARCH_CALL_ID = "call_dr_child_search"
_CHILD_SEARCH_ARGS = {"queries": ["zebra-linkage onboarding"]}
_RESEARCH_TASK = "Find the zebra-linkage onboarding policy"
_FINAL_REPORT = "The zebra-linkage policy is documented."


def _script_deep_research(mock_llm: ScriptHandle) -> None:
    mock_llm.lane(
        "clarification",
        # Config can turn the clarification step off.
        Step(
            tool_calls=[ToolCall(id="call_dr_plan", name=GENERATE_PLAN_TOOL_NAME)],
            required=False,
        ),
        match=Matcher(offered_tools=[GENERATE_PLAN_TOOL_NAME]),
    )
    mock_llm.lane(
        "plan",
        Step(text="1. Look up the onboarding policy"),
        match=Matcher(tools_offered=False),
    )
    mock_llm.lane(
        "orchestrator",
        # The non-research call comes first so the research call is not at index 0.
        Step(
            tool_calls=[
                ToolCall(
                    id=_STRAY_CALL_ID,
                    name=SearchTool.NAME,
                    arguments={"queries": ["stray"]},
                ),
                ToolCall(
                    id=_RESEARCH_CALL_ID,
                    name=RESEARCH_AGENT_TOOL_NAME,
                    arguments={RESEARCH_AGENT_TASK_KEY: _RESEARCH_TASK},
                ),
            ]
        ),
        Step(
            tool_calls=[
                ToolCall(id="call_dr_final_report", name=GENERATE_REPORT_TOOL_NAME)
            ],
            match=Matcher(tool_results_for=[_RESEARCH_CALL_ID]),
        ),
        match=Matcher(offered_tools=[RESEARCH_AGENT_TOOL_NAME]),
    )
    mock_llm.lane(
        "research_agent",
        Step(
            tool_calls=[
                ToolCall(
                    id=_CHILD_SEARCH_CALL_ID,
                    name=SearchTool.NAME,
                    arguments=_CHILD_SEARCH_ARGS,
                )
            ]
        ),
        Step(
            tool_calls=[
                ToolCall(id="call_dr_child_report", name=GENERATE_REPORT_TOOL_NAME)
            ],
            match=Matcher(tool_results_for=[_CHILD_SEARCH_CALL_ID]),
        ),
        match=Matcher(
            offered_tools=[SearchTool.NAME, GENERATE_REPORT_TOOL_NAME],
            not_offered_tools=[RESEARCH_AGENT_TOOL_NAME],
        ),
    )
    mock_llm.lane(
        "intermediate_report",
        Step(text="Intermediate zebra-linkage findings."),
        match=Matcher(tools_offered=False, tool_results_for=[_CHILD_SEARCH_CALL_ID]),
    )
    mock_llm.lane(
        "final_report",
        Step(text=_FINAL_REPORT),
        match=Matcher(tools_offered=False, tool_results_for=[_RESEARCH_CALL_ID]),
    )


def test_research_child_tool_calls_attach_to_research_call(
    admin_user: DATestUser, mock_llm: ScriptHandle
) -> None:
    # SearchTool is only exposed when at least one non-default connector exists.
    CCPairManager.create_from_scratch(
        source=DocumentSource.INGESTION_API,
        user_performing_action=admin_user,
    )
    _script_deep_research(mock_llm)
    chat_session = ChatSessionManager.create(user_performing_action=admin_user)

    response = ChatSessionManager.send_message(
        chat_session_id=chat_session.id,
        message="What is the zebra-linkage onboarding policy?",
        user_performing_action=admin_user,
        deep_research=True,
    )

    assert response.error is None, f"Unexpected stream error: {response.error}"
    assert response.full_message == _FINAL_REPORT

    # The orchestrator replays only the research call, and the stray call never runs.
    _, orchestrator_followup = mock_llm.lane_requests("orchestrator")
    replayed_calls = [
        call.id
        for message in orchestrator_followup.messages
        if message.role == "assistant"
        for call in message.tool_calls
    ]
    assert replayed_calls == [_RESEARCH_CALL_ID]
    assert all(r.tool_result(_STRAY_CALL_ID) is None for r in mock_llm.requests)

    _, child_followup = mock_llm.lane_requests("research_agent")
    assert child_followup.tool_result(_CHILD_SEARCH_CALL_ID) is not None

    with get_session_with_current_tenant() as db_session:
        saved_calls = {
            tool_call.tool_call_id: tool_call
            for tool_call in db_session.scalars(
                select(ToolCallModel).where(
                    ToolCallModel.chat_session_id == chat_session.id
                )
            )
        }

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
        assert child_search.tool_call_arguments == _CHILD_SEARCH_ARGS
