"""The packet view cannot drive model requests or tool execution."""

from queue import Queue

import pytest

from onyx.agents.events import AgentEvent
from onyx.agents.runtime import Agent, AgentContext
from onyx.agents.tools import AgentTool
from onyx.chat.chat_state import ChatStateContainer
from onyx.chat.citation_processor import CitationMode, DynamicCitationProcessor
from onyx.chat.emitter import Emitter, ModelStreamStatus
from onyx.chat.presentation import TurnPresentation
from onyx.chat.renderer import PacketRenderer, RenderConfig
from onyx.llm.cancellation import AgentCancelled, CancellationSignal
from onyx.llm.litellm_conversion import MessageAccumulator
from onyx.llm.litellm_models import (
    ChatCompletionDeltaToolCall,
    Delta,
    FunctionCall,
    ModelResponseStream,
    StreamingChoice,
)
from onyx.llm.models import (
    AssistantMessage,
    GenerationDoneEvent,
    GenerationRequestParams,
    ReasoningEffort,
    ToolCall,
    ToolResult,
    UserMessage,
)
from onyx.server.query_and_chat.placement import Placement
from onyx.server.query_and_chat.streaming_models import AgentResponseDelta, Packet
from onyx.tools.tool_runner import bind_tool
from tests.unit.onyx.agents.fakes import FakeModelClient, ScriptedLLM


def test_presentation_saves_request_settings_from_the_event() -> None:
    state = ChatStateContainer()
    view = TurnPresentation(Emitter(Queue()))
    view.configure(RenderConfig(), state)
    event = GenerationDoneEvent(
        message=AssistantMessage(),
        request_params=GenerationRequestParams(
            model_name="test",
            model_provider="test",
            reasoning_effort=ReasoningEffort.LOW,
            max_tokens=128,
            sent_kwargs={},
        ),
    )
    view.consume_model(event)
    assert state.snapshot().request_params == event.request_params
    assert event.request_params is not None
    event.request_params.max_tokens = 256
    snapshot = state.snapshot()
    assert snapshot.request_params is not None
    assert snapshot.request_params.max_tokens == 128


def test_rendering_does_not_change_requests_transcript_or_execution() -> None:
    def run(render: bool) -> tuple[object, object, list[str]]:
        executed: list[str] = []

        def echo(
            _id: str, _args: object, _signal: object, _update: object
        ) -> ToolResult:
            executed.append("echo")
            return ToolResult(content="tool value")

        llm = ScriptedLLM(
            [
                Delta(
                    content="Let me check.",
                    tool_calls=[
                        ChatCompletionDeltaToolCall(
                            index=0,
                            id="call",
                            function=FunctionCall(name="echo", arguments="{}"),
                        )
                    ],
                ),
                Delta(content="Answer [1]."),
            ]
        )
        agent = Agent(
            llm,
            context=AgentContext(
                tools=[
                    AgentTool(name="echo", description="", parameters={}, execute=echo),
                ]
            ),
        )
        if render:
            presentation = TurnPresentation(Emitter(Queue()))
            agent.subscribe(presentation.consume)
        result = agent.run(messages=[UserMessage(content="Question")], max_turns=2)
        return llm.requests, result.messages, executed

    assert run(True) == run(False)


@pytest.mark.parametrize(
    "fragments, expected",
    [
        (["Answer [", "1", "]."], "Answer."),
        (["[1]"], "[1]"),
        (["<unknown>literal XML</unknown>"], "<unknown>literal XML</unknown>"),
        (["unfinished ["], "unfinished ["),
    ],
)
def test_citation_display_keeps_raw_transcript(
    fragments: list[str], expected: str
) -> None:
    accumulator = MessageAccumulator()
    renderer = PacketRenderer(
        RenderConfig(
            citations=DynamicCitationProcessor(citation_mode=CitationMode.REMOVE)
        )
    )
    for fragment in fragments:
        for event in accumulator.add(
            ModelResponseStream(
                id="m",
                created="1",
                choice=StreamingChoice(delta=Delta(content=fragment)),
            )
        ):
            renderer.consume(event)
    for event in accumulator.end():
        renderer.consume(event)
    assert renderer.answer == expected
    assert accumulator.message.text == "".join(fragments)


