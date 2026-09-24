"""The normalized model adapter works without Onyx chat types."""

import json
from collections.abc import Iterator

import pytest

from onyx.agents.events import AgentEvent
from onyx.agents.models import PreparedStep
from onyx.agents.runtime import Agent
from onyx.agents.tools import AgentTool
from onyx.llm.cancellation import CancellationSignal
from onyx.llm.litellm_conversion import normalized_stream, recover_tool_calls
from onyx.llm.litellm_models import (
    ChatCompletionDeltaToolCall,
    Delta,
    FunctionCall,
    ModelResponseStream,
    StreamingChoice,
    ToolMessage,
)
from onyx.llm.models import (
    GenerationOptions,
    GenerationRequest,
    GenerationToolCallEvent,
    ToolChoiceOptions,
    ToolResult,
    ToolResultMessage,
    UserMessage,
)
from tests.unit.onyx.agents.fakes import ScriptedLLM


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
    response = agent.context.messages[1]
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

    result = list(
        normalized_stream(chunks(), PreparedStep(tools=[tool()]).generation_request([]))
    )
    first, second = [chunk.choice.delta.tool_calls[0] for chunk in result]
    assert first.id and first.id == second.id
    assert first.function and second.function
    assert json.loads(
        (first.function.arguments or "") + (second.function.arguments or "")
    ) == {"value": 3}


def test_model_honors_cancelled_signal() -> None:
    signal = CancellationSignal()
    signal.cancel()
    llm = ScriptedLLM([])

    from onyx.llm.cancellation import AgentCancelled

    with pytest.raises(AgentCancelled):
        Agent(llm).execute(max_steps=1, cancellation=signal).result()
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
        GenerationRequest(messages=history), ScriptedLLM([]).transport.config
    )[0]
    assert isinstance(wire_message, WireAssistantMessage)
    assert wire_message.thinking_blocks == [block]

    class Details(BaseModel):
        source: str

    result = ToolResult(content="summary", details=Details(source="document"))
    assert result.model_dump()["details"] == {"source": "document"}
