from typing import Any

from sqlalchemy import select

from onyx.configs.constants import DocumentSource
from onyx.db.engine.sql_engine import get_session_with_current_tenant
from onyx.db.models import ToolCall as ToolCallModel
from onyx.deep_research.tool_definitions import (
    GENERATE_PLAN_TOOL_NAME,
    GENERATE_REPORT_TOOL_NAME,
    RESEARCH_AGENT_TASK_KEY,
    RESEARCH_AGENT_TOOL_NAME,
    THINK_TOOL_NAME,
)
from onyx.server.query_and_chat.streaming_models import StreamingType
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

_RESEARCH_CALL_ID = "call_dr_research"
_THINK_CALL_ID = "call_child_think"
_SEARCH_CALL_ID = "call_child_search"
_CHILD_REPORT_CALL_ID = "call_child_report"
_PARENT_REPORT_CALL_ID = "call_dr_report"
_RESEARCH_TASK = "Investigate the zebra quartz launch timeline."
_THINK_TEXT = "I should search the internal docs for the launch timeline first."
_FINAL_REPORT = "The zebra quartz launch is scheduled for spring."

_SEARCH_PACKET_TYPES = {
    StreamingType.SEARCH_TOOL_START.value,
    StreamingType.SEARCH_TOOL_QUERIES_DELTA.value,
    StreamingType.SEARCH_TOOL_DOCUMENTS_DELTA.value,
}


def _script_deep_research(mock_llm: MockLLMScript) -> None:
    # Runs only when Deep Research clarification is enabled.
    mock_llm.conversation(
        "clarification",
        Reply(
            tool_calls=[
                ToolCall(id="call_generate_plan", name=GENERATE_PLAN_TOOL_NAME)
            ],
            required=False,
        ),
        conditions=RequestConditions(offers=[GENERATE_PLAN_TOOL_NAME]),
    )
    mock_llm.conversation(
        "orchestrator",
        Reply(
            text="1. Research the zebra quartz launch timeline.",
            conditions=RequestConditions(has_tools=False),
        ),
        Reply(
            tool_calls=[
                ToolCall(
                    id=_RESEARCH_CALL_ID,
                    name=RESEARCH_AGENT_TOOL_NAME,
                    arguments={RESEARCH_AGENT_TASK_KEY: _RESEARCH_TASK},
                )
            ],
            conditions=RequestConditions(
                offers=[RESEARCH_AGENT_TOOL_NAME, THINK_TOOL_NAME],
                tool_choice="required",
            ),
        ),
        Reply(
            tool_calls=[
                ToolCall(id=_PARENT_REPORT_CALL_ID, name=GENERATE_REPORT_TOOL_NAME)
            ],
            conditions=RequestConditions(
                offers=[RESEARCH_AGENT_TOOL_NAME],
                has_results_for=[_RESEARCH_CALL_ID],
            ),
        ),
        Reply(
            text=_FINAL_REPORT,
            conditions=RequestConditions(
                has_tools=False, has_results_for=[_RESEARCH_CALL_ID]
            ),
        ),
    )
    mock_llm.conversation(
        "research",
        Reply(
            tool_calls=[
                ToolCall(
                    id=_THINK_CALL_ID,
                    name=THINK_TOOL_NAME,
                    arguments={"reasoning": _THINK_TEXT},
                )
            ],
            conditions=RequestConditions(
                offers=[
                    SearchTool.NAME,
                    THINK_TOOL_NAME,
                    GENERATE_REPORT_TOOL_NAME,
                ],
                does_not_offer=[RESEARCH_AGENT_TOOL_NAME],
                tool_choice="required",
            ),
        ),
        Reply(
            tool_calls=[
                ToolCall(
                    id=_SEARCH_CALL_ID,
                    name=SearchTool.NAME,
                    arguments={"queries": ["zebra quartz launch"]},
                )
            ],
            conditions=RequestConditions(
                offers=[SearchTool.NAME],
                has_results_for=[_THINK_CALL_ID],
            ),
        ),
        Reply(
            tool_calls=[
                ToolCall(id=_CHILD_REPORT_CALL_ID, name=GENERATE_REPORT_TOOL_NAME)
            ],
            conditions=RequestConditions(
                offers=[SearchTool.NAME],
                has_results_for=[_SEARCH_CALL_ID],
            ),
        ),
        Reply(
            text="The launch timeline is not in the internal docs.",
            conditions=RequestConditions(
                has_tools=False, has_results_for=[_SEARCH_CALL_ID]
            ),
        ),
    )


def _placement(packet: dict[str, Any]) -> tuple[int, int, int | None]:
    placement = packet["placement"]
    return (
        placement["turn_index"],
        placement.get("tab_index", 0),
        placement.get("sub_turn_index"),
    )


def test_research_think_step_takes_one_sub_turn(
    admin_user: DATestUser, mock_llm: MockLLMScript
) -> None:
    """A research child that thinks before it searches places the search one
    sub-turn after the think reasoning, in the stream and in the saved tool call."""
    # internal_search is only offered when a non-default connector exists.
    CCPairManager.create_from_scratch(
        source=DocumentSource.INGESTION_API,
        user_performing_action=admin_user,
    )
    _script_deep_research(mock_llm)
    chat_session = ChatSessionManager.create(user_performing_action=admin_user)

    response = ChatSessionManager.send_message(
        chat_session_id=chat_session.id,
        message="When does the zebra quartz launch happen?",
        user_performing_action=admin_user,
        deep_research=True,
    )
    assert response.error is None, f"Unexpected stream error: {response.error}"
    assert response.full_message == _FINAL_REPORT
    assert [r.reply_index for r in mock_llm.requests_in("research")] == [0, 1, 2, 3]

    # The think arguments stream as the child's only reasoning section.
    child_reasoning = [
        packet
        for packet in response.packets
        if packet["obj"]["type"] == StreamingType.REASONING_DELTA.value
        and _placement(packet)[2] is not None
    ]
    assert child_reasoning, "The think step streamed no reasoning"
    think_placements = {_placement(packet) for packet in child_reasoning}
    assert len(think_placements) == 1
    [(turn_index, tab_index, think_sub_turn)] = think_placements
    assert think_sub_turn is not None
    assert "".join(p["obj"]["reasoning"] for p in child_reasoning) == _THINK_TEXT

    # The search runs on the sub-turn right after the think reasoning.
    search_placements = {
        _placement(packet)
        for packet in response.packets
        if packet["obj"]["type"] in _SEARCH_PACKET_TYPES
    }
    assert search_placements == {(turn_index, tab_index, think_sub_turn + 1)}

    # The saved child search call uses the same sub-turn and keeps the think reasoning.
    with get_session_with_current_tenant() as db_session:
        tool_calls = {
            tool_call.tool_call_id: tool_call
            for tool_call in db_session.scalars(
                select(ToolCallModel).where(
                    ToolCallModel.chat_session_id == chat_session.id
                )
            )
        }
        research_call = tool_calls[_RESEARCH_CALL_ID]
        search_call = tool_calls[_SEARCH_CALL_ID]
        assert search_call.parent_tool_call_id == research_call.id
        assert search_call.turn_number == think_sub_turn + 1
        assert search_call.reasoning_tokens == _THINK_TEXT
