"""Streaming generation turns provider chunks into ordered shared events."""

import json
from collections.abc import Iterable, Iterator
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from pydantic import BaseModel

from onyx.configs.chat_configs import LLM_SOCKET_READ_TIMEOUT
from onyx.llm.interfaces import GenerationContext, LLMConfig
from onyx.llm.model_request import ChatCompletionMessage
from onyx.llm.model_response import (
    ChatCompletionDeltaToolCall,
    Choice,
    Delta,
    MessageAccumulator,
    ModelResponse,
    ModelResponseStream,
    ResponseFunctionCall,
    StreamingChoice,
    recover_tool_calls,
)
from onyx.llm.model_response import ChatCompletionMessageToolCall as WireToolCall
from onyx.llm.model_response import Message as ResponseMessage
from onyx.llm.models import (
    AssistantMessage,
    GenerationDoneEvent,
    GenerationErrorEvent,
    GenerationEvent,
    GenerationLifecycleEvent,
    GenerationOptions,
    GenerationRequest,
    GenerationRequestParams,
    GenerationStartEvent,
    GenerationTextEvent,
    GenerationToolCallEvent,
    ReasoningEffort,
    TextContent,
    TextDeltaEvent,
    ThinkingBlock,
    ThinkingDeltaEvent,
    ToolCallEndEvent,
    ToolChoiceOptions,
    ToolDefinition,
    Usage,
    UserMessage,
    apply_generation_event,
)
from onyx.llm.multi_llm import LitellmLLM
from onyx.tracing.flows import LLMFlow


class ScriptedLLM(LitellmLLM):
    """Streams one scripted provider delta per stream_raw call."""

    def __init__(self, steps: list[Delta]) -> None:
        self.steps = iter(steps)
        self.requests: list[dict[str, Any]] = []

    @property
    def config(self) -> LLMConfig:
        return LLMConfig(
            model_provider="openai",
            model_name="test-model",
            max_input_tokens=4096,
            temperature=0,
        )

    def stream_raw(
        self, prompt: list[ChatCompletionMessage], *args: Any, **kwargs: Any
    ) -> Iterator[ModelResponseStream]:
        assert not args
        self.requests.append({"prompt": prompt, **kwargs})
        yield ModelResponseStream(
            id="test", created="1", choice=StreamingChoice(delta=next(self.steps))
        )


def collect_generation(events: Iterable[GenerationEvent]) -> AssistantMessage:
    message = AssistantMessage()
    for event in events:
        apply_generation_event(message, event)
    return message


def test_accumulator_keeps_interleaved_calls_and_signed_thinking_separate() -> None:
    accumulator = MessageAccumulator()
    signed = ThinkingBlock(thinking="plan", signature="signed")
    accumulator.add(
        ModelResponseStream(
            id="response",
            created="0",
            choice=StreamingChoice(
                delta=Delta(reasoning_content="plan", thinking_blocks=[signed])
            ),
        )
    )
    for call in [
        ChatCompletionDeltaToolCall(
            index=0,
            id="first",
            function=ResponseFunctionCall(name="search", arguments='{"query":"fir'),
        ),
        ChatCompletionDeltaToolCall(
            index=1,
            id="second",
            function=ResponseFunctionCall(
                name="search", arguments='{"query":"second"}'
            ),
        ),
        ChatCompletionDeltaToolCall(
            index=0, function=ResponseFunctionCall(arguments='st"}')
        ),
        ChatCompletionDeltaToolCall(
            index=2,
            id="invalid",
            function=ResponseFunctionCall(name="search", arguments='{"query":broken'),
        ),
    ]:
        accumulator.add(
            ModelResponseStream(
                id="response",
                created="0",
                choice=StreamingChoice(delta=Delta(tool_calls=[call])),
            )
        )
    assert all(not call.arguments_complete for call in accumulator.message.tool_calls)
    events = accumulator.end()
    terminal = events[-1]
    assert isinstance(terminal, GenerationDoneEvent)
    message = accumulator.message
    assert message.thinking_blocks == [signed]
    assert [(call.id, call.arguments) for call in message.tool_calls] == [
        ("first", {"query": "first"}),
        ("second", {"query": "second"}),
        ("invalid", {}),
    ]
    assert message.tool_calls[-1].argument_error is not None
    assert [call.raw_arguments for call in message.tool_calls] == [
        None,
        None,
        '{"query":broken',
    ]
    assert [call.arguments_complete for call in message.tool_calls] == [
        True,
        True,
        False,
    ]
    assert [
        event.content_index for event in events if isinstance(event, ToolCallEndEvent)
    ] == [1, 2, 3]


