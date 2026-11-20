from typing import Any

from onyx.configs.constants import MessageType
from onyx.deep_research.tool_definitions import (
    GENERATE_PLAN_TOOL_NAME,
    GENERATE_REPORT_TOOL_NAME,
    RESEARCH_AGENT_TASK_KEY,
    RESEARCH_AGENT_TOOL_NAME,
)
from onyx.server.query_and_chat.models import ChatSessionDetailResponse
from onyx.server.query_and_chat.streaming_models import ReasoningDelta, StreamingType
from tests.integration.common_utils.constants import API_SERVER_URL
from tests.integration.common_utils.http_client import client
from tests.integration.common_utils.managers.chat import ChatSessionManager
from tests.integration.common_utils.managers.mock_llm import MockLLMScript
from tests.integration.common_utils.test_models import DATestUser
from tests.integration.mock_services.mock_llm_server.models import (
    Reply,
    RequestConditions,
    ToolCall,
)

_RESEARCH_CALL_ID = "call_research_agent"

_RESEARCH_TASK = "Investigate the history of the alpha protocol."
# Escapes and final characters must survive streaming and replay.
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


def _script_deep_research(mock_llm: MockLLMScript) -> None:
    # SKIP_DEEP_RESEARCH_CLARIFICATION can skip this reply.
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
            tool_calls=[
                ToolCall(
                    id=_RESEARCH_CALL_ID,
                    name=RESEARCH_AGENT_TOOL_NAME,
                    arguments={RESEARCH_AGENT_TASK_KEY: _RESEARCH_TASK},
                )
            ],
        ),
        Reply(
            reasoning=_ORCHESTRATOR_REASONING,
            tool_calls=[
                ToolCall(id="call_final_report", name=GENERATE_REPORT_TOOL_NAME)
            ],
            conditions=RequestConditions(has_results_for=[_RESEARCH_CALL_ID]),
        ),
        conditions=RequestConditions(
            offers=[RESEARCH_AGENT_TOOL_NAME],
            tool_choice="required",
        ),
    )
    mock_llm.conversation(
        "research_agent",
        Reply(
            reasoning=_CHILD_REASONING,
            tool_calls=[
                ToolCall(id="call_intermediate_report", name=GENERATE_REPORT_TOOL_NAME)
            ],
        ),
        conditions=RequestConditions(
            offers=[GENERATE_REPORT_TOOL_NAME],
            does_not_offer=[RESEARCH_AGENT_TOOL_NAME],
            tool_choice="required",
        ),
    )
    # All report steps disable calls; the child report retains its tool definitions.
    mock_llm.conversation(
        "reports",
        Reply(text=_RESEARCH_PLAN, conditions=RequestConditions(has_tools=False)),
        Reply(
            text=_INTERMEDIATE_REPORT,
            conditions=RequestConditions(
                offers=[GENERATE_REPORT_TOOL_NAME],
                tool_choice="none",
                has_results_for=["call_intermediate_report"],
            ),
        ),
        Reply(
            text=_FINAL_REPORT,
            conditions=RequestConditions(
                has_tools=False,
                has_results_for=[_RESEARCH_CALL_ID],
            ),
        ),
    )


def test_model_reasoning_is_streamed_and_saved_in_full(
    admin_user: DATestUser, mock_llm: MockLLMScript
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
    saved_response = client.get(
        f"{API_SERVER_URL}/chat/get-chat-session/{chat_session.id}",
        headers=admin_user.headers,
    )
    saved_response.raise_for_status()
    saved = ChatSessionDetailResponse.model_validate(saved_response.json())
    assert len(saved.packets) == 1
    for is_child, expected in (
        (True, _CHILD_REASONING),
        (False, _ORCHESTRATOR_REASONING),
    ):
        assert (
            "".join(
                packet.obj.reasoning
                for packet in saved.packets[0]
                if isinstance(packet.obj, ReasoningDelta)
                and (packet.placement.sub_turn_index is not None) == is_child
            )
            == expected
        )
