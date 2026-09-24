"""Deep Research batch runner: parent tool call pairing."""

from typing import Any
from unittest.mock import patch

import pytest

from onyx.chat.chat_state import ChatStateContainer
from onyx.deep_research.dr_mock_tools import (
    RESEARCH_AGENT_TASK_KEY,
    RESEARCH_AGENT_TOOL_NAME,
)
from onyx.deep_research.models import ResearchAgentCallResult
from onyx.server.query_and_chat.placement import Placement
from onyx.tools.fake_tools import research_agent
from onyx.tools.fake_tools.research_agent import run_research_agent_calls
from onyx.tools.models import ToolCallKickoff
from tests.unit.onyx.deep_research.fakes import UnusedLLM, make_emitter, token_counter

TURN = 2


def _research_call(call_id: str, tab_index: int) -> ToolCallKickoff:
    return ToolCallKickoff(
        tool_call_id=call_id,
        tool_name=RESEARCH_AGENT_TOOL_NAME,
        tool_args={RESEARCH_AGENT_TASK_KEY: call_id},
        placement=Placement(turn_index=TURN, tab_index=tab_index),
    )


def _run_batch(
    calls: list[ToolCallKickoff], parent_ids: list[str]
) -> list[tuple[str, str]]:
    pairs: list[tuple[str, str]] = []

    def fake_call(
        research_agent_call: ToolCallKickoff,
        parent_tool_call_id: str,
        *_args: Any,
    ) -> ResearchAgentCallResult:
        pairs.append((research_agent_call.tool_call_id, parent_tool_call_id))
        return ResearchAgentCallResult(intermediate_report="r", citation_mapping={})

    with patch.object(research_agent, "run_research_agent_call", fake_call):
        run_research_agent_calls(
            research_agent_calls=calls,
            parent_tool_call_ids=parent_ids,
            tools=[],
            emitter=make_emitter(),
            state_container=ChatStateContainer(),
            llm=UnusedLLM(),
            is_reasoning_model=True,
            token_counter=token_counter,
            citation_mapping={},
            language_section="",
        )
    return pairs


def test_batch_pairs_each_call_with_its_parent_id() -> None:
    calls = [_research_call("rc1", 0), _research_call("rc2", 1)]

    pairs = _run_batch(calls, ["rc1", "rc2"])

    assert sorted(pairs) == [("rc1", "rc1"), ("rc2", "rc2")]


def test_batch_rejects_mismatched_parent_ids() -> None:
    calls = [_research_call("rc1", 0)]

    with pytest.raises(ValueError):
        _run_batch(calls, ["u1", "rc1"])