def test_tool_packets_cross_the_agent_progress_boundary_once() -> None:
    queue: Queue[tuple[int, Packet | ModelStreamStatus]] = Queue()
    emitter = Emitter(queue)
    presentation = TurnPresentation(emitter)

    def execute(_call: object) -> ToolResult:
        emitter.emit(
            Packet(
                placement=Placement(turn_index=0),
                obj=AgentResponseDelta(content="progress"),
            )
        )
        return ToolResult(content="done")

    bound = bind_tool({"function": {"name": "work"}}, execute)
    llm = ScriptedLLM(
        [
            Delta(
                tool_calls=[
                    ChatCompletionDeltaToolCall(
                        index=0,
                        id="call",
                        function=FunctionCall(name="work", arguments="{}"),
                    )
                ]
            )
        ]
    )
    agent = Agent(
        llm,
        context=AgentContext(tools=[bound]),
    )
    events: list[AgentEvent] = []
    agent.subscribe(events.append)
    agent.subscribe(presentation.consume)
    agent.run(max_turns=1)
    updates = [event for event in events if event.type == "tool_update"]
    assert len(updates) == 1
    assert updates[0].tool_call and updates[0].tool_call.id == "call"
    assert queue.qsize() == 1
    packet = queue.get()[1]
    assert isinstance(packet, Packet) and isinstance(packet.obj, AgentResponseDelta)
    assert packet.obj.content == "progress"


def test_nested_runs_identify_the_parent_tool_call() -> None:
    child_events: list[AgentEvent] = []
    child = Agent(ScriptedLLM([Delta(content="child")]))
    child.subscribe(child_events.append)
    tool = AgentTool(
        name="child",
        description="",
        parameters={},
        execute=lambda _id, _args, _signal, _update: ToolResult(
            content=child.run(max_turns=1).output.text
        ),
    )
    parent = Agent(
        FakeModelClient(
            lambda _context, _signal: AssistantMessage(
                content=[ToolCall(id="parent-call", name="child", arguments={})]
            )
        ),
        context=AgentContext(tools=[tool]),
    )
    parent_events: list[AgentEvent] = []
    parent.subscribe(parent_events.append)
    parent.run(max_turns=1)
    assert child_events
    assert all(event.parent_run_id == parent_events[0].run_id for event in child_events)
    assert all(event.parent_tool_call_id == "parent-call" for event in child_events)


def test_stop_retains_partial_canonical_message_and_display() -> None:
    signal = CancellationSignal()
    agent = Agent(ScriptedLLM([Delta(content="partial")]))
    presentation = TurnPresentation(Emitter(Queue()))
    agent.subscribe(presentation.consume)

    def stop(event: AgentEvent) -> None:
        if (
            event.type == "message_update"
            and event.generation_event.type == "text_delta"
        ):
            signal.cancel()

    agent.subscribe(stop)
    with pytest.raises(AgentCancelled):
        agent.run(max_turns=1, cancellation=signal)
    assert isinstance(agent.context.messages[-1], AssistantMessage)
    assert agent.context.messages[-1].text == "partial"
    assert agent.context.messages[-1].stop_reason == "aborted"
    assert presentation.renderer.answer == "partial"


