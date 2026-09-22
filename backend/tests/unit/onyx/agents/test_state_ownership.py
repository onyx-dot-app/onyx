"""Runtime ownership across hooks, observation, snapshots, and lazy resources."""

import base64
import threading
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor

import pytest
from pydantic import BaseModel

from onyx.agents.events import (
    AgentEvent,
)
from onyx.agents.items import messages_from_items
from onyx.agents.models import (
    AgentContext,
    PreparedStep,
    StepInput,
    StepResult,
    ToolCallContext,
)
from onyx.agents.runtime import Agent
from onyx.agents.tools import AgentTool, ToolInvocation
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
    agent.prepare_step = lambda _input: PreparedStep(
        assemble_messages=lambda messages: prepare_model_messages(messages, llm.info)
    )
    copies = [agent.context, agent.context]
    for context in copies:
        context.model_dump_json()
    assert loads == 0
    metadata = copies[0].messages[0].metadata
    assert isinstance(metadata, PromptMetadata) and metadata.image_files
    metadata.image_files[0].filename = "changed.png"
    assert attachment.filename == "original.png"
    agent.execute(max_steps=1).result()
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


def test_stream_consumer_cannot_mutate_later_events() -> None:
    model = ScriptedLLM([Delta(content="answer")])
    terminal = None
    for event in model.stream(GenerationRequest()):
        if event.type == "done":
            terminal = event.message
        else:
            event.message.content.clear()
    assert terminal is not None and terminal.text == "answer"


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

    agent = Agent(FakeModelClient(model), tools=[_tool()], after_tool_call=finalize)
    run = agent.start(max_steps=2)
    result = run.result()
    assert run.wait_for_idle(2)
    snapshot = run.snapshot()
    assert result.output.text == "accepted"
    assert (
        requests[1][-1].text
        == agent.context.messages[1].text
        == snapshot.messages[1].text
        == "accepted"
    )
    assert "private metadata" not in "".join(
        item.model_dump_json() for item in snapshot.items
    )


@pytest.mark.parametrize("inherited", [False, True])
def test_listeners_cannot_edit_history_or_each_others_events(inherited: bool) -> None:
    def corrupt(event: AgentEvent) -> None:
        if event.type == "message_end":
            event.message.content.clear()
        elif event.type == "message_update":
            event.generation_event.message.content.clear()
        elif event.type == "tool_end":
            event.result.content = "corrupted"
            event.tool_call.arguments["bad"] = True

    ready = threading.Event()

    def generate(
        request: GenerationRequest, _signal: CancellationSignal
    ) -> AssistantMessage:
        assert ready.wait(2)
        return _model(request)

    agent = Agent(FakeModelClient(generate), tools=[_tool()])
    observed: list[AgentEvent] = []
    run = agent.start(
        max_steps=2,
        on_event=None if inherited else corrupt,
        inherited_event_sink=corrupt if inherited else None,
    )
    run.subscribe(observed.append)
    ready.set()
    result = run.result()
    assert run.wait_for_idle(2)
    assert result.output.text == "original"
    assert agent.context.messages[-1].text == "original"
    assert (
        next(event for event in observed if event.type == "message_end").message.text
        == "Searching"
    )
    result.output.content.clear()
    run.snapshot().messages.clear()
    agent.context.messages.clear()
    assert run.snapshot().messages[-1].text == "original"


def test_after_step_cannot_rewrite_accepted_output() -> None:
    def complete(step: StepResult) -> bool:
        step.message.content.clear()
        step.tool_results.clear()
        return False

    run = Agent(FakeModelClient(_model), tools=[_tool()], after_step=complete).start(
        max_steps=1
    )
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
        )
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
        tools=[
            AgentTool(name="lookup", description="", parameters={}, execute=execute)
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
        operation.status for operation in snapshot.operations if operation.tool_call_id
    ] == ["complete", "cancelled"]
    assert snapshot.messages == agent.context.messages


def test_request_assembly_keeps_logical_tool_context_and_metadata() -> None:
    tool_histories: list[list[str]] = []
    model_histories: list[list[str]] = []
    metadata = ExtraData(value="application phase")

    def execute(invocation: ToolInvocation) -> ToolResult:
        tool_histories.append([message.text for message in invocation.messages])
        return ToolResult(content="evidence")

    def prepare(_input: StepInput) -> PreparedStep:
        return PreparedStep(
            tools=[_tool(execute)],
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
        context=AgentContext(messages=[UserMessage(content="original task")]),
        prepare_step=prepare,
    )
    events: list[AgentEvent] = []
    run = agent.start(max_steps=1, on_event=events.append)
    result = run.result()
    assert run.wait_for_idle(2)
    assert model_histories == [["provider prompt"]]
    assert tool_histories == [["original task"]]
    assert result.output.metadata == metadata
    assert run.snapshot().messages[0].metadata == metadata
    assert messages_from_items(run.snapshot().items)[0].metadata is None
    starts = [event for event in events if event.type == "message_start"]
    assert len(starts) == 1 and starts[0].metadata == metadata