def test_text_deltas_preserve_content_boundaries_without_boundary_events() -> None:
    accumulator = MessageAccumulator()
    deltas = [
        Delta(reasoning_content="plan"),
        Delta(content="first"),
        Delta(content=" part"),
        Delta(reasoning_content="reconsider"),
        Delta(
            tool_calls=[
                ChatCompletionDeltaToolCall(
                    index=0,
                    id="call",
                    function=ResponseFunctionCall(name="search", arguments="{}"),
                )
            ]
        ),
        Delta(content="last"),
    ]
    events = [
        event for delta in deltas for event in accumulator.add(_stream_chunk(delta))
    ]
    text_events = [event for event in events if isinstance(event, GenerationTextEvent)]
    assert [(event.content_index, event.text) for event in text_events] == [
        (0, "plan"),
        (1, "first"),
        (1, " part"),
        (2, "reconsider"),
        (4, "last"),
    ]
    assert text_events[1].text == "first"
    terminal = accumulator.end()[-1]
    assert isinstance(terminal, GenerationDoneEvent)
    assert accumulator.message.text == "first partlast"


class StructuredToolArguments(BaseModel):
    queries: list[str]
    filters: dict[str, str]
    literal: str


@pytest.mark.parametrize("streaming", [False, True])
@pytest.mark.parametrize("text_fallback", [False, True])
def test_shared_client_normalizes_schema_directed_tool_arguments(
    streaming: bool, text_fallback: bool
) -> None:
    arguments = {
        "queries": '["first", "second"]',
        "filters": '{"source": "docs"}',
        "literal": '["keep this as text"]',
    }
    encoded = json.dumps(json.dumps(arguments))
    payload = json.dumps({"name": "search", "arguments": arguments})
    delta = (
        Delta(content=payload)
        if text_fallback
        else Delta(
            tool_calls=[
                ChatCompletionDeltaToolCall(
                    index=0,
                    id="search-call",
                    function=ResponseFunctionCall(name="search", arguments=encoded),
                )
            ]
        )
    )
    transport = ScriptedLLM([delta])
    client = transport
    request = GenerationRequest(
        messages=[UserMessage(content="Search")],
        tools=[
            ToolDefinition(
                name="search",
                description="Search sources",
                parameters=StructuredToolArguments.model_json_schema(),
            )
        ],
        options=GenerationOptions(tool_choice=ToolChoiceOptions.REQUIRED),
    )
    response = ModelResponse(
        id="test",
        created="1",
        choice=Choice(
            message=ResponseMessage(
                content=delta.content,
                tool_calls=[
                    WireToolCall(
                        id="search-call",
                        function=ResponseFunctionCall(name="search", arguments=encoded),
                    )
                ]
                if not text_fallback
                else None,
            )
        ),
    )
    with patch.object(transport, "invoke_raw", return_value=response):
        if streaming:
            events = list(client.stream(request))
            terminal = events[-1]
            assert isinstance(terminal, GenerationDoneEvent)
            message = collect_generation(events)
            ends = [event for event in events if isinstance(event, ToolCallEndEvent)]
            assert len(ends) == 1
            assert ends[0].tool_call == message.tool_calls[0]
        else:
            message = client.invoke(request)
    call = message.tool_calls[0]
    assert call.arguments_complete
    assert call.argument_error is None
    parsed = StructuredToolArguments.model_validate(call.arguments)
    assert parsed.queries == ["first", "second"]
    assert parsed.filters == {"source": "docs"}
    assert parsed.literal == arguments["literal"]


@pytest.mark.parametrize("streaming", [False, True])
@pytest.mark.parametrize("prefix", ["Before ", ""])
def test_xml_tool_recovery_preserves_visible_prose(
    streaming: bool, prefix: str
) -> None:
    fragments = [
        prefix,
        '<function_calls><invoke name="search">',
        '<parameter name="queries" string="false">["Onyx"]</parameter>',
        "</invoke></function_calls>",
        "  ",
        "\nAfter",
    ]
    request = GenerationRequest(
        tools=[ToolDefinition(name="search", description="Search", parameters={})],
    )
    if streaming:
        source = iter(
            ModelResponseStream(
                id="response",
                created="1",
                choice=StreamingChoice(delta=Delta(content=fragment)),
            )
            for fragment in fragments
        )
        accumulator = MessageAccumulator(request.tools)
        list(accumulator.consume(source, request))
        accumulator.finalize()
        message = accumulator.message
    else:
        message = recover_tool_calls(
            AssistantMessage(content=[TextContent(text="".join(fragments))]), request
        )
    assert message.text == prefix + "\nAfter"
    assert len(message.tool_calls) == 1
    assert message.tool_calls[0].name == "search"
    assert message.tool_calls[0].arguments == {"queries": ["Onyx"]}


