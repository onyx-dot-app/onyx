"""The packet view cannot drive model requests or tool execution."""

from queue import Queue

import pytest
from pydantic import BaseModel

from onyx.agents.events import (
    AgentEndEvent,
    ToolEndEvent,
    ToolStartEvent,
    ToolUpdateEvent,
)
from onyx.agents.runtime import Agent, AgentContext, RunSnapshot
from onyx.agents.tools import AgentTool, ToolInvocation, ToolProgress
from onyx.agents.transcript import OperationSnapshot, RunStatus
from onyx.chat.citation_processor import CitationMode, DynamicCitationProcessor
from onyx.chat.emitter import Emitter, ModelStreamStatus
from onyx.chat.models import ChatStepOutput
from onyx.chat.presentation import ResponsePresenter, project_response
from onyx.chat.renderer import PacketRenderer, RenderConfig, render_message
from onyx.llm.cancellation import CancellationSignal
from onyx.llm.litellm_conversion import MessageAccumulator
from onyx.llm.litellm_models import (
    Delta,
    ModelResponseStream,
    StreamingChoice,
)
from onyx.llm.models import (
    AssistantMessage,
    GenerationErrorEvent,
    GenerationRequest,
    GenerationRequestParams,
    Message,
    ReasoningEffort,
    TextContent,
    TextDeltaEvent,
    ToolCall,
    ToolResult,
    UserMessage,
)
from onyx.server.query_and_chat.streaming_models import (
    OperationStatus,
    OverallStop,
    Packet,
    PacketIdentity,
    PythonToolDelta,
)
from onyx.tools.progress import PythonOutput
from tests.unit.onyx.agents.fakes import FakeModelClient


class _Execution(BaseModel):
    requests: list[GenerationRequest]
    messages: list[Message]
    executed: list[str]


def test_rendering_does_not_change_requests_transcript_or_execution() -> None:
    def run(render: bool) -> _Execution:
        executed: list[str] = []

        def echo(_invocation: ToolInvocation) -> ToolResult:
            executed.append("echo")
            return ToolResult(content="tool value")

        requests: list[GenerationRequest] = []
        responses = iter(
            [
                AssistantMessage(
                    content=[
                        TextContent(text="Let me check."),
                        ToolCall(id="call", name="echo", arguments={}),
                    ],
                ),
                AssistantMessage(content=[TextContent(text="Answer [1].")]),
            ]
        )

        def reply(
            request: GenerationRequest, _signal: CancellationSignal
        ) -> AssistantMessage:
            requests.append(request.model_copy(deep=True))
            return next(responses)

        llm = FakeModelClient(reply)
        agent = Agent(
            llm,
            context=AgentContext(
                tools=[
                    AgentTool(name="echo", description="", parameters={}, execute=echo),
                ]
            ),
        )
        if render:
            presentation = ResponsePresenter(Emitter(Queue(), response_id=42))
            agent.subscribe(presentation.consume)
        agent.run(messages=[UserMessage(content="Question")], max_steps=2)
        return _Execution(
            requests=requests, messages=agent.context.messages, executed=executed
        )

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
        ),
        PacketIdentity(response_id=1, run_id="run", message_id="run:0"),
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


def test_snapshot_projects_partial_output_before_observers_receive_it() -> None:
    snapshot = RunSnapshot(
        run_id="run",
        status=RunStatus.CANCELLED,
        messages=[
            AssistantMessage(
                content=[TextContent(text="partial")],
                stop_reason="aborted",
                metadata=ChatStepOutput(),
            )
        ],
        operations=[
            OperationSnapshot(step_index=0, message_index=0, status=RunStatus.CANCELLED)
        ],
    )
    snapshot.request_params = GenerationRequestParams(
        model_name="test",
        model_provider="test",
        reasoning_effort=ReasoningEffort.LOW,
        max_tokens=128,
        sent_kwargs={},
    )
    before = snapshot.model_dump()
    response = project_response(
        snapshot,
        response_id=42,
        tool_ids={},
    )
    assert response.answer == "partial"
    assert response.request_params == snapshot.request_params
    assert snapshot.model_dump() == before


def test_child_progress_and_completion_keep_explicit_ancestry() -> None:
    output: Queue[tuple[int, Packet | ModelStreamStatus]] = Queue()
    view = ResponsePresenter(Emitter(output, response_id=42))
    call = ToolCall(id="leaf", name="search", arguments={})
    view.consume(
        ToolStartEvent(
            run_id="child",
            parent_run_id="root",
            parent_message_id="root:2",
            parent_tool_call_id="research",
            step_index=1,
            tool_call=call,
        )
    )
    view.consume(
        ToolUpdateEvent(
            run_id="child",
            parent_run_id="root",
            parent_message_id="root:2",
            parent_tool_call_id="research",
            step_index=1,
            tool_call=call,
            progress=ToolProgress(details=PythonOutput(stdout="progress")),
        )
    )
    view.consume(
        ToolEndEvent(
            run_id="child",
            parent_run_id="root",
            parent_message_id="root:2",
            parent_tool_call_id="research",
            step_index=1,
            tool_call=call,
            result=ToolResult(content="complete"),
        )
    )
    view.consume(
        AgentEndEvent(
            run_id="child",
            parent_run_id="root",
            parent_message_id="root:2",
            parent_tool_call_id="research",
            outcome=RunStatus.COMPLETE,
        )
    )
    packets = [entry[1] for entry in list(output.queue) if isinstance(entry[1], Packet)]
    progress = [packet for packet in packets if isinstance(packet.obj, PythonToolDelta)]
    assert len(progress) == 1
    assert progress[0].identity == PacketIdentity(
        response_id=42,
        run_id="child",
        message_id="child:1",
        parent_run_id="root",
        parent_message_id="root:2",
        parent_tool_call_id="research",
        tool_call_id="leaf",
        part_id="tool",
    )
    assert not any(isinstance(packet.obj, OverallStop) for packet in packets)
    assert isinstance(packets[-1].obj, OperationStatus)
    assert packets[-1].obj.status == "complete"


def test_failed_generation_replay_preserves_buffered_citation_text() -> None:
    message = AssistantMessage(
        content=[TextContent(text="See [1")], stop_reason="error"
    )
    config = RenderConfig(citations=DynamicCitationProcessor())
    identity = PacketIdentity(response_id=42, run_id="root", message_id="root:0")
    live = PacketRenderer(config.model_copy(deep=True), identity)
    live.consume(TextDeltaEvent(message=message, content_index=0, text=message.text))
    live.consume(GenerationErrorEvent(message=message))
    replay = PacketRenderer(config.model_copy(deep=True), identity)
    render_message(replay, message, complete=False)
    assert live.answer == "See [1"
    assert replay.answer == live.answer
