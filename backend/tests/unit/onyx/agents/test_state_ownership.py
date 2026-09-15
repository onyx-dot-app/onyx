"""Runtime ownership across hooks, observation, snapshots, and lazy resources."""

import base64
import threading
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor

import pytest
from pydantic import BaseModel

from onyx.agents.events import (
    AgentEvent,
    MessageEndEvent,
    MessageUpdateEvent,
    StepEndEvent,
)
from onyx.agents.runtime import (
    Agent,
    AgentContext,
    AgentHooks,
    StepResult,
    ToolCallContext,
)
from onyx.agents.tools import AgentTool, ToolInvocation, ToolProgress
from onyx.context.messages import PromptMetadata, prepare_model_messages
from onyx.file_store.models import ChatFileType, ChatLoadedFile
from onyx.llm.cancellation import AgentCancelled, CancellationSignal
from onyx.llm.interfaces import GenerationContext
from onyx.llm.litellm_conversion import serialize_request
from onyx.llm.litellm_models import Delta
from onyx.llm.models import (
    AssistantMessage,
    GenerationRequest,
    ImageContentPart,
    ImageUrlDetail,
    Message,
    TextContent,
    ToolCall,
    ToolResult,
    ToolResultMessage,
    UserMessage,
)
from tests.unit.onyx.agents.fakes import FakeModelClient, ScriptedLLM


class ExtraData(BaseModel):
    value: str = "private metadata"


def _tool(execute: Callable[[ToolInvocation], ToolResult] | None = None) -> AgentTool:
    return AgentTool(
        name="lookup",
        description="",
        parameters={},
        execute=execute
        or (lambda _invocation: ToolResult(content="original", details=ExtraData())),
    )


def _model(
    context: GenerationRequest, _signal: CancellationSignal | None = None
) -> AssistantMessage:
    if any(isinstance(message, ToolResultMessage) for message in context.messages):
        return AssistantMessage(content=[TextContent(text=context.messages[-1].text)])
    return AssistantMessage(
        content=[
            TextContent(text="Searching"),
            ToolCall(id="c", name="lookup", arguments={}),
        ]
    )


@pytest.mark.parametrize("replace", [False, True])
def test_tool_finalization_has_one_commit_point(replace: bool) -> None:
    requests: list[list[Message]] = []

    def model(
        context: GenerationRequest, _signal: CancellationSignal | None
    ) -> AssistantMessage:
        requests.append(context.messages)
        return _model(context)

    def finalize(_context: ToolCallContext, result: ToolResult) -> ToolResult:
        if replace:
            return result.model_copy(update={"content": "accepted"})
        result.content = "accepted"
        return result

    agent = Agent(
        FakeModelClient(model),
        context=AgentContext(tools=[_tool()]),
        hooks=AgentHooks(after_tool_call=finalize),
    )
    result = agent.run(max_steps=2)
    snapshot = agent.snapshot()
    assert snapshot is not None
    assert result.output.text == "accepted"
    assert (
        requests[1][-1].text
        == agent.context.messages[1].text
        == snapshot.messages[1].text
        == "accepted"
    )
    assert all(message.metadata is None for message in snapshot.messages)
    assert "private metadata" not in snapshot.transcript().model_dump_json()


def test_step_observer_cannot_rewrite_executed_calls() -> None:
    def rewrite(step: StepResult) -> None:
        step.message.content = []

    agent = Agent(
        FakeModelClient(_model),
        context=AgentContext(tools=[_tool()]),
        hooks=AgentHooks(after_step=rewrite),
    )
    agent.run(max_steps=1)
    snapshot = agent.snapshot()
    assert snapshot is not None and snapshot.status == "limit"
    assert isinstance(snapshot.messages[-1], ToolResultMessage)
    assert snapshot.messages[-1].text == "original"


def test_subscribers_cannot_edit_history_or_each_others_events() -> None:
    def corrupt(event: AgentEvent) -> None:
        if event.type == "message_end":
            event.message.content.clear()
        elif event.type == "tool_end":
            event.result.content = "corrupted"
            event.tool_call.arguments["bad"] = True

    baseline = Agent(FakeModelClient(_model), context=AgentContext(tools=[_tool()]))
    expected = baseline.run(max_steps=2)
    agent = Agent(FakeModelClient(_model), context=AgentContext(tools=[_tool()]))
    observed: list[AgentEvent] = []
    agent.subscribe(corrupt)
    agent.subscribe(observed.append)
    actual = agent.run(max_steps=2)
    assert actual.output == expected.output
    assert actual.steps == expected.steps
    assert actual.stop_reason == expected.stop_reason
    assert agent.context.messages == baseline.context.messages
    actual_snapshot = agent.snapshot()
    expected_snapshot = baseline.snapshot()
    assert actual_snapshot is not None and expected_snapshot is not None
    assert actual_snapshot.messages == expected_snapshot.messages
    assert actual_snapshot.status == expected_snapshot.status
    assert (
        next(event for event in observed if event.type == "message_end").message.text
        == "Searching"
    )
    actual.output.content.clear()
    agent.context.messages.clear()
    assert agent.context.messages[-1].text == "original"