def test_nested_tool_packets_reach_each_progress_observer_once() -> None:
    queue: Queue[tuple[int, Packet | ModelStreamStatus]] = Queue()
    emitter = Emitter(queue)
    parent_view, child_view = TurnPresentation(emitter), TurnPresentation(emitter)
    parent_view.configure(RenderConfig(placement=Placement(turn_index=7)))
    child_view.configure(
        RenderConfig(placement=Placement(turn_index=0, sub_turn_index=3), nested=True)
    )

    def leaf(_call: object) -> ToolResult:
        emitter.emit(
            Packet(
                placement=Placement(turn_index=0),
                obj=AgentResponseDelta(content="nested progress"),
            )
        )
        return ToolResult(content="done")

    child_tool = bind_tool({"function": {"name": "leaf"}}, leaf)
    child = Agent(
        FakeModelClient(
            lambda _context, _signal: AssistantMessage(
                content=[ToolCall(id="leaf-call", name="leaf", arguments={})]
            )
        ),
        context=AgentContext(tools=[child_tool]),
    )
    child_events: list[AgentEvent] = []
    child.subscribe(child_events.append)
    child.subscribe(child_view.consume)

    def run_child(_call: object) -> ToolResult:
        child.run(max_turns=1)
        return ToolResult(content="child done")

    parent_tool = bind_tool({"function": {"name": "child"}}, run_child)
    parent = Agent(
        FakeModelClient(
            lambda _context, _signal: AssistantMessage(
                content=[ToolCall(id="parent-call", name="child", arguments={})]
            )
        ),
        context=AgentContext(tools=[parent_tool]),
    )
    parent_events: list[AgentEvent] = []
    parent.subscribe(parent_events.append)
    parent.subscribe(parent_view.consume)
    parent.run(max_turns=1)
    assert len([event for event in child_events if event.type == "tool_update"]) == 1
    assert len([event for event in parent_events if event.type == "tool_update"]) == 1
    assert queue.qsize() == 1
    packet = queue.get()[1]
    assert isinstance(packet, Packet)
    assert packet.placement == Placement(turn_index=7, sub_turn_index=3, model_index=0)


@pytest.mark.parametrize("text_as_thinking", [False, True])
@pytest.mark.parametrize("nested", [False, True])
def test_tool_arguments_progress_and_saved_placement_share_one_policy(
    text_as_thinking: bool,
    nested: bool,
) -> None:
    from onyx.server.query_and_chat.streaming_models import ToolCallArgumentDelta
    from onyx.tools.models import ToolCallKickoff

    queue: Queue[tuple[int, Packet | ModelStreamStatus]] = Queue()
    emitter = Emitter(queue)
    view = TurnPresentation(emitter)
    view.configure(
        RenderConfig(
            placement=Placement(
                turn_index=7, tab_index=4, sub_turn_index=2 if nested else None
            ),
            nested=nested,
            text_as_thinking=text_as_thinking,
            argument_tools={"work"},
        )
    )
    neutral_calls: list[ToolCallKickoff] = []

    def execute(call: ToolCallKickoff) -> ToolResult:
        neutral_calls.append(call)
        emitter.emit(
            Packet(
                placement=call.placement,
                obj=AgentResponseDelta(content=call.tool_call_id),
            )
        )
        return ToolResult(content="done")

    calls = [
        ChatCompletionDeltaToolCall(
            index=index,
            id=f"call-{index}",
            function=FunctionCall(name="work", arguments='{"value":"x"}'),
        )
        for index in range(2)
    ]
    llm = ScriptedLLM(
        [Delta(reasoning_content="Consider", content="Searching", tool_calls=calls)]
    )
    agent = Agent(
        llm,
        context=AgentContext(
            tools=[bind_tool({"function": {"name": "work"}}, execute)]
        ),
    )
    agent.subscribe(view.consume)
    agent.run(max_turns=1)
    packets = [entry[1] for entry in list(queue.queue) if isinstance(entry[1], Packet)]
    arguments = [
        packet for packet in packets if isinstance(packet.obj, ToolCallArgumentDelta)
    ]
    progress = [
        packet
        for packet in packets
        if isinstance(packet.obj, AgentResponseDelta)
        and packet.obj.content.startswith("call-")
    ]
    assert len(arguments) == len(progress) == 2
    for index, argument in enumerate(arguments):
        call_id = f"call-{index}"
        update = next(packet for packet in progress if packet.obj.content == call_id)
        assert argument.placement == update.placement
        assert argument.placement.model_copy(
            update={"model_index": None}
        ) == view.placement_for(call_id)
    assert all(call.placement == Placement(turn_index=0) for call in neutral_calls)
    # Reconfiguring the next turn must retain finalized call placements for storage.
    expected = view.placement_for("call-0")
    view.configure(RenderConfig())
    assert view.placement_for("call-0") == expected
