"""Runtime ownership across hooks, observation, snapshots, and lazy resources."""

import base64
import threading
from collections.abc import Callable, Sequence
from concurrent.futures import ThreadPoolExecutor

import pytest
from pydantic import BaseModel, ValidationError

from onyx.agents.concurrency import EventDelivery
from onyx.agents.events import (
    AgentEvent,
    MessageEndEvent,
)
from onyx.agents.models import (
    AgentState,
    PreparedStep,
    RunHooks,
    StepInput,
    StepResult,
    ToolCallContext,
)
from onyx.agents.runtime import Agent, RunFailed
from onyx.agents.tools import AgentTool, ToolInvocation
from onyx.chat.models import PromptMetadata
from onyx.chat.prompt_formatting import prepare_model_messages
from onyx.chat.response import response_record
from onyx.file_store.models import ChatFileType, ChatLoadedFile
from onyx.llm.cancellation import AgentCancelled, CancellationSignal
from onyx.llm.interfaces import GenerationContext
from onyx.llm.model_response import Delta
from onyx.llm.models import (
    AssistantMessage,
    GenerationRequest,
    ImageContentPart,
    Message,
    SystemMessage,
    TextContent,
    ToolCall,
    ToolDefinition,
    ToolResult,
    ToolResultMessage,
    UserMessage,
)
from onyx.tools.models import CustomToolCallSummary
from onyx.tracing.flows import LLMFlow
from tests.unit.onyx.agents.fakes import (
    FakeModelClient,
    ScriptedLLM,
    collect_generation,
)


class ExtraData(BaseModel):
    value: str = "private metadata"


def _tool(execute: Callable[[ToolInvocation], ToolResult] | None = None) -> AgentTool:
    return AgentTool(
        definition=ToolDefinition(name="lookup", description="", parameters={}),
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
        "onyx.chat.prompt_formatting.model_supports_image_input", lambda *_: True
    )
    agent = Agent(
        llm,
        generation_context=GenerationContext(flow=LLMFlow.CHAT_RESPONSE),
        state=AgentState(
            messages=[
                UserMessage(
                    content="describe",
                    metadata=PromptMetadata(image_files=[attachment]),
                )
            ]
        ),
    )
    agent.feature = RunHooks(
        prepare_step=lambda _input: PreparedStep(
            assemble_messages=lambda messages: prepare_model_messages(
                messages, llm.config
            )
        )
    )
    copies = [agent.state, agent.state]
    for context in copies:
        context.model_dump_json()
    assert loads == 0
    metadata = copies[0].messages[0].metadata
    assert isinstance(metadata, PromptMetadata) and metadata.image_files
    metadata.image_files[0].filename = "changed.png"
    assert attachment.filename == "original.png"
    agent.start(background=False, max_steps=1).result()
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
    output = collect_generation(
        model.stream(
            GenerationRequest(messages=[message]),
            GenerationContext(cancellation=CancellationSignal()),
        )
    )
    assert output.text == "done"
    assert llm.requests[0]["prompt"][0].content == "plain input"
    assert "private metadata" not in str(llm.requests)


def test_finalized_result_keeps_the_recorded_details_without_a_copy() -> None:
    finalized: list[ToolResult] = []

    def finalize(_context: ToolCallContext, result: ToolResult) -> ToolResult:
        finalized.append(result)
        return result

    agent = Agent(
        FakeModelClient(_model),
        generation_context=GenerationContext(flow=LLMFlow.CHAT_RESPONSE),
        tools=[
            _tool(
                lambda _: ToolResult(
                    content="found",
                    details=CustomToolCallSummary(
                        tool_name="lookup", response_type="json", tool_result={"id": 1}
                    ),
                )
            )
        ],
        feature=RunHooks(after_tool_call=finalize),
    )
    run = agent.start(max_steps=2)
    run.result()
    assert run.wait_for_idle(2)
    [result] = finalized
    recorded = run._state.steps[0].tools[run._state.steps[0].message.tool_calls[0].id]
    assert recorded.result is not None
    assert recorded.result.details is result.details


