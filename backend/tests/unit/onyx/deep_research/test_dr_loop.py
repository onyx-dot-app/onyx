"""Deep Research orchestrator: think tool reasoning."""

from collections.abc import Generator
from unittest.mock import patch

import pytest

from onyx.chat.chat_state import ChatStateContainer
from onyx.chat.models import ChatMessageSimple
from onyx.configs.constants import MessageType
from onyx.deep_research import dr_loop
from onyx.deep_research.dr_loop import run_deep_research_llm_loop
from onyx.deep_research.dr_mock_tools import GENERATE_REPORT_TOOL_NAME, THINK_TOOL_NAME
from onyx.server.query_and_chat.streaming_models import ReasoningDelta
from tests.unit.onyx.deep_research.fakes import (
    ScriptedLLM,
    drain,
    make_emitter,
    summarize,
    text,
    token_counter,
    tool_call,
)

PLAN = "1. Research alpha\n2. Research beta"


@pytest.fixture(autouse=True)
def _isolate_orchestrator() -> Generator[None, None, None]:
    with (
        patch.object(dr_loop, "_get_research_agent_tool_id", return_value=77),
        patch.object(dr_loop, "get_current_llm_day_time", return_value="Thursday"),
        patch.object(dr_loop, "model_is_reasoning_model", return_value=False),
        patch("onyx.llm.litellm_singleton.config.initialize_litellm"),
    ):
        yield


def test_think_reasoning_is_saved_in_full_with_the_report() -> None:
    llm = ScriptedLLM(
        [
            text(PLAN),
            tool_call("t1", THINK_TOOL_NAME, {"reasoning": "decide to report"}),
            tool_call("g1", GENERATE_REPORT_TOOL_NAME, {}),
            text("Final report."),
        ]
    )
    emitter, merged = make_emitter()
    state_container = ChatStateContainer()

    run_deep_research_llm_loop(
        emitter=emitter,
        state_container=state_container,
        simple_chat_history=[
            ChatMessageSimple(
                message="Compare alpha and beta",
                token_count=5,
                message_type=MessageType.USER,
            )
        ],
        tools=[],
        custom_agent_prompt=None,
        llm=llm,
        token_counter=token_counter,
        user_language=None,
        skip_clarification=True,
    )

    # Non-reasoning models get the think tool and its token processor.
    assert THINK_TOOL_NAME in llm.calls[1]["tool_names"]
    assert state_container.get_reasoning_tokens() == "decide to report"
    packets = drain(merged)
    streamed = "".join(
        p.obj.reasoning for p in packets if isinstance(p.obj, ReasoningDelta)
    )
    assert streamed == "decide to report"
    assert ("ReasoningStart", 1, 0, None) in summarize(packets)
    assert summarize(packets)[-1] == ("OverallStop", 3, 0, None)
