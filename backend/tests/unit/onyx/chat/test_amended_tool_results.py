"""A result that a release hook sets reaches the live stream and the saved replay."""

from onyx.agents.models import ToolResultAmendment
from onyx.agents.runtime import Agent
from onyx.agents.tools import AgentTool
from onyx.chat.emitter import Emitter
from onyx.chat.presentation import ResponsePresenter, project_response, replay_response
from onyx.llm.cancellation import CancellationSignal
from onyx.llm.interfaces import GenerationContext
from onyx.llm.models import (
    AssistantMessage,
    GenerationRequest,
    TextContent,
    ToolCall,
    ToolDefinition,
    ToolResult,
    ToolResultMessage,
)
from onyx.server.query_and_chat.streaming_models import (
    CustomToolDelta,
    CustomToolStart,
    OverallStop,
    Packet,
    SectionEnd,
)
from onyx.tracing.flows import LLMFlow
from tests.unit.onyx.agents.fakes import FakeModelClient

CALL_ID = "lookup-call"


def _reply(request: GenerationRequest, _signal: CancellationSignal) -> AssistantMessage:
    if request.messages and isinstance(request.messages[-1], ToolResultMessage):
        return AssistantMessage(content=[TextContent(text="done")])
    return AssistantMessage(content=[ToolCall(id=CALL_ID, name="lookup", arguments={})])


def _card(
    packets: list[Packet],
) -> list[CustomToolStart | CustomToolDelta | SectionEnd]:
    """The tool card's packets: its start, results, and section end."""
    return [
        packet.obj
        for packet in packets
        if isinstance(packet.obj, (CustomToolStart, CustomToolDelta, SectionEnd))
        and packet.placement.turn_index == 0
    ]


def _results(card: list[CustomToolStart | CustomToolDelta | SectionEnd]) -> list[str]:
    return [str(obj.data) for obj in card if isinstance(obj, CustomToolDelta)]


def test_amended_result_streams_after_the_card_ends_and_replays_once() -> None:
    agent = Agent(
        FakeModelClient(_reply),
        generation_context=GenerationContext(flow=LLMFlow.CHAT_RESPONSE),
        tools=[
            AgentTool(
                definition=ToolDefinition(name="lookup", description="", parameters={}),
                execute=lambda _invocation: ToolResult(content="running"),
            )
        ],
        on_finish=lambda _results: [
            ToolResultAmendment(call_id=CALL_ID, result=ToolResult(content="closed"))
        ],
    )
    live: list[Packet] = []
    run = agent.start(
        max_steps=3, on_event=ResponsePresenter(Emitter(live.append)).consume
    )
    run.result()
    assert run.wait_for_idle(5)

    # The card starts and ends once; the amended result follows its section end
    # and the answer, before the stop.
    card = _card(live)
    assert isinstance(card[0], CustomToolStart)
    assert [isinstance(obj, SectionEnd) for obj in card].count(True) == 1
    end = next(i for i, obj in enumerate(card) if isinstance(obj, SectionEnd))
    assert "closed" not in _results(card[:end])
    assert _results(card[end:]) == ["closed"]
    assert isinstance(live[-1].obj, OverallStop)

    # The saved response holds only the amended result, rendered once.
    projected = project_response(run.snapshot(), tool_ids={})
    assert projected.response is not None
    replayed = _card(replay_response(projected.response, {}, {}, {}))
    assert isinstance(replayed[0], CustomToolStart)
    assert isinstance(replayed[-1], SectionEnd)
    assert set(_results(replayed)) == {"closed"}
