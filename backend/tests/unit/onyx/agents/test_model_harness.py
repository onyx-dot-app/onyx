"""The normalized model adapter works without Onyx chat types."""

from collections.abc import Generator, Iterator

import pytest

from onyx.agents.events import AgentEvent
from onyx.agents.execution_records import RunStatus
from onyx.agents.models import PreparedStep
from onyx.agents.runtime import Agent, RunFailed
from onyx.agents.tools import AgentTool
from onyx.llm.cancellation import AgentCancelled, CancellationSignal
from onyx.llm.interfaces import GenerationContext
from onyx.llm.litellm_conversion import MessageAccumulator, recover_tool_calls
from onyx.llm.litellm_models import (
    ChatCompletionDeltaToolCall,
    Delta,
    FunctionCall,
    ModelResponseStream,
    StreamingChoice,
    ToolMessage,
)
from onyx.llm.models import (
    AssistantMessage,
    GenerationEvent,
    GenerationOptions,
    GenerationRequest,
    GenerationToolCallEvent,
    TextDeltaEvent,
    ToolChoiceOptions,
    ToolResult,
    ToolResultMessage,
    UserMessage,
)
from tests.unit.onyx.agents.fakes import FakeModelClient, ScriptedLLM


def tool() -> AgentTool:
    return AgentTool(
        name="echo",
        description="Echo",
        parameters={"type": "object"},
        execute=lambda invocation: ToolResult(
            content=str(invocation.arguments["value"])
        ),
    )


def test_model_and_agent_share_transcript_and_stream_events() -> None:
    llm = ScriptedLLM(
        [
            Delta(
                tool_calls=[
                    ChatCompletionDeltaToolCall(
                        index=0,
                        id="call",
                        function=FunctionCall(name="echo", arguments='{"value":3}'),
                    )
                ]
            ),
            Delta(content="done"),
        ]
    )
    agent = Agent(
        llm,
        tools=[tool()],
    )
    events: list[AgentEvent] = []
    run = agent.start(
        messages=[UserMessage(content="Echo 3")], max_steps=2, on_event=events.append
    )
    result = run.result()
    assert run.wait_for_idle(2)
    assert result.output.text == "done"
    assert isinstance(llm.requests[-1]["prompt"][-1], ToolMessage)
    assert llm.requests[-1]["prompt"][-1].content == "3"
    assert len([event for event in events if event.type == "message_update"]) >= 2
    assert len([event for event in events if event.type == "message_start"]) == 2
    assert len([event for event in events if event.type == "message_end"]) == 2
    assert all(
        event.generation_event.type not in {"start", "done", "error"}
        for event in events
        if event.type == "message_update"
    )


@pytest.mark.parametrize("cancelled", [False, True])
def test_partial_message_closes_before_run_completion(cancelled: bool) -> None:
    signal = CancellationSignal()

    class InterruptedModel(FakeModelClient):
        def stream(
            self, request: GenerationRequest, context: GenerationContext | None = None
        ) -> Generator[GenerationEvent, None, None]:
            assert not request.messages
            assert context is not None and context.cancellation is signal
            yield TextDeltaEvent(content_index=0, text="Partial output")
            if cancelled:
                signal.cancel()
                signal.check()
            raise ValueError("Provider disconnected")

    events: list[AgentEvent] = []
    run = Agent(InterruptedModel(lambda _request, _signal: AssistantMessage())).start(
        max_steps=1, cancellation=signal, on_event=events.append
    )
    with pytest.raises(AgentCancelled if cancelled else RunFailed):
        run.result()
    assert run.wait_for_idle(2)
    ends = [event for event in events if event.type == "message_end"]
    assert len(ends) == 1
    terminal = ends[0]
    assert terminal.status == (RunStatus.CANCELLED if cancelled else RunStatus.ERROR)
    saved_message = run.snapshot().messages[0]
    assert isinstance(saved_message, AssistantMessage)
    assert terminal.message.text == saved_message.text == "Partial output"
    assert terminal.message_id == saved_message.id
    assert events.index(terminal) < next(
        index for index, event in enumerate(events) if event.type == "agent_end"
    )


def test_tool_recovery_happens_before_events() -> None:
    llm = ScriptedLLM(
        [
            Delta(content='{"name":"echo","arguments":{"value":"recovered"}}'),
            Delta(content="done"),
        ]
    )
    agent = Agent(
        llm,
        tools=[tool()],
        options=GenerationOptions(tool_choice=ToolChoiceOptions.REQUIRED),
    )
    events: list[AgentEvent] = []
    run = agent.start(max_steps=2, on_event=events.append)
    run.result()
    assert run.wait_for_idle(2)
    response = agent.state.messages[1]
    assert isinstance(response, ToolResultMessage) and response.content == "recovered"
    first = next(
        event.generation_event for event in events if event.type == "message_update"
    )
    assert first is not None
    tool_event = next(
        event.generation_event
        for event in events
        if event.type == "message_update"
        and isinstance(event.generation_event, GenerationToolCallEvent)
    )
    assert isinstance(tool_event, GenerationToolCallEvent)
    assert tool_event.tool_call.id == response.tool_call_id