def _stream_chunk(delta: Delta, *, usage: Usage | None = None) -> ModelResponseStream:
    return ModelResponseStream(
        id="response", created="1", choice=StreamingChoice(delta=delta), usage=usage
    )


def test_stream_keeps_native_precedence_stable_ids_and_event_snapshots() -> None:
    fallback = '{"name":"search","arguments":{"query":"fallback"}}'
    request = GenerationRequest(
        tools=[ToolDefinition(name="search", description="Search", parameters={})],
        options=GenerationOptions(tool_choice=ToolChoiceOptions.REQUIRED),
    )
    chunks = [
        _stream_chunk(Delta(content=fallback)),
        _stream_chunk(
            Delta(
                tool_calls=[
                    ChatCompletionDeltaToolCall(
                        index=0,
                        function=ResponseFunctionCall(
                            name="search", arguments='{"query":"fir'
                        ),
                    )
                ]
            )
        ),
        _stream_chunk(
            Delta(
                tool_calls=[
                    ChatCompletionDeltaToolCall(
                        index=0,
                        id="late-provider-id",
                        function=ResponseFunctionCall(arguments='st"}'),
                    )
                ]
            )
        ),
    ]
    client = ScriptedLLM([])
    with patch.object(client, "stream_raw", return_value=iter(chunks)):
        events = list(client.stream(request))
    assert [event.type for event in events] == [
        "start",
        "text_delta",
        "tool_call_start",
        "tool_call_delta",
        "tool_call_delta",
        "tool_call_end",
        "done",
    ]
    calls = [
        event.tool_call
        for event in events
        if isinstance(event, GenerationToolCallEvent)
    ]
    assert len({call.id for call in calls}) == 1
    assert calls[0].id and calls[0].arguments == {}
    assert calls[1].arguments == {"query": "fir"}
    assert calls[-1].arguments == {"query": "first"}
    start, delta, terminal = events[0], events[1], events[-1]
    assert isinstance(start, GenerationLifecycleEvent)
    assert start.type == "start"
    assert isinstance(delta, TextDeltaEvent)
    assert delta.text == fallback
    assert isinstance(terminal, GenerationDoneEvent)
    assert collect_generation(events).text == fallback
    assert len(collect_generation(events).tool_calls) == 1
    assert chunks[1].choice.delta.tool_calls[0].id is None
    assert chunks[2].choice.delta.tool_calls[0].id == "late-provider-id"


@pytest.mark.parametrize("ending", ["complete", "close", "error"])
def test_stream_conversion_closes_provider_source(ending: str) -> None:
    closed: list[bool] = []
    failure = RuntimeError("provider failed")

    def chunks() -> Iterator[ModelResponseStream]:
        try:
            yield _stream_chunk(Delta(content="visible"))
            if ending == "error":
                raise failure
            yield _stream_chunk(Delta(content=" tail"))
        finally:
            closed.append(True)

    accumulator = MessageAccumulator()
    stream = accumulator.consume(chunks(), GenerationRequest())
    if ending == "close":
        next(stream)
        stream.close()
    elif ending == "error":
        with pytest.raises(RuntimeError) as caught:
            list(stream)
        assert caught.value is failure
    else:
        list(stream)
        accumulator.finalize()
        assert accumulator.message.text == "visible tail"
    assert closed == [True]