@pytest.mark.parametrize("replace", [False, True])
def test_tool_finalization_has_one_commit_point(replace: bool) -> None:
    requests: list[list[Message]] = []

    def model(
        request: GenerationRequest, _signal: CancellationSignal
    ) -> AssistantMessage:
        requests.append(request.messages)
        return _model(request)

    def finalize(_context: ToolCallContext, result: ToolResult) -> ToolResult:
        if replace:
            return result.model_copy(update={"content": "accepted"})
        result.content = "accepted"
        return result

    agent = Agent(
        FakeModelClient(model),
        generation_context=GenerationContext(flow=LLMFlow.CHAT_RESPONSE),
        tools=[
            _tool(
                lambda _: ToolResult(
                    content="original",
                    details=CustomToolCallSummary(
                        tool_name="lookup", response_type="json", tool_result={"id": 1}
                    ),
                    metadata=ExtraData(),
                )
            )
        ],
        feature=RunHooks(after_tool_call=finalize),
    )
    run = agent.start(max_steps=2)
    result = run.result()
    assert run.wait_for_idle(2)
    snapshot = run.snapshot()
    assert result.output.text == "accepted"
    assert (
        requests[1][-1].text
        == agent.state.messages[1].text
        == snapshot.messages[1].text
        == "accepted"
    )
    record = response_record(snapshot)
    assert "private metadata" not in record.model_dump_json()
    saved_result = record.messages[1]
    assert isinstance(saved_result, ToolResultMessage)
    assert isinstance(saved_result.details, CustomToolCallSummary)
    assert saved_result.details.tool_result == {"id": 1}
    saved_result.details.tool_result = {"id": 2}
    runtime_result = snapshot.messages[1]
    assert isinstance(runtime_result, ToolResultMessage)
    assert isinstance(runtime_result.details, CustomToolCallSummary)
    assert runtime_result.details.tool_result == {"id": 1}


@pytest.mark.parametrize("inherited", [False, True])
def test_events_hold_recorded_objects_that_never_change_after_publication(
    inherited: bool,
) -> None:
    received: list[tuple[AgentEvent, str]] = []
    shared: list[AgentEvent] = []

    def record(event: AgentEvent) -> None:
        received.append((event, event.model_dump_json()))

    def finalize(_context: ToolCallContext, result: ToolResult) -> ToolResult:
        return result.model_copy(update={"content": "accepted"})

    agent = Agent(
        FakeModelClient(_model),
        generation_context=GenerationContext(flow=LLMFlow.CHAT_RESPONSE),
        tools=[_tool()],
        feature=RunHooks(
            after_tool_call=finalize,
            prepare_step=lambda _: PreparedStep(output_metadata=ExtraData()),
        ),
    )
    parent = EventDelivery()
    if inherited:
        parent.subscribe(record)
    parent.subscribe(shared.append)
    run = agent.start(
        max_steps=2,
        on_event=None if inherited else record,
        _event_parent=parent,
    )
    assert run.result(timeout=5).output.text == "accepted"
    assert run.wait_for_idle(5)
    assert [event.model_dump_json() for event, _ in received] == [
        dump for _, dump in received
    ]
    # Every listener gets the published object; events hold recorded objects.
    events = [event for event, _ in received]
    assert all(seen is event for seen, event in zip(shared, events, strict=True))
    end = next(event for event in events if isinstance(event, MessageEndEvent))
    assert end.message is run._state.steps[0].message
    parent.close()


@pytest.mark.parametrize(
    "rewrite",
    [
        lambda step: step.tool_results.clear(),
        lambda step: setattr(step, "message", AssistantMessage()),
    ],
    ids=["clear-results", "replace-message"],
)
def test_after_step_that_rewrites_accepted_output_fails_the_run(
    rewrite: Callable[[StepResult], None],
) -> None:
    def complete(step: StepResult) -> bool:
        rewrite(step)
        return False

    run = Agent(
        FakeModelClient(_model),
        generation_context=GenerationContext(flow=LLMFlow.CHAT_RESPONSE),
        tools=[_tool()],
        feature=RunHooks(after_step=complete),
    ).start(max_steps=1)
    with pytest.raises(RunFailed):
        run.result()
    assert run.wait_for_idle(2)
    assert run.snapshot().messages[0].text == "Searching"
    assert run.snapshot().messages[-1].text == "original"


