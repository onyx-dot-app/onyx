"""Regression test for the "disappearing search step" bug.

When the model narrates AND calls a tool in the same LLM cycle (e.g.
"Let me search Zendesk first." followed by an internal_search call), the
narration streams as the assistant message and the tool call is extracted as a
kickoff. Both must NOT share the same (turn_index, tab_index): the frontend
buckets packets by that pair and routes a bucket whose first packet is a
message to the chat area, which swallows the tool's timeline step.

The fix (onyx/chat/llm_step.py) shifts the tool call to the next tab_index when
pre-tool answer content was emitted, so it forms its own render group.
"""

from collections.abc import Iterator
from typing import Any
from unittest.mock import MagicMock
from unittest.mock import patch

from onyx.chat.llm_step import run_llm_step_pkt_generator
from onyx.llm.interfaces import ToolChoiceOptions
from onyx.llm.model_response import ChatCompletionDeltaToolCall
from onyx.llm.model_response import Delta
from onyx.llm.model_response import FunctionCall
from onyx.llm.model_response import ModelResponseStream
from onyx.llm.model_response import StreamingChoice
from onyx.server.query_and_chat.placement import Placement
from onyx.server.query_and_chat.streaming_models import AgentResponseDelta
from onyx.server.query_and_chat.streaming_models import AgentResponseStart


def _chunk(delta: Delta) -> ModelResponseStream:
    return ModelResponseStream(id="c", created="0", choice=StreamingChoice(delta=delta))


def _narration_then_tool_stream() -> Iterator[ModelResponseStream]:
    # 1) The model narrates before acting -> streamed as answer content.
    yield _chunk(Delta(content="Let me search Zendesk first."))
    # 2) ...then, in the SAME cycle, it calls the search tool.
    yield _chunk(
        Delta(
            tool_calls=[
                ChatCompletionDeltaToolCall(
                    id="call_1",
                    index=0,
                    function=FunctionCall(name="internal_search", arguments=""),
                )
            ]
        )
    )
    yield _chunk(
        Delta(
            tool_calls=[
                ChatCompletionDeltaToolCall(
                    index=0,
                    id=None,
                    function=FunctionCall(name=None, arguments='{"queries": ["x"]}'),
                )
            ]
        )
    )


def _make_llm() -> MagicMock:
    llm = MagicMock()
    llm.config.model_name = "test-model"
    llm.config.model_provider = "openai"
    llm.config.api_base = None
    llm.stream.return_value = _narration_then_tool_stream()
    return llm


def _drive() -> tuple[list[Any], Any]:
    """Run the streaming step and return (emitted_packets, LlmStepResult)."""
    gen = run_llm_step_pkt_generator(
        history=[],
        tool_definitions=[],
        tool_choice=ToolChoiceOptions.AUTO,
        llm=_make_llm(),
        placement=Placement(turn_index=1, tab_index=0),
        state_container=None,
        citation_processor=None,
    )
    packets: list[Any] = []
    result: Any = None
    try:
        while True:
            packets.append(next(gen))
    except StopIteration as stop:
        result, _has_reasoned = stop.value
    return packets, result


@patch("onyx.chat.llm_step.translate_history_to_llm_format", return_value=[])
def test_narration_and_tool_call_get_distinct_tabs(_translate: MagicMock) -> None:
    packets, result = _drive()

    # The narration streamed as the assistant message at the cycle's base tab.
    narration = [
        p
        for p in packets
        if isinstance(p.obj, (AgentResponseStart, AgentResponseDelta))
    ]
    assert narration, "expected the model's narration to stream as answer content"
    narration_turn = narration[0].placement.turn_index
    assert all(p.placement.tab_index == 0 for p in narration)

    # The tool call must land in its own render group: same turn, distinct tab.
    assert result.tool_calls is not None and len(result.tool_calls) == 1
    tool_placement = result.tool_calls[0].placement
    assert tool_placement.turn_index == narration_turn
    assert tool_placement.tab_index == 1, (
        "tool call collided with the narration's placement (same turn_index AND "
        "tab_index) — the frontend would route the shared group to the chat area "
        "and the search step would never render in the timeline"
    )
