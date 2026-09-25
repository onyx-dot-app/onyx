"""The packet view cannot drive model requests or tool execution."""

from collections.abc import Mapping
from queue import Queue

import pytest
from pydantic import BaseModel

from onyx.agents.events import (
    AgentEndEvent,
    MessageEndEvent,
    MessageStartEvent,
    ToolStartEvent,
)
from onyx.agents.execution_records import ExecutionStatus, RunStatus
from onyx.agents.models import RunState, StepRecord
from onyx.agents.runtime import Agent
from onyx.agents.tools import AgentTool, ToolInvocation
from onyx.chat.emitter import Emitter
from onyx.chat.models import ChatMessageMetadata, CitationMode, MessageRendering
from onyx.chat.presentation import ResponsePresenter, project_response
from onyx.chat.renderer import MessageRenderer, ResponseLayout
from onyx.context.search.models import SearchDoc
from onyx.llm.cancellation import CancellationSignal
from onyx.llm.model_response import (
    Delta,
    MessageAccumulator,
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
    AgentResponseDelta,
    AgentResponseStart,
    OverallStop,
    Packet,
    SectionEnd,
)
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
            presentation = ResponsePresenter(Emitter(Queue[Packet]().put_nowait))
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
        ResponseLayout(),
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
        steps=[
            StepRecord(
                message=AssistantMessage(
                    content=[TextContent(text="partial")],
                    stop_reason="aborted",
                    metadata=ChatMessageMetadata(),
                ),
                generation_status=ExecutionStatus.CANCELLED,
                tools={},
            )
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
        tool_ids={},
    )
    assert response.answer == "partial"
    assert response.request_params == snapshot.request_params
    assert snapshot.model_dump() == before


def test_formatting_failure_keeps_accepted_response(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_formatting(
        _presentation: MessageRendering,
        _documents: Mapping[str, SearchDoc],
        _layout: ResponseLayout,
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
    response = project_response(run.snapshot(), tool_ids={})
    assert response.response is not None
    assert response.response.messages[-1].text == "Accepted answer"
    assert response.answer == "Accepted answer"
    assert (
        response.error
        == "Response formatting failed. The accepted content has been retained."
    )


def test_interrupted_text_is_not_duplicated_and_matches_reload() -> None:
    message = AssistantMessage(content=[TextContent(text="See [1")])
    settings = MessageRendering(citation_mode=CitationMode.HYPERLINK)
    live = MessageRenderer(settings, {}, ResponseLayout())
    output = live.consume(TextDeltaEvent(content_index=0, text="See [1"))
    output += live.complete(message)
    output += live.finish()
    saved = MessageRenderer(settings, {}, ResponseLayout())
    restored = saved.complete(message)
    assert live.answer == saved.answer == "See [1"
    assert (
        "".join(p.obj.content for p in output if isinstance(p.obj, AgentResponseDelta))
        == "See [1"
    )
    assert (
        "".join(
            p.obj.content for p in restored if isinstance(p.obj, AgentResponseDelta)
        )
        == "See [1"
    )
    assert sum(isinstance(p.obj, AgentResponseStart) for p in output) == 1
    assert isinstance(output[-1].obj, SectionEnd)


def test_parallel_child_packets_stay_in_parent_tabs() -> None:
    output: list[Packet] = []
    presenter = ResponsePresenter(Emitter(output.append))
    calls = [
        ToolCall(id=str(i), name="research_agent", arguments={"task": str(i)})
        for i in range(2)
    ]
    presenter.consume(
        MessageStartEvent(run_id="root", message_id="parent", step_index=0)
    )
    presenter.consume(
        MessageEndEvent(
            run_id="root",
            message_id="parent",
            step_index=0,
            message=AssistantMessage(content=calls),
            status=ExecutionStatus.COMPLETE,
        )
    )
    for i, call in enumerate(calls):
        presenter.consume(
            ToolStartEvent(
                run_id="root", message_id="parent", step_index=0, tool_call=call
            )
        )
        presenter.consume(
            MessageStartEvent(
                run_id=str(i),
                message_id=f"child-{i}",
                step_index=0,
                parent_run_id="root",
                parent_message_id="parent",
                parent_tool_call_id=call.id,
            )
        )
        presenter.consume(
            MessageEndEvent(
                run_id=str(i),
                message_id=f"child-{i}",
                step_index=0,
                parent_run_id="root",
                parent_message_id="parent",
                parent_tool_call_id=call.id,
                message=AssistantMessage(content=[TextContent(text=str(i))]),
                status=ExecutionStatus.COMPLETE,
            )
        )
        presenter.consume(
            AgentEndEvent(
                run_id=str(i), parent_run_id="root", outcome=RunStatus.COMPLETE
            )
        )
    text = [p for p in output if isinstance(p.obj, AgentResponseDelta)]
    assert [
        (p.placement.turn_index, p.placement.tab_index, p.placement.sub_turn_index)
        for p in text
    ] == [(0, 0, 0), (0, 1, 0)]
    assert not any(isinstance(p.obj, OverallStop) for p in output)
