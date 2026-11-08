"""A result that a release hook sets for an ended call reaches the saved replay."""

from onyx.agents.events import ToolResultAmendedEvent
from onyx.agents.models import ToolResultAmendment
from onyx.agents.runtime import Agent, Run
from onyx.agents.tools import AgentTool
from onyx.chat.emitter import Emitter
from onyx.chat.presentation import ResponsePresenter, project_response, replay_response
from onyx.deep_research.tool_definitions import THINK_TOOL_NAME
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


def _agent(tool_name: str) -> Agent:
    def reply(
        request: GenerationRequest, _signal: CancellationSignal
    ) -> AssistantMessage:
        if request.messages and isinstance(request.messages[-1], ToolResultMessage):
            return AssistantMessage(content=[TextContent(text="done")])
        return AssistantMessage(
            content=[ToolCall(id=CALL_ID, name=tool_name, arguments={})]
        )

    return Agent(
        FakeModelClient(reply),
        generation_context=GenerationContext(flow=LLMFlow.CHAT_RESPONSE),
        tools=[
            AgentTool(
                definition=ToolDefinition(
                    name=tool_name, description="", parameters={}
                ),
                execute=lambda _invocation: ToolResult(content="running"),
            )
        ],
        on_finish=lambda _results: [
            ToolResultAmendment(call_id=CALL_ID, result=ToolResult(content="closed"))
        ],
    )


def _stream(agent: Agent) -> tuple[list[Packet], Run]:
    live: list[Packet] = []
    run = agent.start(
        max_steps=3, on_event=ResponsePresenter(Emitter(live.append)).consume
    )
    run.result()
    assert run.wait_for_idle(5)
    return live, run


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


def test_an_ended_card_keeps_its_result_and_replay_shows_the_amended_one() -> None:
    live, run = _stream(_agent("lookup"))

    # The card starts and ends once with the result it completed with.
    card = _card(live)
    assert isinstance(card[0], CustomToolStart)
    assert isinstance(card[-1], SectionEnd)
    assert [isinstance(obj, SectionEnd) for obj in card].count(True) == 1
    assert set(_results(card)) == {"running"}
    assert isinstance(live[-1].obj, OverallStop)

    # The saved response holds only the amended result, rendered once.
    projected = project_response(run.snapshot(), tool_ids={})
    assert projected.response is not None
    replayed = _card(replay_response(projected.response, {}, {}, {}))
    assert isinstance(replayed[0], CustomToolStart)
    assert isinstance(replayed[-1], SectionEnd)
    assert set(_results(replayed)) == {"closed"}


def test_an_amended_hidden_call_stays_hidden() -> None:
    live, _run = _stream(_agent(THINK_TOOL_NAME))

    assert not any(
        isinstance(packet.obj, (CustomToolStart, CustomToolDelta)) for packet in live
    )
    assert isinstance(live[-1].obj, OverallStop)


def test_a_restored_call_amended_twice_renders_one_card() -> None:
    """A suspend hook and then a finish hook amend a call from before a restore."""
    live: list[Packet] = []
    presenter = ResponsePresenter(Emitter(live.append))
    for content in ("suspended", "closed"):
        presenter.consume(
            ToolResultAmendedEvent(
                run_id="restored",
                message_id="earlier-message",
                step_index=0,
                tool_call=ToolCall(id=CALL_ID, name="lookup", arguments={}),
                result=ToolResult(content=content),
            )
        )

    # One card ends with the first amendment and keeps what it showed.
    card = [
        packet.obj
        for packet in live
        if isinstance(packet.obj, (CustomToolStart, CustomToolDelta, SectionEnd))
    ]
    assert [type(obj) for obj in card] == [CustomToolStart, CustomToolDelta, SectionEnd]
    assert _results(card) == ["suspended"]