def test_running_snapshot_retains_completed_tools_when_another_is_cancelled() -> None:
    signal = CancellationSignal()
    completed = threading.Event()
    snapshots = []

    def execute(invocation: ToolInvocation) -> ToolResult:
        if invocation.call_id == "first":
            return ToolResult(content="completed result")
        assert completed.wait(2)
        snapshots.append(agent.snapshot(cancelled=True))
        signal.cancel()
        signal.check()
        raise AssertionError("unreachable")

    agent = Agent(
        FakeModelClient(
            lambda *_: AssistantMessage(
                content=[
                    ToolCall(id="first", name="lookup", arguments={}),
                    ToolCall(id="second", name="lookup", arguments={}),
                ]
            )
        ),
        context=AgentContext(
            messages=[UserMessage(content="initial history")],
            tools=[
                AgentTool(name="lookup", description="", parameters={}, execute=execute)
            ],
        ),
    )

    def observe(event: AgentEvent) -> None:
        if event.type == "tool_end" and event.tool_call.id == "first":
            completed.set()

    agent.subscribe(observe)
    with pytest.raises(AgentCancelled):
        agent.run(max_steps=1, cancellation=signal)
    snapshot = agent.snapshot()
    assert snapshot is not None and snapshot.status == "cancelled"
    assert len(snapshot.messages) == 2
    assert (
        snapshot.messages[1].text == snapshots[0].messages[1].text == "completed result"
    )
    operation = next(
        item for item in snapshot.operations if item.tool_call_id == "second"
    )
    assert operation.status == "cancelled"
    assert snapshot.messages == agent.context.messages[1:]