@pytest.mark.parametrize("cancel_observer", [False, True])
def test_observer_failure_does_not_change_execution(
    cancel_observer: bool,
) -> None:
    def observe(_event: AgentEvent) -> None:
        if cancel_observer:
            raise AgentCancelled()
        raise ValueError("observer failed")

    run = Agent(
        FakeModelClient(
            lambda *_: AssistantMessage(content=[TextContent(text="answer")])
        ),
        generation_context=GenerationContext(flow=LLMFlow.CHAT_RESPONSE),
    ).start(max_steps=1, on_event=observe)
    assert (run.result()).output.text == "answer"
    assert run.wait_for_idle(2)
    assert run.snapshot().status == "complete"
    assert run.delivery_failed


def test_completed_tools_survive_sibling_cancellation() -> None:
    blocked = threading.Event()
    release = threading.Event()

    def execute(invocation: ToolInvocation) -> ToolResult:
        if invocation.call_id == "first":
            return ToolResult(content="completed result")
        blocked.set()
        release.wait()
        return ToolResult(content="second")

    agent = Agent(
        FakeModelClient(
            lambda *_: AssistantMessage(
                content=[
                    ToolCall(id="first", name="lookup", arguments={}),
                    ToolCall(id="second", name="lookup", arguments={}),
                ]
            )
        ),
        generation_context=GenerationContext(flow=LLMFlow.CHAT_RESPONSE),
        tools=[
            AgentTool(
                definition=ToolDefinition(name="lookup", description="", parameters={}),
                execute=execute,
            )
        ],
    )
    run = agent.start(max_steps=1)
    assert blocked.wait(2)
    run.cancel()
    with pytest.raises(AgentCancelled):
        run.result(2)
    assert not run.wait_for_idle(0)
    release.set()
    assert run.wait_for_idle(2)
    snapshot = run.snapshot()
    assert snapshot.messages[-1].text == "completed result"
    assert [
        execution.status for step in snapshot.steps for execution in step.tools.values()
    ] == ["complete", "cancelled"]
    assert snapshot.messages == agent.state.messages


def test_request_assembly_keeps_logical_tool_context_and_metadata() -> None:
    tool_histories: list[list[str]] = []
    model_histories: list[list[str]] = []
    metadata = ExtraData(value="application phase")

    def execute(invocation: ToolInvocation) -> ToolResult:
        tool_histories.append([message.text for message in invocation.messages])
        return ToolResult(content="evidence")

    tool = _tool(execute)

    def prepare(_input: StepInput) -> PreparedStep:
        return PreparedStep(
            output_metadata=metadata,
            assemble_messages=lambda _: [UserMessage(content="provider prompt")],
        )

    def generate(
        request: GenerationRequest, _signal: CancellationSignal
    ) -> AssistantMessage:
        model_histories.append([message.text for message in request.messages])
        return _model(request)

    agent = Agent(
        FakeModelClient(generate),
        generation_context=GenerationContext(flow=LLMFlow.CHAT_RESPONSE),
        state=AgentState(messages=[UserMessage(content="original task")]),
        tools=[tool],
        feature=RunHooks(prepare_step=prepare),
    )
    events: list[AgentEvent] = []
    run = agent.start(max_steps=1, on_event=events.append)
    result = run.result()
    assert run.wait_for_idle(2)
    assert model_histories == [["provider prompt"]]
    assert tool_histories == [["original task"]]
    assert result.output.metadata == metadata
    assert run.snapshot().messages[0].metadata == metadata
    assert response_record(run.snapshot()).messages[0].metadata is None
    starts = [event for event in events if event.type == "message_start"]
    assert len(starts) == 1 and starts[0].metadata == metadata


