"""Runtime ownership across hooks, observation, snapshots, and lazy resources."""

import base64
import threading
from concurrent.futures import ThreadPoolExecutor

import pytest
from pydantic import BaseModel, JsonValue

from onyx.agents.events import (
    AgentEvent,
    MessageEndEvent,
    MessageUpdateEvent,
    TurnEndEvent,
)
from onyx.agents.runtime import Agent, AgentContext, AgentHooks, TurnResult
from onyx.agents.tools import AgentTool, ToolUpdate
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


def _tool() -> AgentTool:
    return AgentTool(
        name="lookup",
        description="",
        parameters={},
        execute=lambda *_: ToolResult(content="original", details=ExtraData()),
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
def test_after_turn_changes_have_one_commit_point(replace: bool) -> None:
    requests: list[list[Message]] = []

    def model(
        context: GenerationRequest, _signal: CancellationSignal | None
    ) -> AssistantMessage:
        requests.append(context.messages)
        return _model(context)

    def after_turn(turn: TurnResult) -> None:
        if turn.tool_results:
            if replace:
                turn.tool_results[0] = turn.tool_results[0].model_copy(
                    update={"content": "accepted"}
                )
            else:
                turn.tool_results[0].content = "accepted"

    agent = Agent(
        FakeModelClient(model),
        context=AgentContext(tools=[_tool()]),
        hooks=AgentHooks(after_turn=after_turn),
    )
    result = agent.run(max_turns=2)
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
    assert "private metadata" not in snapshot.model_dump_json()


def test_after_turn_cannot_rewrite_executed_calls() -> None:
    def rewrite(turn: TurnResult) -> None:
        turn.message.content = []

    agent = Agent(
        FakeModelClient(_model),
        context=AgentContext(tools=[_tool()]),
        hooks=AgentHooks(after_turn=rewrite),
    )
    with pytest.raises(ValueError, match="executed tool calls"):
        agent.run(max_turns=1)
    snapshot = agent.snapshot()
    assert snapshot is not None and snapshot.status == "error"
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
    expected = baseline.run(max_turns=2)
    agent = Agent(FakeModelClient(_model), context=AgentContext(tools=[_tool()]))
    observed: list[AgentEvent] = []
    agent.subscribe(corrupt)
    agent.subscribe(observed.append)
    actual = agent.run(max_turns=2)
    assert actual == expected
    assert agent.snapshot() == baseline.snapshot()
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

    def execute(
        call_id: str,
        _arguments: dict[str, JsonValue],
        _signal: CancellationSignal,
        _update: ToolUpdate,
    ) -> ToolResult:
        if call_id == "first":
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
        agent.run(max_turns=1, cancellation=signal)
    snapshot = agent.snapshot()
    assert snapshot is not None and snapshot.status == "cancelled"
    assert len(snapshot.messages) == 3
    assert (
        snapshot.messages[1].text == snapshots[0].messages[1].text == "completed result"
    )
    assert (
        isinstance(snapshot.messages[2], ToolResultMessage)
        and snapshot.messages[2].is_error
    )
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
        transform_context=lambda context, _turn: context.model_copy(
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
    agent.run(max_turns=1)
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


def test_after_turn_cannot_change_published_text() -> None:
    def rewrite(turn: TurnResult) -> None:
        turn.message.content = [TextContent(text="replacement")]

    agent = Agent(
        FakeModelClient(
            lambda *_: AssistantMessage(content=[TextContent(text="published")])
        ),
        hooks=AgentHooks(after_turn=rewrite),
    )
    with pytest.raises(ValueError, match="published assistant"):
        agent.run(max_turns=1)
    assert agent.output_messages[0].text == "published"


def test_observer_failures_do_not_change_agent_or_model_output() -> None:
    def observer(event: AgentEvent) -> None:
        if isinstance(event, (MessageUpdateEvent, MessageEndEvent, TurnEndEvent)):
            event.message.content.clear()
        raise ValueError("observer failed")

    agent = Agent(
        FakeModelClient(
            lambda *_: AssistantMessage(content=[TextContent(text="answer")])
        )
    )
    agent.subscribe(observer)
    assert agent.run(max_turns=1).output.text == "answer"
    snapshot = agent.snapshot()
    assert snapshot is not None and snapshot.status == "complete"


def test_cancelled_run_cannot_deliver_result_into_next_run(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pending = threading.Event()
    release = threading.Event()
    workers: list[threading.Thread] = []
    original = Agent._emit

    def delayed(self: Agent, event: AgentEvent) -> None:
        if event.type == "tool_end" and not pending.is_set():
            event.result.content = "stale"
            workers.append(threading.current_thread())
            pending.set()
            assert release.wait(5)
        original(self, event)

    monkeypatch.setattr(Agent, "_emit", delayed)
    agent = Agent(
        FakeModelClient(
            lambda *_: AssistantMessage(
                content=[
                    ToolCall(id="c", name="lookup", arguments={}),
                    ToolCall(id="d", name="lookup", arguments={}),
                ]
            )
        ),
        context=AgentContext(tools=[_tool()]),
    )
    signal = CancellationSignal()
    with ThreadPoolExecutor(max_workers=1) as executor:
        old = executor.submit(agent.run, max_turns=1, cancellation=signal)
        assert pending.wait(5)
        signal.cancel()
        with pytest.raises(AgentCancelled):
            old.result(timeout=5)
        before = agent.snapshot()
        agent.model = FakeModelClient(
            lambda *_: AssistantMessage(
                content=[
                    TextContent(text="new"),
                    ToolCall(id="c", name="lookup", arguments={}),
                ]
            )
        )
        assert agent.run(max_turns=1).output.text == "new"
        release.set()
        for worker in workers:
            worker.join(timeout=5)
            assert not worker.is_alive()
        assert [message.text for message in agent.output_messages] == [
            "new",
            "original",
        ]
        assert before is not None and before.status == "cancelled"


@pytest.mark.parametrize("accepted", [False, True])
def test_tool_side_effect_cancellation_cutoff(accepted: bool) -> None:
    signal = CancellationSignal()
    writes: list[str] = []

    def execute(
        _call_id: str,
        _arguments: dict[str, JsonValue],
        _signal: CancellationSignal,
        _update: ToolUpdate,
    ) -> ToolResult:
        writes.append("saved")
        if not accepted:
            signal.cancel()
        return ToolResult(content="saved", details=ExtraData())

    tool = _tool().model_copy(update={"execute": execute})
    agent = Agent(FakeModelClient(_model), context=AgentContext(tools=[tool]))

    def stop(event: AgentEvent) -> None:
        if event.type == "tool_end":
            signal.cancel()

    agent.subscribe(stop)
    with pytest.raises(AgentCancelled):
        agent.run(max_turns=1, cancellation=signal)
    snapshot = agent.snapshot()
    assert snapshot is not None
    result = snapshot.messages[-1]
    assert isinstance(result, ToolResultMessage)
    assert writes == ["saved"]
    assert result.is_error is not accepted
    if accepted:
        assert result.text == "saved"
        assert isinstance(agent.output_messages[-1], ToolResultMessage)
    else:
        assert "External effects may have occurred" in result.text


@pytest.mark.parametrize("terminal", [False, True])
def test_agent_observer_cancellation_propagates(terminal: bool) -> None:
    def cancel(event: AgentEvent) -> None:
        if event.type == ("agent_end" if terminal else "message_end"):
            raise AgentCancelled()

    agent = Agent(
        FakeModelClient(
            lambda *_: AssistantMessage(content=[TextContent(text="answer")])
        )
    )
    agent.subscribe(cancel)
    with pytest.raises(AgentCancelled):
        agent.run(max_turns=1)
    snapshot = agent.snapshot()
    assert snapshot is not None and snapshot.status == "cancelled"
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
        agent.run(max_turns=1, cancellation=signal)
    assert seen[-1] == agent.output_messages[0].text == "answer"


def test_tool_completion_waits_for_accepted_progress_publication(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    update_entered = threading.Event()
    release_update = threading.Event()
    return_tool = threading.Event()
    tool_returned = threading.Event()
    tool_ended = threading.Event()
    seen: list[str] = []
    original_emit = Agent._emit

    def emit(self: Agent, event: AgentEvent) -> None:
        if event.type == "tool_update":
            update_entered.set()
            assert release_update.wait(5)
        original_emit(self, event)

    monkeypatch.setattr(Agent, "_emit", emit)
    with ThreadPoolExecutor(max_workers=2) as workers:

        def execute(
            _call_id: str,
            _arguments: dict[str, JsonValue],
            _signal: CancellationSignal,
            update: ToolUpdate,
        ) -> ToolResult:
            workers.submit(update, ToolResult(content="progress"))
            assert return_tool.wait(5)
            tool_returned.set()
            return ToolResult(content="finished")

        agent = Agent(
            FakeModelClient(_model),
            context=AgentContext(
                tools=[_tool().model_copy(update={"execute": execute})]
            ),
        )

        def observe(event: AgentEvent) -> None:
            if event.type in {"tool_update", "tool_end"}:
                seen.append(event.type)
            if event.type == "tool_end":
                tool_ended.set()

        agent.subscribe(observe)
        future = workers.submit(agent.run, max_turns=1)
        try:
            assert update_entered.wait(5)
            return_tool.set()
            assert tool_returned.wait(5)
            assert not tool_ended.wait(0.1)
        finally:
            release_update.set()
            return_tool.set()
        future.result(timeout=5)
    assert seen == ["tool_update", "tool_end"]