@pytest.mark.parametrize("reasoning", [False, True])
def test_buffered_recovery_preserves_content_and_emits_one_call_with_usage(
    reasoning: bool,
) -> None:
    payload = '{"name":"search","arguments":{"query":"recovered"}}'
    usage = Usage(
        prompt_tokens=4,
        completion_tokens=5,
        total_tokens=9,
        cache_creation_input_tokens=0,
        cache_read_input_tokens=0,
    )
    request = GenerationRequest(
        tools=[ToolDefinition(name="search", description="Search", parameters={})],
        options=GenerationOptions(tool_choice=ToolChoiceOptions.REQUIRED),
    )
    signed = ThinkingBlock(thinking=payload, signature="provider-signature")
    closed: list[bool] = []

    def chunks() -> Iterator[ModelResponseStream]:
        try:
            for fragment in [payload[:15], payload[15:]]:
                yield _stream_chunk(
                    Delta(reasoning_content=fragment)
                    if reasoning
                    else Delta(content=fragment)
                )
            yield _stream_chunk(Delta(thinking_blocks=[signed]))
            yield ModelResponseStream(
                id="response",
                created="1",
                choice=StreamingChoice(finish_reason="stop", delta=Delta()),
                usage=usage,
            )
        finally:
            closed.append(True)

    client = ScriptedLLM([])
    with patch.object(client, "stream_raw", return_value=chunks()):
        events = list(client.stream(request))
    assert closed == [True]
    assert [
        event.type for event in events if not isinstance(event, GenerationTextEvent)
    ] == ["start", "tool_call_start", "tool_call_delta", "tool_call_end", "done"]
    calls = [
        event.tool_call
        for event in events
        if isinstance(event, GenerationToolCallEvent)
    ]
    assert len({call.id for call in calls}) == 1
    assert calls[-1].arguments == {"query": "recovered"}
    terminal = events[-1]
    assert isinstance(terminal, GenerationDoneEvent)
    final = collect_generation(events)
    assert final.thinking_blocks == [signed]
    assert final.usage == usage
    assert final.stop_reason == "stop"
    assert final.tool_calls == [calls[-1]]
    assert final.text == ("" if reasoning else payload)
    assert final.thinking == (payload if reasoning else "")


def test_buffered_stream_failure_keeps_unresolved_tool_payload_out_of_events() -> None:
    payload = '{"name":"search","arguments":{"query":"unfinished'
    failure = RuntimeError("provider failed")
    closed: list[bool] = []

    def chunks() -> Iterator[ModelResponseStream]:
        try:
            yield _stream_chunk(Delta(content=payload))
            raise failure
        finally:
            closed.append(True)

    request = GenerationRequest(
        tools=[ToolDefinition(name="search", description="Search", parameters={})],
        options=GenerationOptions(tool_choice=ToolChoiceOptions.REQUIRED),
    )
    client = ScriptedLLM([])
    events: list[GenerationEvent] = []
    with (
        patch.object(client, "stream_raw", return_value=chunks()),
        patch("onyx.llm.multi_llm.record_llm_span_output") as record,
        pytest.raises(RuntimeError) as caught,
    ):
        events.extend(client.stream(request))
    assert caught.value is failure
    assert closed == [True]
    assert [event.type for event in events] == ["start", "error"]
    assert collect_generation(events).content == []
    assert payload not in str(record.call_args)


def test_incremental_events_preserve_partial_content_and_snapshot_isolation() -> None:
    accumulator = MessageAccumulator()
    accepted = AssistantMessage()
    saved = None
    chunks = [
        Delta(content="first"),
        Delta(content=" second"),
        Delta(
            reasoning_content="plan",
            thinking_blocks=[ThinkingBlock(thinking="plan", signature="signed")],
        ),
        Delta(
            tool_calls=[
                ChatCompletionDeltaToolCall(
                    index=0,
                    id="call",
                    function=ResponseFunctionCall(
                        name="search", arguments='{"query":"par'
                    ),
                )
            ]
        ),
        Delta(
            tool_calls=[
                ChatCompletionDeltaToolCall(
                    index=0, function=ResponseFunctionCall(arguments='tial","limit":3}')
                )
            ]
        ),
    ]
    for index, chunk in enumerate(chunks):
        for event in accumulator.add(_stream_chunk(chunk)):
            apply_generation_event(accepted, event)
            # Event consumers cannot change already accepted tool or reasoning data.
            if isinstance(event, GenerationToolCallEvent):
                event.tool_call.arguments.clear()
            elif isinstance(event, ThinkingDeltaEvent) and event.blocks:
                event.blocks.clear()
        assert accepted.content == accumulator.message.content
        if index == 0:
            saved = accepted.model_copy(deep=True)
    assert saved is not None and saved.text == "first"
    assert accepted.text == "first second"
    assert accepted.thinking_blocks == [
        ThinkingBlock(thinking="plan", signature="signed")
    ]
    assert accepted.tool_calls[0].arguments == {"query": "partial", "limit": 3}
    assert not accepted.tool_calls[0].arguments_complete
    for event in accumulator.end():
        apply_generation_event(accepted, event)
        if isinstance(event, GenerationToolCallEvent):
            event.tool_call.arguments.clear()
    assert accepted.content == accumulator.message.content
    assert accepted.tool_calls[0].arguments_complete


def test_text_update_payload_does_not_grow_with_accumulated_output() -> None:
    accumulator = MessageAccumulator()
    accumulator.add(_stream_chunk(Delta(content="x" * 100_000)))
    updates = [
        accumulator.add(_stream_chunk(Delta(content="next")))[0] for _ in range(10)
    ]
    assert len({event.model_dump_json() for event in updates}) == 1
    assert len(updates[0].model_dump_json()) < 200
    assert accumulator.message.text == "x" * 100_000 + "next" * 10


