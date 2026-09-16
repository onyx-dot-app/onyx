"""The packet view cannot drive model requests or tool execution."""

from collections.abc import Mapping
from queue import Queue

import pytest
from pydantic import BaseModel

from onyx.agents.events import (
    AgentEndEvent,
    MessageUpdateEvent,
    ToolEndEvent,
    ToolStartEvent,
    ToolUpdateEvent,
)
from onyx.agents.items import build_response_items, messages_from_items
from onyx.agents.models import RunSnapshot
from onyx.agents.runtime import Agent
from onyx.agents.tools import AgentTool, ToolInvocation, ToolProgress
from onyx.agents.transcript import OperationSnapshot, RunStatus
from onyx.chat.citation_processor import DynamicCitationProcessor
from onyx.chat.emitter import Emitter
from onyx.chat.models import ChatMessageMetadata, CitationMode, MessageRendering
from onyx.chat.presentation import ResponsePresenter, project_response
from onyx.chat.renderer import PacketRenderer, RenderConfig
from onyx.chat.tool_progress import tool_display_progress
from onyx.context.search.models import SearchDoc
from onyx.deep_research.tool_definitions import THINK_TOOL_NAME
from onyx.llm.cancellation import CancellationSignal
from onyx.llm.litellm_conversion import MessageAccumulator
from onyx.llm.litellm_models import (
    Delta,
    ModelResponseStream,
    StreamingChoice,
)
from onyx.llm.models import (
    AssistantMessage,
    GenerationRequest,
    GenerationRequestParams,
    Message,
    ReasoningEffort,
    TextContent,
    ThinkingContent,
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
    ReasoningDone,
    ReasoningStart,
)
from onyx.tools.progress import PythonOutput
from onyx.tools.tool_implementations.python.python_tool import PythonTool
from tests.unit.onyx.agents.fakes import FakeModelClient, run_agent


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
            tools=[
                AgentTool(name="echo", description="", parameters={}, execute=echo),
            ],
        )
        listener = None
        if render:
            presentation = ResponsePresenter(
                Emitter(Queue[Packet]().put_nowait, response_id=42)
            )
            listener = presentation.consume
        run_agent(
            agent,
            messages=[UserMessage(content="Question")],
            max_steps=2,
            listener=listener,
        )
        return _Execution(
            requests=requests, messages=agent.context.messages, executed=executed
        )

    rendered = run(True)
    plain = run(False)
    for execution in (rendered, plain):
        for message in execution.messages:
            if isinstance(message, AssistantMessage):
                message.id = None
        for request in execution.requests:
            for message in request.messages:
                if isinstance(message, AssistantMessage):
                    message.id = None
    assert rendered == plain


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
            renderer.consume_items(
                MessageUpdateEvent(
                    run_id="run", step_index=0, generation_event=event
                ).items
            )
    for event in accumulator.end():
        renderer.consume_items(
            MessageUpdateEvent(run_id="run", step_index=0, generation_event=event).items
        )
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
                metadata=ChatMessageMetadata(),
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
    output: Queue[Packet] = Queue()
    view = ResponsePresenter(Emitter(output.put_nowait, response_id=42))
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
    packets = list(output.queue)
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


def test_tool_display_handles_incomplete_calls_without_fabricated_arguments() -> None:
    call = ToolCall(id="partial", name=PythonTool.NAME, arguments={})
    assert tool_display_progress(call, None) == []
    call.arguments = {"code": "print(1)"}
    updates = tool_display_progress(call, None)
    assert len(updates) == 1
    assert updates[0].details is not None
    assert updates[0].details.model_dump() == {"code": "print(1)"}


def test_framework_control_tool_finishes_without_a_custom_tool_card() -> None:
    queue: Queue[Packet] = Queue()
    presenter = ResponsePresenter(Emitter(queue.put_nowait, response_id=42))
    call = ToolCall(id="think", name=THINK_TOOL_NAME, arguments={"thoughts": "plan"})
    presenter.consume(ToolStartEvent(run_id="run", step_index=0, tool_call=call))
    presenter.consume(
        ToolEndEvent(
            run_id="run",
            step_index=0,
            tool_call=call,
            result=ToolResult(content="done"),
        )
    )
    packets = list(queue.queue)
    statuses = [
        packet.obj
        for packet in packets
        if isinstance(packet, Packet) and isinstance(packet.obj, OperationStatus)
    ]
    assert statuses[-1].status == "complete"
    assert all(
        not isinstance(packet, Packet) or not packet.obj.type.startswith("custom_tool")
        for packet in packets
    )


def test_formatting_failure_keeps_accepted_response(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_formatting(
        _presentation: MessageRendering, _documents: Mapping[str, SearchDoc]
    ) -> RenderConfig:
        raise ValueError("Invalid display metadata")

    agent = Agent(
        FakeModelClient(
            lambda _request, _signal: AssistantMessage(
                content=[TextContent(text="Accepted answer")]
            )
        )
    )
    run = agent.start(messages=[UserMessage(content="Question")], max_steps=1)
    run.result(timeout=10)
    monkeypatch.setattr("onyx.chat.presentation.render_config", fail_formatting)
    response = project_response(run.snapshot(), response_id=42, tool_ids={})
    assert response.response is not None
    assert messages_from_items(response.response.items)[-1].text == "Accepted answer"
    assert response.answer == "Accepted answer"
    assert (
        response.error
        == "Response formatting failed. The accepted content has been retained."
    )


def test_repeated_tool_snapshot_does_not_split_later_reasoning() -> None:
    renderer = PacketRenderer(
        RenderConfig(), PacketIdentity(response_id=42, run_id="run", message_id="run:0")
    )
    message = AssistantMessage(
        content=[
            ToolCall(id="call", name="search", arguments={}),
            ThinkingContent(text="First"),
        ]
    )
    operation = OperationSnapshot(
        step_index=0, message_index=0, status=RunStatus.RUNNING
    )
    packets = renderer.consume_items(
        build_response_items("run", [message], [operation])
    )
    message.content[1] = ThinkingContent(text="First, then second")
    packets.extend(
        renderer.consume_items(build_response_items("run", [message], [operation]))
    )
    assert renderer.reasoning == "First, then second"
    assert sum(isinstance(packet.obj, ReasoningStart) for packet in packets) == 1
    assert not any(isinstance(packet.obj, ReasoningDone) for packet in packets)
    packets.extend(renderer.finish(RunStatus.CANCELLED))
    assert sum(isinstance(packet.obj, ReasoningDone) for packet in packets) == 1


@pytest.mark.parametrize("status", [RunStatus.CANCELLED, RunStatus.ERROR])
def test_interrupted_item_stream_flushes_buffered_citation_like_reload(
    status: RunStatus,
) -> None:
    message = AssistantMessage(content=[TextContent(text="See [1")])
    operation = OperationSnapshot(
        step_index=0, message_index=0, status=RunStatus.RUNNING
    )
    config = RenderConfig(citations=DynamicCitationProcessor())
    identity = PacketIdentity(response_id=42, run_id="run", message_id="run:0")
    live = PacketRenderer(config.model_copy(deep=True), identity)
    live.consume_items(build_response_items("run", [message], [operation]))
    live.finish(status)
    operation.status = status
    saved = PacketRenderer(config.model_copy(deep=True), identity)
    saved.consume_items(build_response_items("run", [message], [operation]))
    assert live.answer == saved.answer == "See [1"
    assert live.finish(status) == []
