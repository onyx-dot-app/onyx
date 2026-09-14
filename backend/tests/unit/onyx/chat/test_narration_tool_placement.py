"""Narration and tools occupy distinct groups in the packet projection."""

import queue
from collections.abc import Iterator
from typing import Any

from onyx.chat.emitter import Emitter
from onyx.chat.presentation import TurnPresentation
from onyx.chat.renderer import RenderConfig
from onyx.llm.interfaces import GenerationContext
from onyx.llm.litellm_models import (
    ChatCompletionDeltaToolCall,
    Delta,
    FunctionCall,
    ModelResponseStream,
    StreamingChoice,
)
from onyx.llm.models import GenerationRequest
from onyx.llm.multi_llm import LitellmLLM
from onyx.server.query_and_chat.placement import Placement
from onyx.server.query_and_chat.streaming_models import (
    AgentResponseDelta,
    AgentResponseStart,
)
from onyx.tracing.flows import LLMFlow
from tests.unit.onyx.agents.fakes import ScriptedTransport


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


class NarrationTransport(ScriptedTransport):
    def stream(self, *args: Any, **kwargs: Any) -> Iterator[ModelResponseStream]:
        del args, kwargs
        return _narration_then_tool_stream()


def _drive() -> tuple[list[Any], Any]:
    """Render model output and look up tool-call display coordinates."""
    output = queue.Queue()
    presentation = TurnPresentation(Emitter(output))
    presentation.configure(RenderConfig(placement=Placement(turn_index=1, tab_index=0)))
    llm = LitellmLLM(NarrationTransport([]))
    message = None
    for event in llm.stream(
        GenerationRequest(), GenerationContext(flow=LLMFlow.CHAT_RESPONSE)
    ):
        presentation.consume_model(event)
        if event.type == "done":
            message = event.message
    assert message is not None
    calls = [presentation.placement_for(call.id) for call in message.tool_calls]
    return [item[1] for item in list(output.queue)], calls


def test_narration_and_tool_call_get_distinct_tabs() -> None:
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
    assert result is not None and len(result) == 1
    tool_placement = result[0]
    assert tool_placement.turn_index == narration_turn
    assert tool_placement.tab_index == 1, (
        "tool call collided with the narration's placement (same turn_index AND "
        "tab_index) — the frontend would route the shared group to the chat area "
        "and the search step would never render in the timeline"
    )
