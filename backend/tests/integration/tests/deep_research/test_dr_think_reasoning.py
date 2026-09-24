import json
from typing import Any

from onyx.configs.constants import MessageType
from onyx.deep_research.dr_mock_tools import (
    GENERATE_PLAN_TOOL_NAME,
    GENERATE_REPORT_TOOL_NAME,
    RESEARCH_AGENT_TASK_KEY,
    RESEARCH_AGENT_TOOL_NAME,
    THINK_TOOL_NAME,
    THINK_TOOL_RESPONSE_MESSAGE,
)
from onyx.server.query_and_chat.streaming_models import StreamingType
from tests.integration.common_utils.managers.chat import ChatSessionManager
from tests.integration.common_utils.test_models import DATestUser
from tests.integration.mock_services.mock_llm_server.handle import ScriptHandle
from tests.integration.mock_services.mock_llm_server.models import (
    Matcher,
    RecordedRequest,
    Step,
    ToolCall,
)

_RESEARCH_CALL_ID = "call_research_agent"
_CHILD_THINK_CALL_ID = "call_child_think"
_ORCHESTRATOR_THINK_CALL_ID = "call_orchestrator_think"

_RESEARCH_TASK = "Investigate the history of the alpha protocol."
# Each ends in characters the think tool processor used to drop.
_CHILD_REASONING = 'Search for "alpha" first,\nthen report. Done'
_ORCHESTRATOR_REASONING = 'The research is complete: write the report \\ "end"'
_RESEARCH_PLAN = "1. Research the alpha protocol."
_INTERMEDIATE_REPORT = "The alpha protocol started early."
_FINAL_REPORT = "Alpha came before beta."


def _streamed_reasoning(packets: list[dict[str, Any]], in_research_agent: bool) -> str:
    return "".join(
        packet["obj"]["reasoning"]
        for packet in packets
        if packet["obj"]["type"] == StreamingType.REASONING_DELTA.value
        and (packet["placement"].get("sub_turn_index") is not None) == in_research_agent
    )


def _replayed_think_reasoning(request: RecordedRequest, tool_call_id: str) -> str:
    for message in request.messages:
        for call in message.tool_calls:
            if call.id == tool_call_id and isinstance(call.arguments, str):
                return json.loads(call.arguments)["reasoning"]
    raise AssertionError(f"tool call {tool_call_id} was not replayed")


def _script_deep_research(mock_llm: ScriptHandle) -> None:
    # SKIP_DEEP_RESEARCH_CLARIFICATION can turn this step off.
    mock_llm.lane(
        "clarification",
        Step(
            tool_calls=[
                ToolCall(id="call_generate_plan", name=GENERATE_PLAN_TOOL_NAME)
            ],
            required=False,
        ),
        match=Matcher(offered_tools=[GENERATE_PLAN_TOOL_NAME]),
    )
    mock_llm.lane(
        "orchestrator",
        Step(
            tool_calls=[
                ToolCall(
                    id=_RESEARCH_CALL_ID,
                    name=RESEARCH_AGENT_TOOL_NAME,
                    arguments={RESEARCH_AGENT_TASK_KEY: _RESEARCH_TASK},
                )
            ],
        ),
        Step(
            tool_calls=[
                ToolCall(
                    id=_ORCHESTRATOR_THINK_CALL_ID,
                    name=THINK_TOOL_NAME,
                    arguments={"reasoning": _ORCHESTRATOR_REASONING},
                )
            ],
            match=Matcher(tool_results_for=[_RESEARCH_CALL_ID]),
        ),
        Step(
            tool_calls=[
                ToolCall(id="call_final_report", name=GENERATE_REPORT_TOOL_NAME)
            ],
            match=Matcher(tool_results_for=[_ORCHESTRATOR_THINK_CALL_ID]),
        ),
        match=Matcher(
            offered_tools=[RESEARCH_AGENT_TOOL_NAME, THINK_TOOL_NAME],
            tool_choice="required",
        ),
    )
    mock_llm.lane(
        "research_agent",
        Step(
            tool_calls=[
                ToolCall(
                    id=_CHILD_THINK_CALL_ID,
                    name=THINK_TOOL_NAME,
                    arguments={"reasoning": _CHILD_REASONING},
                )
            ],
        ),
        Step(
            tool_calls=[
                ToolCall(id="call_intermediate_report", name=GENERATE_REPORT_TOOL_NAME)
            ],
            match=Matcher(tool_results_for=[_CHILD_THINK_CALL_ID]),
        ),
        match=Matcher(
            offered_tools=[GENERATE_REPORT_TOOL_NAME, THINK_TOOL_NAME],
            not_offered_tools=[RESEARCH_AGENT_TOOL_NAME],
            tool_choice="required",
        ),
    )
    # The plan, the intermediate report and the final report offer no tools.
    mock_llm.lane(
        "reports",
        Step(text=_RESEARCH_PLAN),
        Step(
            text=_INTERMEDIATE_REPORT,
            match=Matcher(tool_results_for=[_CHILD_THINK_CALL_ID]),
        ),
        Step(
            text=_FINAL_REPORT,
            match=Matcher(
                tool_results_for=[_RESEARCH_CALL_ID, _ORCHESTRATOR_THINK_CALL_ID]
            ),
        ),
        match=Matcher(tools_offered=False),
    )


def test_think_tool_reasoning_is_streamed_and_saved_in_full(
    admin_user: DATestUser, mock_llm: ScriptHandle
) -> None:
    _script_deep_research(mock_llm)
    chat_session = ChatSessionManager.create(user_performing_action=admin_user)

    response = ChatSessionManager.send_message(
        chat_session_id=chat_session.id,
        message="How did the alpha protocol start?",
        user_performing_action=admin_user,
        deep_research=True,
    )

    assert response.error is None, f"Unexpected stream error: {response.error}"
    assert response.full_message == _FINAL_REPORT
    assert _streamed_reasoning(response.packets, in_research_agent=True) == (
        _CHILD_REASONING
    )
    assert _streamed_reasoning(response.packets, in_research_agent=False) == (
        _ORCHESTRATOR_REASONING
    )

    history = ChatSessionManager.get_chat_history(
        chat_session=chat_session,
        user_performing_action=admin_user,
    )
    assistant_messages = [
        message for message in history if message.message_type == MessageType.ASSISTANT
    ]
    assert len(assistant_messages) == 1
    assert assistant_messages[0].message == _FINAL_REPORT
    assert assistant_messages[0].reasoning_tokens == _ORCHESTRATOR_REASONING

    # Each think call goes back to the model with its full reasoning and the
    # acknowledgement as its tool result.
    _, child_report_call = mock_llm.lane_requests("research_agent")
    assert child_report_call.tool_result(_CHILD_THINK_CALL_ID) == (
        THINK_TOOL_RESPONSE_MESSAGE
    )
    assert _replayed_think_reasoning(child_report_call, _CHILD_THINK_CALL_ID) == (
        _CHILD_REASONING
    )

    _, orchestrator_think_call, orchestrator_report_call = mock_llm.lane_requests(
        "orchestrator"
    )
    assert orchestrator_think_call.tool_result(_RESEARCH_CALL_ID) == (
        _INTERMEDIATE_REPORT
    )
    assert orchestrator_report_call.tool_result(_ORCHESTRATOR_THINK_CALL_ID) == (
        THINK_TOOL_RESPONSE_MESSAGE
    )
    assert (
        _replayed_think_reasoning(orchestrator_report_call, _ORCHESTRATOR_THINK_CALL_ID)
        == _ORCHESTRATOR_REASONING
    )