def test_lazy_attachments_share_resources_but_not_message_data(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    loads = 0
    image = base64.b64decode(
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+a1ioAAAAASUVORK5CYII="
    )

    def load() -> bytes:
        nonlocal loads
        loads += 1
        return image

    attachment = ChatLoadedFile.lazy_loaded(
        file_id="image",
        filename="original.png",
        file_type=ChatFileType.IMAGE,
        content_text=None,
        token_count=1,
        loader=load,
    )
    llm = ScriptedLLM([Delta(content="image seen")])
    monkeypatch.setattr(
        "onyx.context.messages.model_supports_image_input", lambda *_: True
    )
    agent = Agent(
        llm,
        context=AgentContext(
            messages=[
                UserMessage(
                    content="describe",
                    metadata=PromptMetadata(image_files=[attachment]),
                )
            ]
        ),
    )
    agent.hooks = AgentHooks(
        prepare_step=lambda context, _turn: context.model_copy(
            update={"messages": prepare_model_messages(context.messages, llm.info)}
        )
    )
    copies = [agent.context, agent.context]
    for context in copies:
        context.model_dump_json()
    assert loads == 0
    metadata = copies[0].messages[0].metadata
    assert isinstance(metadata, PromptMetadata) and metadata.image_files
    metadata.image_files[0].filename = "changed.png"
    assert attachment.filename == "original.png"
    agent.run(max_steps=1)
    assert loads == 1
    with ThreadPoolExecutor(max_workers=2) as executor:
        contents = list(executor.map(lambda _: attachment.content, range(2)))
    assert contents == [image, image]
    assert loads == 1
    assert any(
        isinstance(part, ImageContentPart)
        for part in llm.requests[0]["prompt"][0].content
    )


def test_default_model_accepts_application_metadata_without_chat_policy() -> None:
    llm = ScriptedLLM([Delta(content="done")])
    message = UserMessage(content="plain input", metadata=ExtraData())
    model = llm
    output = list(
        model.stream(
            GenerationRequest(messages=[message]),
            GenerationContext(cancellation=CancellationSignal()),
        )
    )[-1]
    assert output.message.text == "done"
    assert llm.requests[0]["prompt"][0].content == "plain input"
    assert "private metadata" not in str(llm.requests)
    with pytest.raises(ValueError, match="text content"):
        serialize_request(
            GenerationRequest(
                messages=[
                    ToolResultMessage(
                        tool_call_id="c",
                        tool_name="image",
                        content=[
                            ImageContentPart(
                                image_url=ImageUrlDetail(
                                    url="https://example.com/image.png"
                                )
                            )
                        ],
                    )
                ]
            ),
            llm.transport.config,
        )


def test_step_observer_cannot_change_published_text() -> None:
    def rewrite(step: StepResult) -> None:
        step.message.content = [TextContent(text="replacement")]

    agent = Agent(
        FakeModelClient(
            lambda *_: AssistantMessage(content=[TextContent(text="published")])
        ),
        hooks=AgentHooks(after_step=rewrite),
    )
    agent.run(max_steps=1)
    snapshot = agent.snapshot()
    assert snapshot is not None
    assert snapshot.messages[0].text == "published"


def test_observer_failures_do_not_change_agent_or_model_output() -> None:
    def observer(event: AgentEvent) -> None:
        if isinstance(event, (MessageUpdateEvent, MessageEndEvent, StepEndEvent)):
            event.message.content.clear()
        raise ValueError("observer failed")

    agent = Agent(
        FakeModelClient(
            lambda *_: AssistantMessage(content=[TextContent(text="answer")])
        )
    )
    agent.subscribe(observer)
    assert agent.run(max_steps=1).output.text == "answer"
    snapshot = agent.snapshot()
    assert snapshot is not None and snapshot.status == "complete"


def test_cancelled_run_cannot_deliver_result_into_next_run() -> None:
    entered = threading.Event()
    release = threading.Event()
    exited = threading.Event()

    def execute(_invocation: ToolInvocation) -> ToolResult:
        entered.set()
        assert release.wait(5)
        exited.set()
        return ToolResult(content="stale")

    agent = Agent(FakeModelClient(_model), context=AgentContext(tools=[_tool(execute)]))
    signal = CancellationSignal()
    with ThreadPoolExecutor(max_workers=1) as workers:
        previous = workers.submit(agent.run, max_steps=1, cancellation=signal)
        try:
            assert entered.wait(2)
            signal.cancel()
            with pytest.raises(AgentCancelled):
                previous.result(timeout=2)
            agent.llm = FakeModelClient(
                lambda *_: AssistantMessage(content=[TextContent(text="new")])
            )
            assert agent.run(max_steps=1).output.text == "new"
            before = agent.snapshot()
        finally:
            release.set()
        assert exited.wait(2)
        assert agent.snapshot() == before


@pytest.mark.parametrize("accepted", [False, True])
def test_tool_side_effect_cancellation_cutoff(accepted: bool) -> None:
    signal = CancellationSignal()
    writes: list[str] = []

    def execute(_invocation: ToolInvocation) -> ToolResult:
        writes.append("committed")
        if not accepted:
            signal.cancel()
        return ToolResult(content="saved")

    def after_step(_result: StepResult) -> None:
        signal.cancel()

    agent = Agent(
        FakeModelClient(_model),
        context=AgentContext(tools=[_tool(execute)]),
        hooks=AgentHooks(after_step=after_step),
    )
    with pytest.raises(AgentCancelled):
        agent.run(max_steps=2, cancellation=signal)
    snapshot = agent.snapshot()
    assert snapshot is not None and snapshot.status == "cancelled"
    assert writes == ["committed"]
    results = [
        message
        for message in snapshot.messages
        if isinstance(message, ToolResultMessage)
    ]
    assert [result.text for result in results] == (["saved"] if accepted else [])


@pytest.mark.parametrize("terminal", [False, True])
def test_observer_cancellation_does_not_rewrite_execution(terminal: bool) -> None:
    def cancel(event: AgentEvent) -> None:
        if event.type == ("agent_end" if terminal else "message_end"):
            raise AgentCancelled()

    agent = Agent(
        FakeModelClient(
            lambda *_: AssistantMessage(content=[TextContent(text="answer")])
        )
    )
    agent.subscribe(cancel)
    assert agent.run(max_steps=1).output.text == "answer"
    snapshot = agent.snapshot()
    assert snapshot is not None and snapshot.status == "complete"
    assert snapshot.delivery_failed
    assert agent.wait_for_idle(timeout=0)


def test_stream_consumer_cannot_mutate_later_events() -> None:
    model = ScriptedLLM([Delta(content="answer")])
    terminal = None
    for event in model.stream(GenerationRequest()):
        if event.type == "done":
            terminal = event.message
        else:
            event.message.content.clear()
    assert terminal is not None and terminal.text == "answer"


def test_cancel_between_model_commit_and_publication_keeps_both(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    signal = CancellationSignal()
    original = Agent._emit
    seen: list[str] = []

    def cancel_during_publication(self: Agent, event: AgentEvent) -> None:
        if event.type == "message_update" and event.message.text:
            signal.cancel()
        original(self, event)

    monkeypatch.setattr(Agent, "_emit", cancel_during_publication)
    agent = Agent(ScriptedLLM([Delta(content="answer")]))

    def observe(event: AgentEvent) -> None:
        if event.type == "message_update":
            seen.append(event.message.text)

    agent.subscribe(observe)
    with pytest.raises(AgentCancelled):
        agent.run(max_steps=1, cancellation=signal)
    snapshot = agent.snapshot()
    assert snapshot is not None
    assert seen[-1] == snapshot.messages[0].text == "answer"


def test_slow_progress_observer_does_not_block_result_acceptance() -> None:
    observer_entered = threading.Event()
    release_observer = threading.Event()
    seen: list[str] = []

    def execute(invocation: ToolInvocation) -> ToolResult:
        invocation.update(ToolProgress(content="working"))
        return ToolResult(content="finished")

    def observe(event: AgentEvent) -> None:
        if event.type == "tool_update":
            observer_entered.set()
            assert release_observer.wait(5)
        seen.append(event.type)

    agent = Agent(FakeModelClient(_model), context=AgentContext(tools=[_tool(execute)]))
    agent.subscribe(observe)
    with ThreadPoolExecutor(max_workers=1) as workers:
        result = workers.submit(agent.run, max_steps=1)
        try:
            assert observer_entered.wait(2)
            assert agent.wait_for_idle(2)
            snapshot = agent.snapshot()
            assert snapshot is not None
            assert snapshot.messages[-1].text == "finished"
            assert "tool_end" not in seen
        finally:
            release_observer.set()
        result.result(timeout=2)
    assert seen.index("tool_update") < seen.index("tool_end") < seen.index("agent_end")


def test_observer_cleanup_timeout_marks_snapshot_delivery_gap(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("onyx.agents.runtime.EVENT_CLEANUP_SECONDS", 0.05)
    observer_entered = threading.Event()
    release_observer = threading.Event()

    def observe(_event: AgentEvent) -> None:
        observer_entered.set()
        assert release_observer.wait(3)

    agent = Agent(
        FakeModelClient(
            lambda *_: AssistantMessage(content=[TextContent(text="saved answer")])
        )
    )
    agent.subscribe(observe)
    with ThreadPoolExecutor(max_workers=1) as workers:
        result = workers.submit(agent.run, max_steps=1)
        try:
            assert observer_entered.wait(2)
            assert result.result(timeout=2).output.text == "saved answer"
            snapshot = agent.snapshot()
            assert snapshot is not None
            assert snapshot.status == "complete"
            assert snapshot.messages[0].text == "saved answer"
            assert snapshot.delivery_failed
        finally:
            release_observer.set()


def test_request_builder_preserves_tool_context_and_output_metadata() -> None:
    tool_histories: list[list[str]] = []
    model_histories: list[list[str]] = []
    metadata = ExtraData(value="application phase")

    def build_request(context: AgentContext) -> GenerationRequest:
        request = context.generation_request()
        request.messages = [UserMessage(content="provider prompt")]
        return request

    def generate(
        request: GenerationRequest, _signal: CancellationSignal
    ) -> AssistantMessage:
        model_histories.append([message.text for message in request.messages])
        return _model(request)

    def execute(invocation: ToolInvocation) -> ToolResult:
        tool_histories.append([message.text for message in invocation.messages])
        return ToolResult(content="saved evidence")

    agent = Agent(
        FakeModelClient(generate),
        context=AgentContext(
            messages=[UserMessage(content="original task")],
            tools=[_tool(execute)],
            output_metadata=metadata,
        ),
        hooks=AgentHooks(build_request=build_request),
    )
    events: list[AgentEvent] = []
    agent.subscribe(events.append)
    result = agent.run(max_steps=1)
    assert model_histories == [["provider prompt"]]
    assert tool_histories == [["original task"]]
    assert result.output.metadata == metadata
    starts = [event for event in events if event.type == "message_start"]
    assert len(starts) == 1 and starts[0].metadata == metadata
    snapshot = agent.snapshot()
    assert snapshot is not None
    assert snapshot.messages[0].metadata == metadata
    assert snapshot.transcript().messages[0].metadata is None