def test_live_and_completed_history_match_and_are_isolated() -> None:
    step_ready = threading.Event()
    finish_step = threading.Event()

    def after_step(_step: StepResult) -> bool:
        step_ready.set()
        assert finish_step.wait(5)
        return False

    agent = Agent(
        FakeModelClient(
            lambda *_: AssistantMessage(content=[TextContent(text="answer")])
        ),
        generation_context=GenerationContext(flow=LLMFlow.CHAT_RESPONSE),
        state=AgentState(messages=[UserMessage(content="earlier")]),
        feature=RunHooks(after_step=after_step),
    )
    run = agent.start(messages=[UserMessage(content="question")], max_steps=1)
    try:
        assert step_ready.wait(5)
        live_state = agent.state
        assert [message.text for message in live_state.messages] == [
            "earlier",
            "question",
            "answer",
        ]
        detached = agent.state
        first, last = detached.messages[0], detached.messages[-1]
        assert isinstance(first, UserMessage)
        assert isinstance(last, AssistantMessage)
        first.content = "changed"
        last.content.clear()
        assert agent.state == live_state
    finally:
        finish_step.set()
        run.result(timeout=5)
        assert run.wait_for_idle(5)
    assert agent.state == live_state
    live_state.messages.clear()
    assert len(agent.state.messages) == 3


@pytest.mark.parametrize("with_assembly", [False, True])
def test_prepared_request_shares_history_without_changing_it(
    with_assembly: bool,
) -> None:
    original = AssistantMessage(
        content=[
            ToolCall(id="call", name="lookup", arguments={"filters": {"q": "original"}})
        ]
    )
    found = ToolResultMessage(tool_call_id="call", tool_name="lookup", content="found")
    messages: list[Message] = [original, found]
    instructions = SystemMessage(content="Use sources", metadata=ExtraData())
    assembled_from: list[Sequence[Message]] = []

    def assemble(history: Sequence[Message]) -> list[Message]:
        assembled_from.append(history)
        return [instructions, *history]

    request = PreparedStep(
        assemble_messages=assemble if with_assembly else None
    ).generation_request(messages)

    shared = request.messages[1:] if with_assembly else request.messages
    assert len(messages) == 2
    assert original.tool_calls[0].arguments == {"filters": {"q": "original"}}
    # Only the assistant message gets a shallow copy, for its filtered content.
    output = shared[0]
    assert isinstance(output, AssistantMessage)
    assert output is not original
    assert output.tool_calls[0] is original.tool_calls[0]
    assert shared[1] is found
    if with_assembly:
        assert request.messages[0] is instructions
        # The assembler borrows a read-only tuple, like every hook input.
        assert isinstance(assembled_from[0], tuple)
    request.messages.clear()
    assert messages == [original, found]


def test_tool_calls_share_one_read_only_history_view() -> None:
    views: list[Sequence[Message]] = []
    contexts: list[ToolCallContext] = []

    def execute(invocation: ToolInvocation) -> ToolResult:
        views.append(invocation.messages)
        return ToolResult(content="evidence", details=ExtraData())

    def model(
        request: GenerationRequest, _signal: CancellationSignal
    ) -> AssistantMessage:
        step = sum(
            isinstance(message, AssistantMessage) for message in request.messages
        )
        if step == 2:
            return AssistantMessage(content=[TextContent(text="answer")])
        return AssistantMessage(
            content=[
                ToolCall(id=f"{step}-a", name="lookup", arguments={}),
                ToolCall(id=f"{step}-b", name="lookup", arguments={}),
            ]
        )

    def before(context: ToolCallContext) -> None:
        contexts.append(context)

    run = Agent(
        FakeModelClient(model),
        generation_context=GenerationContext(flow=LLMFlow.CHAT_RESPONSE),
        state=AgentState(messages=[UserMessage(content="question")]),
        tools=[_tool(execute)],
        feature=RunHooks(before_tool_call=before),
    ).start(max_steps=3)
    assert run.result(timeout=5).output.text == "answer"
    assert run.wait_for_idle(5)
    first_a, first_b, second_a, second_b = views
    assert first_a is first_b and second_a is second_b
    for context, view in zip(contexts, views, strict=True):
        assert all(
            shown is viewed
            for shown, viewed in zip(context.messages, view, strict=True)
        )
    # The recorded messages themselves, results with their details.
    recorded = run.snapshot()
    assert second_a[1] is run._state.steps[0].message
    assert second_a[2] is run._state.steps[0].tools["0-a"].result
    assert [message.text for message in second_a] == [
        "question",
        "",
        "evidence",
        "evidence",
    ]
    assert recorded.messages[1] == second_a[2]
    assert isinstance(second_a, tuple)
    with pytest.raises(ValidationError):
        contexts[0].messages = ()  # ty: ignore[invalid-assignment]
