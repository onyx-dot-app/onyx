from sqlalchemy import select

from onyx.configs.constants import DocumentSource, MessageType
from onyx.db.engine.sql_engine import get_session_with_current_tenant
from onyx.db.models import ChatMessage
from onyx.db.models import ToolCall as ToolCallModel
from onyx.deep_research.tool_definitions import (
    GENERATE_PLAN_TOOL_NAME,
    GENERATE_REPORT_TOOL_NAME,
    RESEARCH_AGENT_TASK_KEY,
    RESEARCH_AGENT_TOOL_NAME,
)
from onyx.tools.tool_implementations.search.search_tool import SearchTool
from tests.integration.common_utils.managers.cc_pair import CCPairManager
from tests.integration.common_utils.managers.chat import ChatSessionManager
from tests.integration.common_utils.managers.mock_llm import MockLLMScript
from tests.integration.common_utils.test_models import DATestUser
from tests.integration.mock_services.mock_llm_server.models import (
    Reply,
    RequestConditions,
    ToolCall,
)

_STRAY_CALL_ID = "call_dr_stray_search"
_RESEARCH_CALL_ID = "call_dr_research_agent"
_CHILD_SEARCH_CALL_ID = "call_dr_child_search"
_CHILD_SEARCH_ARGS = {"queries": ["zebra-linkage onboarding"]}
_RESEARCH_TASK = "Find the zebra-linkage onboarding policy"
_FINAL_REPORT = "The zebra-linkage policy is documented."


def _script_deep_research(mock_llm: MockLLMScript) -> None:
    mock_llm.conversation(
        "clarification",
        # Config can turn clarification off.
        Reply(
            tool_calls=[ToolCall(id="call_dr_plan", name=GENERATE_PLAN_TOOL_NAME)],
            required=False,
        ),
        conditions=RequestConditions(offers=[GENERATE_PLAN_TOOL_NAME]),
    )
    mock_llm.conversation(
        "plan",
        Reply(text="1. Look up the onboarding policy"),
        conditions=RequestConditions(has_tools=False),
    )
    mock_llm.conversation(
        "orchestrator",
        # The non-research call comes first so the research call is not at index 0.
        Reply(
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
        Reply(
            tool_calls=[
                ToolCall(id="call_dr_final_report", name=GENERATE_REPORT_TOOL_NAME)
            ],
            conditions=RequestConditions(has_results_for=[_RESEARCH_CALL_ID]),
        ),
        conditions=RequestConditions(offers=[RESEARCH_AGENT_TOOL_NAME]),
    )
    mock_llm.conversation(
        "research_agent",
        Reply(
            tool_calls=[
                ToolCall(
                    id=_CHILD_SEARCH_CALL_ID,
                    name=SearchTool.NAME,
                    arguments=_CHILD_SEARCH_ARGS,
                )
            ]
        ),
        Reply(
            tool_calls=[
                ToolCall(id="call_dr_child_report", name=GENERATE_REPORT_TOOL_NAME)
            ],
            conditions=RequestConditions(has_results_for=[_CHILD_SEARCH_CALL_ID]),
        ),
        conditions=RequestConditions(
            offers=[SearchTool.NAME, GENERATE_REPORT_TOOL_NAME],
            does_not_offer=[RESEARCH_AGENT_TOOL_NAME],
        ),
    )
    mock_llm.conversation(
        "intermediate_report",
        Reply(text="Intermediate zebra-linkage findings."),
        conditions=RequestConditions(
            has_tools=False, has_results_for=[_CHILD_SEARCH_CALL_ID]
        ),
    )
    mock_llm.conversation(
        "final_report",
        Reply(text=_FINAL_REPORT),
        conditions=RequestConditions(
            has_tools=False, has_results_for=[_RESEARCH_CALL_ID]
        ),
    )


def test_research_child_tool_calls_attach_to_research_call(
    admin_user: DATestUser, mock_llm: MockLLMScript
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

    # Unavailable calls retain their identity and return a failure to the model.
    _, orchestrator_followup = mock_llm.requests_in("orchestrator")
    replayed_calls = [
        call.id
        for message in orchestrator_followup.messages
        if message.role == "assistant"
        for call in message.tool_calls
    ]
    assert replayed_calls[-2:] == [_STRAY_CALL_ID, _RESEARCH_CALL_ID]
    assert orchestrator_followup.tool_result(_STRAY_CALL_ID) == (
        f"Tool {SearchTool.NAME} is unavailable for this step."
    )

    _, child_followup = mock_llm.requests_in("research_agent")
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

        rejected_call = saved_calls[_STRAY_CALL_ID]
        assert rejected_call.result is not None and rejected_call.result.is_error

        research_call = saved_calls[_RESEARCH_CALL_ID]
        assert research_call.parent_chat_message_id == response.assistant_message_id
        assert research_call.parent_tool_call_id is None

        child_instruction = db_session.scalar(
            select(ChatMessage).where(
                ChatMessage.invoking_tool_call_id == research_call.id
            )
        )
        assert child_instruction is not None
        child_response = db_session.scalar(
            select(ChatMessage).where(
                ChatMessage.parent_message_id == child_instruction.id,
                ChatMessage.message_type == MessageType.ASSISTANT,
            )
        )
        assert child_response is not None
        assert child_response.chat_session_id != chat_session.id
        child_search = db_session.scalar(
            select(ToolCallModel).where(
                ToolCallModel.parent_chat_message_id == child_response.id,
                ToolCallModel.tool_call_id == _CHILD_SEARCH_CALL_ID,
            )
        )
        assert child_search is not None
        assert child_search.chat_session_id == child_response.chat_session_id
        assert child_search.parent_tool_call_id == research_call.id
        assert child_search.tool_call_arguments == _CHILD_SEARCH_ARGS
