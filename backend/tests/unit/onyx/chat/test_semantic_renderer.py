"""The packet view cannot drive model requests or tool execution."""

from collections.abc import Mapping
from queue import Queue

import pytest
from pydantic import BaseModel

from onyx.agents.events import (
    AgentEndEvent,
    MessageEndEvent,
    MessageStartEvent,
    MessageUpdateEvent,
    ToolEndEvent,
    ToolStartEvent,
    ToolUpdateEvent,
)
from onyx.agents.execution_records import OperationSnapshot, RunStatus
from onyx.agents.models import RunState
from onyx.agents.runtime import Agent
from onyx.agents.tools import AgentTool, ToolInvocation, ToolProgress
from onyx.chat.emitter import Emitter
from onyx.chat.models import ChatMessageMetadata, CitationMode, MessageRendering
from onyx.chat.presentation import ResponsePresenter, project_response
from onyx.chat.renderer import MessageRenderer
from onyx.context.search.models import SearchDoc
from onyx.llm.cancellation import CancellationSignal
from onyx.llm.litellm_conversion import MessageAccumulator
from onyx.llm.litellm_models import (
    Delta,
    ModelResponseStream,
    StreamingChoice,
)
from onyx.llm.models import (
    AssistantMessage,
    GenerationDoneEvent,
    GenerationErrorEvent,
    GenerationRequest,
    GenerationRequestParams,
    GenerationStartEvent,
    Message,
    ReasoningEffort,
    TextContent,
    TextDeltaEvent,
    ToolCall,
    ToolResult,
    UserMessage,
)
from onyx.server.query_and_chat.streaming_models import (
    ItemDelta,
    ItemUpdate,
    OverallStop,
    Packet,
    PacketIdentity,
    RunUpdate,
    TextItem,
    TextPurpose,
    ToolOutputUpdate,
)
from onyx.tools.models import LlmPythonExecutionResult
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
            requests=requests, messages=agent.state.messages, executed=executed
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
    renderer = MessageRenderer(
        MessageRendering(citation_mode=CitationMode.REMOVE),
        {},
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
            if not isinstance(
                event, (GenerationStartEvent, GenerationDoneEvent, GenerationErrorEvent)
            ):
                renderer.consume(event)
    for event in accumulator.end():
        if not isinstance(
            event, (GenerationStartEvent, GenerationDoneEvent, GenerationErrorEvent)
        ):
            renderer.consume(event)
    renderer.complete(accumulator.message)
    assert renderer.answer == expected
    assert accumulator.message.text == "".join(fragments)


def test_snapshot_projects_partial_output_before_observers_receive_it() -> None:
    snapshot = RunState(
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
            message_id="child:1",
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
            message_id="child:1",
            tool_call=call,
            progress=ToolProgress(
                details=LlmPythonExecutionResult(
                    stdout="progress",
                    stderr="",
                    exit_code=None,
                    timed_out=False,
                    generated_files=[],
                )
            ),
        )
    )
    view.consume(
        ToolEndEvent(
            run_id="child",
            parent_run_id="root",
            parent_message_id="root:2",
            parent_tool_call_id="research",
            step_index=1,
            message_id="child:1",
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
    progress = [
        packet
        for packet in packets
        if isinstance(packet.obj, ItemDelta)
        and isinstance(packet.obj.delta, ToolOutputUpdate)
    ]
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
    assert isinstance(packets[-1].obj, RunUpdate)
    assert packets[-1].obj.status == "complete"


def test_formatting_failure_keeps_accepted_response(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_formatting(
        _presentation: MessageRendering,
        _documents: Mapping[str, SearchDoc],
        _identity: PacketIdentity,
    ) -> MessageRenderer:
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
    monkeypatch.setattr("onyx.chat.presentation.MessageRenderer", fail_formatting)
    response = project_response(run.snapshot(), response_id=42, tool_ids={})
    assert response.response is not None
    assert response.response.messages[-1].text == "Accepted answer"
    assert response.answer == "Accepted answer"
    assert (
        response.error
        == "Response formatting failed. The accepted content has been retained."
    )


@pytest.mark.parametrize("status", [RunStatus.CANCELLED, RunStatus.ERROR])
def test_interrupted_item_stream_flushes_buffered_citation_like_reload(
    status: RunStatus,
) -> None:
    message = AssistantMessage(content=[TextContent(text="See [1")])
    identity = PacketIdentity(response_id=42, run_id="run", message_id="run:0")
    live = MessageRenderer(
        MessageRendering(citation_mode=CitationMode.HYPERLINK), {}, identity
    )
    live.consume(TextDeltaEvent(content_index=0, text="See [1"))
    live_packets = live.finish(status)
    saved = MessageRenderer(
        MessageRendering(citation_mode=CitationMode.HYPERLINK), {}, identity
    )
    saved_packets = saved.saved(message, status, is_answer=False)
    assert live.answer == saved.answer == "See [1"
    assert [
        p
        for p in live_packets
        if isinstance(p.obj, ItemUpdate) and p.obj.item.status == status
    ] == saved_packets
    assert live.finish(status) == []


def test_complete_only_model_stream_publishes_answer_and_demotes_earlier_text() -> None:
    responses = iter(
        [
            AssistantMessage(content=[TextContent(text="Checking")]),
            AssistantMessage(content=[TextContent(text="The answer")]),
        ]
    )
    output: Queue[Packet] = Queue()
    presenter = ResponsePresenter(Emitter(output.put_nowait, response_id=42))
    agent = Agent(
        FakeModelClient(lambda _request, _signal: next(responses)),
        after_step=lambda step: step.message.text != "The answer",
    )
    run_agent(agent, max_steps=2, listener=presenter.consume)
    items: dict[str, TextItem] = {}
    for packet in output.queue:
        if (
            packet.identity
            and isinstance(packet.obj, ItemUpdate)
            and isinstance(packet.obj.item, TextItem)
        ):
            items[packet.identity.message_id] = packet.obj.item
    assert [(item.text, item.purpose, item.status) for item in items.values()] == [
        ("Checking", TextPurpose.COMMENTARY, RunStatus.COMPLETE),
        ("The answer", TextPurpose.ANSWER, RunStatus.COMPLETE),
    ]


def test_accepted_message_clears_superseded_streamed_text() -> None:
    identity = PacketIdentity(response_id=42, run_id="run", message_id="run:0")
    renderer = MessageRenderer(MessageRendering(), {}, identity)
    renderer.consume(TextDeltaEvent(content_index=0, text="preview"))
    final = renderer.complete(
        AssistantMessage(content=[ToolCall(id="call", name="echo", arguments={})])
    )
    text = [
        packet.obj.item
        for packet in final
        if isinstance(packet.obj, ItemUpdate) and isinstance(packet.obj.item, TextItem)
    ]
    assert len(text) == 1
    assert text[0].text == ""
    assert text[0].status == RunStatus.COMPLETE
    assert text[0].purpose == TextPurpose.COMMENTARY


@pytest.mark.parametrize("status", [RunStatus.CANCELLED, RunStatus.ERROR])
def test_interrupted_message_identity_and_content_match_reload(
    status: RunStatus,
) -> None:
    output: Queue[Packet] = Queue()
    presenter = ResponsePresenter(Emitter(output.put_nowait, response_id=42))
    message = AssistantMessage(
        id="accepted-message", content=[TextContent(text="partial [1")]
    )
    presenter.consume(
        MessageStartEvent(run_id="run", message_id="accepted-message", step_index=3)
    )
    presenter.consume(
        MessageUpdateEvent(
            run_id="run",
            message_id="accepted-message",
            step_index=3,
            generation_event=TextDeltaEvent(content_index=0, text="partial [1"),
        )
    )
    presenter.consume(
        MessageEndEvent(
            run_id="run",
            message_id="accepted-message",
            step_index=3,
            message=message,
            status=status,
        )
    )
    live = [
        packet
        for packet in output.queue
        if isinstance(packet.obj, ItemUpdate) and packet.obj.item.status == status
    ]
    saved = MessageRenderer(
        MessageRendering(),
        {},
        PacketIdentity(response_id=42, run_id="run", message_id="accepted-message"),
    ).saved(message, status, is_answer=False)
    assert [(packet.identity, packet.obj) for packet in live] == [
        (packet.identity, packet.obj) for packet in saved
    ]
    assert all(
        packet.identity.message_id == "accepted-message" for packet in output.queue
    )