def test_native_calls_keep_precedence_and_missing_id_is_stable() -> None:
    def chunks() -> Iterator[ModelResponseStream]:
        for arguments in ['{"value":', "3}"]:
            yield ModelResponseStream(
                id="m",
                created="1",
                choice=StreamingChoice(
                    delta=Delta(
                        tool_calls=[
                            ChatCompletionDeltaToolCall(
                                index=0,
                                function=FunctionCall(
                                    name="echo" if arguments.startswith("{") else None,
                                    arguments=arguments,
                                ),
                            )
                        ]
                    )
                ),
            )

    accumulator = MessageAccumulator()
    events = list(
        accumulator.consume(
            chunks(), PreparedStep(tools=[tool()]).generation_request([])
        )
    )
    calls = [
        event.tool_call
        for event in events
        if isinstance(event, GenerationToolCallEvent)
    ]
    assert calls and calls[0].id
    assert {call.id for call in calls} == {calls[0].id}
    assert accumulator.finish().tool_calls[0].arguments == {"value": 3}


def test_model_honors_cancelled_signal() -> None:
    signal = CancellationSignal()
    signal.cancel()
    llm = ScriptedLLM([])

    with pytest.raises(AgentCancelled):
        Agent(llm).start(background=False, max_steps=1, cancellation=signal).result()
    assert not llm.requests


class TestToolRecovery:
    def context(
        self, choice: ToolChoiceOptions = ToolChoiceOptions.REQUIRED
    ) -> GenerationRequest:
        return PreparedStep(
            tools=[tool()], options=GenerationOptions(tool_choice=choice)
        ).generation_request([])

    def test_recovery_is_independent_across_generations(self) -> None:
        from onyx.llm.models import AssistantMessage, TextContent, ToolCall

        native = AssistantMessage(
            content=[ToolCall(id="native", name="echo", arguments={"value": 1})]
        )
        assert recover_tool_calls(native, self.context()) is native
        missing = AssistantMessage(content=[TextContent(text="no payload")])
        assert recover_tool_calls(missing, self.context()) is missing
        payload = AssistantMessage(
            content=[TextContent(text='{"name":"echo","arguments":{"value":3}}')]
        )
        assert recover_tool_calls(payload, self.context()).tool_calls[0].arguments == {
            "value": 3
        }

    def test_reasoning_fallback_and_required_text(self) -> None:
        from onyx.llm.models import AssistantMessage, TextContent, ThinkingContent

        for blocks in [
            [TextContent(text='{"name":"echo","arguments":{"value":3}}')],
            [
                ThinkingContent(text='{"name":"echo","arguments":{"value":3}}'),
                TextContent(text="Searching"),
            ],
        ]:
            result = recover_tool_calls(
                AssistantMessage(content=blocks), self.context()
            )
            assert result.tool_calls[0].arguments == {"value": 3}
            assert not result.text

    def test_auto_xml_and_disabled_tools(self) -> None:
        from onyx.llm.models import AssistantMessage, TextContent

        payload = AssistantMessage(
            content=[
                TextContent(
                    text='<function_calls><invoke name="echo"><parameter name="value">found</parameter></invoke></function_calls>'
                )
            ]
        )
        result = recover_tool_calls(payload, self.context(ToolChoiceOptions.AUTO))
        assert result.tool_calls[0].arguments == {"value": "found"}
        assert (
            recover_tool_calls(payload, self.context(ToolChoiceOptions.NONE)) is payload
        )
        prose = AssistantMessage(content=[TextContent(text="normal answer")])
        assert recover_tool_calls(prose, self.context(ToolChoiceOptions.AUTO)) is prose


def test_signed_thinking_survives_onyx_projection_and_details_serialize() -> None:
    from pydantic import BaseModel

    from onyx.llm.litellm_conversion import serialize_request
    from onyx.llm.models import AssistantMessage, ThinkingBlock, ThinkingContent

    block = ThinkingBlock(thinking="reasoning", signature="signature")
    message = AssistantMessage(
        content=[ThinkingContent(text="reasoning", blocks=[block])]
    )
    history = [message]
    from onyx.llm.litellm_models import AssistantMessage as WireAssistantMessage

    wire_message = serialize_request(
        GenerationRequest(messages=history), ScriptedLLM([]).config
    )[0]
    assert isinstance(wire_message, WireAssistantMessage)
    assert wire_message.thinking_blocks == [block]

    class Details(BaseModel):
        source: str

    result = ToolResult(content="summary", details=Details(source="document"))
    assert result.model_dump()["details"] == {"source": "document"}