@pytest.mark.parametrize("failed", [False, True])
def test_terminal_events_preserve_content_without_copying_it(failed: bool) -> None:
    accumulator = MessageAccumulator()
    accepted = AssistantMessage()
    for event in accumulator.add(_stream_chunk(Delta(content="x" * 100_000))):
        apply_generation_event(accepted, event)
    content = accepted.content
    block = content[0]
    terminal = (
        GenerationErrorEvent(error_message="Generation failed")
        if failed
        else accumulator.end()[-1]
    )
    apply_generation_event(accepted, terminal)
    assert accepted.content is content
    assert accepted.content[0] is block
    assert accepted.text == "x" * 100_000
    assert len(terminal.model_dump_json()) < 200


class _ParamsLLM(ScriptedLLM):
    """Records request params on the operation, as _completion does."""

    def stream_raw(
        self, prompt: list[ChatCompletionMessage], *args: Any, **kwargs: Any
    ) -> Iterator[ModelResponseStream]:
        kwargs["operation"].request_params = GenerationRequestParams(
            model_name="test-model",
            model_provider="openai",
            reasoning_effort=ReasoningEffort.AUTO,
            max_tokens=None,
            sent_kwargs={},
        )
        yield from super().stream_raw(prompt, *args, **kwargs)


def test_stream_defaults_stall_timeout_omits_empty_tools_and_tags_its_span() -> None:
    llm = ScriptedLLM([Delta(content="hi"), Delta(content="hi")])
    request = GenerationRequest(messages=[UserMessage(content="Hello")])

    with patch("onyx.llm.multi_llm.llm_generation_span") as span:
        list(llm.stream(request))
        list(llm.stream(request, GenerationContext(flow=LLMFlow.CHAT_RESPONSE)))

    assert llm.requests[0]["stall_timeout_s"] == LLM_SOCKET_READ_TIMEOUT
    assert llm.requests[0]["tools"] is None
    flows = [call.args[1] for call in span.call_args_list]
    assert flows == [LLMFlow.UNTAGGED_STREAM, LLMFlow.CHAT_RESPONSE]


def test_stream_attaches_request_params_to_first_update_and_done() -> None:
    events = list(
        _ParamsLLM([Delta(content="hi")]).stream(
            GenerationRequest(messages=[UserMessage(content="Hello")])
        )
    )

    assert isinstance(events[0], GenerationStartEvent)
    assert events[0].request_params is None
    assert isinstance(events[1], TextDeltaEvent)
    assert events[1].request_params is not None
    assert isinstance(events[-1], GenerationDoneEvent)
    assert events[-1].request_params == events[1].request_params
    assert collect_generation(events).text == "hi"


def test_stream_failure_emits_error_event_and_marks_its_span() -> None:
    def failing_stream(*_args: Any, **_kwargs: Any) -> Iterator[ModelResponseStream]:
        yield _stream_chunk(Delta(content="partial"))
        raise TimeoutError("provider stalled")

    llm = ScriptedLLM([])
    span = MagicMock()
    events: list[GenerationEvent] = []
    with (
        patch("onyx.llm.multi_llm.llm_generation_span") as open_span,
        patch("onyx.llm.multi_llm.record_llm_span_output") as record,
        patch.object(llm, "stream_raw", side_effect=failing_stream),
        pytest.raises(TimeoutError),
    ):
        open_span.return_value.__enter__.return_value = span
        events.extend(
            llm.stream(GenerationRequest(messages=[UserMessage(content="Hello")]))
        )

    error = events[-1]
    assert isinstance(error, GenerationErrorEvent)
    message = collect_generation(events)
    assert message.text == "partial"
    assert message.stop_reason == "error"
    assert message.error_message == "Generation failed"
    span.set_error.assert_called_once_with(
        {"message": "TimeoutError: provider stalled", "data": None}
    )
    assert record.call_args.kwargs["output"] == "partial"


def test_stream_records_partial_output_when_the_consumer_stops_early() -> None:
    llm = ScriptedLLM([Delta(content="partial")])
    with (
        patch("onyx.llm.multi_llm.llm_generation_span"),
        patch("onyx.llm.multi_llm.record_llm_span_output") as record,
    ):
        events = llm.stream(GenerationRequest(messages=[UserMessage(content="Hi")]))
        next(events)  # start
        next(events)  # first text update
        events.close()

    record.assert_called_once()
    assert record.call_args.kwargs["output"] == "partial"
