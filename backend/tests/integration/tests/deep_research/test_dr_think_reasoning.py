from typing import Any

from onyx.configs import app_configs
from onyx.configs.constants import MessageType
from onyx.deep_research.dr_mock_tools import (
    GENERATE_PLAN_TOOL_NAME,
    GENERATE_REPORT_TOOL_NAME,
    RESEARCH_AGENT_TASK_KEY,
    RESEARCH_AGENT_TOOL_NAME,
    THINK_TOOL_NAME,
)
from onyx.llm.mock_llm_script import MockLLMStep, MockToolCall
from onyx.server.query_and_chat.streaming_models import StreamingType
from tests.integration.common_utils.managers.chat import ChatSessionManager
from tests.integration.common_utils.managers.llm_provider import LLMProviderManager
from tests.integration.common_utils.test_models import DATestUser

_DUMMY_OPENAI_API_KEY = "sk-mock-llm-workflow-tests"
# Not a reasoning model, so Deep Research exposes the think tool.
_NON_REASONING_MODEL = "gpt-4o-mini"

_RESEARCH_TASK = "Investigate the history of the alpha protocol."
_CHILD_REASONING = 'Search for "alpha" first,\nthen report. Done'
_ORCHESTRATOR_REASONING = 'The research is complete: write the report \\ "end"'
_FINAL_REPORT = "Alpha came before beta."


def _streamed_reasoning(packets: list[dict[str, Any]], in_research_agent: bool) -> str:
    return "".join(
        packet["obj"]["reasoning"]
        for packet in packets
        if packet["obj"]["type"] == StreamingType.REASONING_DELTA.value
        and (packet["placement"].get("sub_turn_index") is not None) == in_research_agent
    )


def test_think_tool_reasoning_is_streamed_and_saved_in_full(
    admin_user: DATestUser,
) -> None:
    assert app_configs.INTEGRATION_TESTS_MODE is True, (
        "Integration tests require INTEGRATION_TESTS_MODE=true."
    )
    LLMProviderManager.create(
        user_performing_action=admin_user,
        api_key=_DUMMY_OPENAI_API_KEY,
        default_model_name=_NON_REASONING_MODEL,
    )
    chat_session = ChatSessionManager.create(user_performing_action=admin_user)

    response = ChatSessionManager.send_message(
        chat_session_id=chat_session.id,
        message="How did the alpha protocol start?",
        user_performing_action=admin_user,
        deep_research=True,
        mock_llm_script=[
            # The clarification step can be turned off by config.
            MockLLMStep(
                tool_calls=[MockToolCall(name=GENERATE_PLAN_TOOL_NAME)],
                match_prompt_contains="You are a clarification agent",
            ),
            MockLLMStep(text="1. Research the alpha protocol."),
            MockLLMStep(
                tool_calls=[
                    MockToolCall(
                        id="call_research_agent",
                        name=RESEARCH_AGENT_TOOL_NAME,
                        arguments={RESEARCH_AGENT_TASK_KEY: _RESEARCH_TASK},
                    )
                ]
            ),
            MockLLMStep(
                tool_calls=[
                    MockToolCall(
                        id="call_child_think",
                        name=THINK_TOOL_NAME,
                        arguments={"reasoning": _CHILD_REASONING},
                    )
                ],
                match_prompt_contains=_RESEARCH_TASK,
            ),
            MockLLMStep(
                tool_calls=[MockToolCall(name=GENERATE_REPORT_TOOL_NAME)],
                match_prompt_contains="call_child_think",
            ),
            MockLLMStep(
                text="The alpha protocol started early.",
                match_prompt_contains=_RESEARCH_TASK,
            ),
            MockLLMStep(
                tool_calls=[
                    MockToolCall(
                        id="call_orchestrator_think",
                        name=THINK_TOOL_NAME,
                        arguments={"reasoning": _ORCHESTRATOR_REASONING},
                    )
                ],
                match_prompt_contains="call_research_agent",
            ),
            MockLLMStep(
                tool_calls=[MockToolCall(name=GENERATE_REPORT_TOOL_NAME)],
                match_prompt_contains="call_orchestrator_think",
            ),
            MockLLMStep(text=_FINAL_REPORT),
        ],
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
