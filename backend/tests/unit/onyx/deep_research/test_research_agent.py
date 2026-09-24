"""Deep Research child agent: think tool reasoning."""

from collections.abc import Generator
from unittest.mock import patch

import pytest

from onyx.chat.chat_state import ChatStateContainer
from onyx.deep_research.dr_mock_tools import (
    GENERATE_REPORT_TOOL_NAME,
    RESEARCH_AGENT_TASK_KEY,
    RESEARCH_AGENT_TOOL_NAME,
    THINK_TOOL_NAME,
    THINK_TOOL_RESPONSE_MESSAGE,
)
from onyx.llm.models import ToolMessage
from onyx.server.query_and_chat.placement import Placement
from onyx.server.query_and_chat.streaming_models import ReasoningDelta
from onyx.tools.fake_tools import research_agent
from onyx.tools.fake_tools.research_agent import run_research_agent_call
from onyx.tools.models import ToolCallKickoff
from onyx.tools.tool_implementations.web_search.web_search_tool import WebSearchTool
from tests.unit.onyx.deep_research.fakes import (
    FakeSearchTool,
    ScriptedLLM,
    drain,
    make_emitter,
    prompt_messages,
    summarize,
    text,
    token_counter,
    tool_call,
)

TURN = 2
TAB = 1
PARENT_ID = "parent-call"


@pytest.fixture(autouse=True)
def _fixed_datetime() -> Generator[None, None, None]:
    with patch.object(
        research_agent, "get_current_llm_day_time", return_value="Thursday"
    ):
        yield


def test_think_step_shifts_placement_and_carries_full_reasoning() -> None:
    emitter, merged = make_emitter()
    web = FakeSearchTool(WebSearchTool.NAME, emitter, tool_id=11, doc_ids=["w1"])
    llm = ScriptedLLM(
        [
            tool_call("t1", THINK_TOOL_NAME, {"reasoning": "plan the search"}),
            tool_call("c1", WebSearchTool.NAME, {"queries": ["alpha"]}),
            tool_call("c2", GENERATE_REPORT_TOOL_NAME, {}),
            text("Report."),
        ]
    )
    state_container = ChatStateContainer()

    run_research_agent_call(
        research_agent_call=ToolCallKickoff(
            tool_call_id=PARENT_ID,
            tool_name=RESEARCH_AGENT_TOOL_NAME,
            tool_args={RESEARCH_AGENT_TASK_KEY: "Investigate topic A"},
            placement=Placement(turn_index=TURN, tab_index=TAB),
        ),
        parent_tool_call_id=PARENT_ID,
        tools=[web],
        emitter=emitter,
        state_container=state_container,
        llm=llm,
        is_reasoning_model=False,
        token_counter=token_counter,
        user_identity=None,
        language_section="",
    )

    # Non-reasoning models get the think tool.
    assert THINK_TOOL_NAME in llm.calls[0]["tool_names"]

    # The think exchange is replayed in the next step.
    second_prompt = prompt_messages(llm.calls[1])
    assert [m.role for m in second_prompt] == ["system", "user", "assistant", "tool"]
    think_response = second_prompt[-1]
    assert isinstance(think_response, ToolMessage)
    assert think_response.content == THINK_TOOL_RESPONSE_MESSAGE
    assert think_response.tool_call_id == "t1"

    # Think does not use a research cycle but advances the reasoning count
    # twice (streamed reasoning plus the think call itself).
    assert web.runs[0][0] == Placement(turn_index=TURN, tab_index=TAB, sub_turn_index=2)
    [info] = state_container.get_tool_calls()
    assert info.turn_index == 2
    assert info.reasoning_tokens == "plan the search"

    packets = drain(merged)
    reasoning_text = "".join(
        p.obj.reasoning for p in packets if isinstance(p.obj, ReasoningDelta)
    )
    assert reasoning_text == "plan the search"
    assert summarize(packets)[:4] == [
        ("ResearchAgentStart", TURN, TAB, None),
        ("ReasoningStart", TURN, TAB, 0),
        ("ReasoningDelta", TURN, TAB, 0),
        ("ReasoningDone", TURN, TAB, 0),
    ]
