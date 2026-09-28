"""Streaming generation turns provider chunks into ordered shared events."""

import json
from collections.abc import Iterable, Iterator
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from pydantic import BaseModel, JsonValue

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
    to_assistant_message,
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
from onyx.tracing.framework.create import get_current_span


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


def test_stream_failure_recovers_no_call_from_an_unfinished_payload() -> None:
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
    # Text streams as it arrives; recovery runs only after a complete response.
    assert [event.type for event in events] == ["start", "text_delta", "error"]
    message = collect_generation(events)
    assert message.text == payload
    assert message.tool_calls == []
    assert record.call_args.kwargs["tool_calls"] is None


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


_XML_ANSWER = (
    'Anthropic uses <function_calls><invoke name="search"></invoke>'
    "</function_calls> blocks."
)


@pytest.mark.parametrize(
    "request_",
    [
        GenerationRequest(),
        GenerationRequest(
            tools=[ToolDefinition(name="search", description="Search", parameters={})],
            options=GenerationOptions(tool_choice=ToolChoiceOptions.NONE),
        ),
    ],
    ids=["no-tools", "tool-choice-none"],
)
def test_xml_text_is_kept_when_tool_recovery_is_off(
    request_: GenerationRequest,
) -> None:
    accumulator = MessageAccumulator(request_.tools)
    events = list(
        accumulator.consume(iter([_stream_chunk(Delta(content=_XML_ANSWER))]), request_)
    )

    assert collect_generation(events).text == _XML_ANSWER
    assert accumulator.message.tool_calls == []


@pytest.mark.parametrize("choice", [ToolChoiceOptions.AUTO, ToolChoiceOptions.REQUIRED])
def test_structured_answers_stream_before_the_provider_finishes(
    choice: ToolChoiceOptions,
) -> None:
    """A JSON-looking answer is not held back while tools are available."""
    request = GenerationRequest(
        tools=[ToolDefinition(name="search", description="Search", parameters={})],
        options=GenerationOptions(tool_choice=choice),
    )
    finished: list[bool] = []

    def chunks() -> Iterator[ModelResponseStream]:
        yield _stream_chunk(Delta(content='{"answer": '))
        yield _stream_chunk(Delta(content="42}"))
        finished.append(True)

    events = MessageAccumulator(request.tools).consume(chunks(), request)
    first = next(events)

    assert isinstance(first, TextDeltaEvent)
    assert first.text == '{"answer": '
    assert finished == []
    events.close()


def test_stream_keeps_its_span_out_of_the_caller_context() -> None:
    before = get_current_span()
    events = ScriptedLLM([Delta(content="hi")]).stream(
        GenerationRequest(messages=[UserMessage(content="Hello")])
    )
    next(events)  # start
    assert get_current_span() is before
    next(events)  # first text update
    events.close()

    assert get_current_span() is before


def test_streamed_thinking_fragments_merge_into_one_signed_block() -> None:
    """Anthropic streams thinking text first and its signature last."""
    accumulator = MessageAccumulator()
    events = [
        event
        for delta in [
            Delta(
                reasoning_content="I ",
                thinking_blocks=[ThinkingBlock(thinking="I ", signature="")],
            ),
            Delta(
                reasoning_content="think",
                thinking_blocks=[ThinkingBlock(thinking="think")],
            ),
            Delta(thinking_blocks=[ThinkingBlock(signature="sig-1")]),
            Delta(
                reasoning_content="again",
                thinking_blocks=[ThinkingBlock(thinking="again", signature="sig-2")],
            ),
        ]
        for event in accumulator.add(_stream_chunk(delta))
    ]

    expected = [
        ThinkingBlock(thinking="I think", signature="sig-1"),
        ThinkingBlock(thinking="again", signature="sig-2"),
    ]
    assert accumulator.message.thinking_blocks == expected
    assert collect_generation(events).thinking_blocks == expected


def test_tool_call_waits_for_name_and_preserves_early_arguments() -> None:
    accumulator = MessageAccumulator()
    assert (
        accumulator.add(
            _stream_chunk(
                Delta(
                    tool_calls=[
                        ChatCompletionDeltaToolCall(
                            index=0,
                            id="call",
                            function=ResponseFunctionCall(arguments='{"query":"ear'),
                        ),
                    ]
                )
            )
        )
        == []
    )
    assert accumulator.message.tool_calls == []
    text_events = accumulator.add(_stream_chunk(Delta(content="Searching")))
    events = accumulator.add(
        _stream_chunk(
            Delta(
                tool_calls=[
                    ChatCompletionDeltaToolCall(
                        index=0,
                        function=ResponseFunctionCall(name="search", arguments='ly"}'),
                    ),
                ]
            )
        )
    )
    events.extend(accumulator.end())
    result = collect_generation([*text_events, *events])
    assert result == accumulator.message
    assert result.tool_calls[0].id == "call"
    assert result.tool_calls[0].name == "search"
    assert result.tool_calls[0].arguments == {"query": "early"}
    assert all(
        event.tool_call.name
        for event in events
        if isinstance(event, GenerationToolCallEvent)
    )


def test_unnamed_tool_calls_never_enter_content_or_events() -> None:
    accumulator = MessageAccumulator()
    assert (
        accumulator.add(
            _stream_chunk(Delta(tool_calls=[ChatCompletionDeltaToolCall(index=0)]))
        )
        == []
    )
    with patch("onyx.llm.model_response.logger.warning") as warning:
        events = accumulator.end()
        accumulator.finalize()
    assert warning.call_count == 1
    assert [event.type for event in events] == ["done"]
    assert accumulator.message.tool_calls == []
    assert collect_generation(events).content == []


@pytest.mark.parametrize(
    "schema, encoded, expected",
    [
        ({"anyOf": [{"type": "array"}, {"type": "null"}]}, '["x"]', ["x"]),
        ({"type": ["array", "null"]}, '["x"]', ["x"]),
        ({"oneOf": [{"type": "object"}, {"type": "null"}]}, '{"x":1}', {"x": 1}),
        ({"anyOf": [{"type": "array"}, {"type": "string"}]}, '["x"]', '["x"]'),
        ({"type": ["object", "string"]}, '{"x":1}', '{"x":1}'),
        ({"type": ["array", "null"]}, '{"x":1}', '{"x":1}'),
    ],
)
@pytest.mark.parametrize("streaming", [False, True])
def test_optional_structured_tool_arguments(
    schema: dict[str, JsonValue], encoded: str, expected: JsonValue, streaming: bool
) -> None:
    request = GenerationRequest(
        tools=[
            ToolDefinition(
                name="search",
                description="Search",
                parameters={"properties": {"value": schema}},
            )
        ]
    )
    arguments = json.dumps({"value": encoded})
    if streaming:
        accumulator = MessageAccumulator(request.tools)
        events = accumulator.add(
            _stream_chunk(
                Delta(
                    tool_calls=[
                        ChatCompletionDeltaToolCall(
                            index=0,
                            id="call",
                            function=ResponseFunctionCall(
                                name="search", arguments=arguments
                            ),
                        )
                    ]
                )
            )
        )
        events.extend(accumulator.end())
        result = collect_generation(events)
    else:
        result = to_assistant_message(
            ModelResponse(
                id="test",
                created="1",
                choice=Choice(
                    message=ResponseMessage(
                        tool_calls=[
                            WireToolCall(
                                id="call",
                                function=ResponseFunctionCall(
                                    name="search", arguments=arguments
                                ),
                            )
                        ]
                    )
                ),
            ),
            request,
        )
    assert result.tool_calls[0].arguments == {"value": expected}


@pytest.mark.parametrize("chunk_count", [0, 3])
def test_empty_generation_logs_one_metadata_warning(chunk_count: int) -> None:
    client = ScriptedLLM([])
    chunks = [_stream_chunk(Delta()) for _ in range(chunk_count)]
    with (
        patch.object(client, "stream_raw", return_value=iter(chunks)),
        patch("onyx.llm.multi_llm.logger.warning") as warning,
    ):
        events = list(client.stream(GenerationRequest()))
    assert collect_generation(events).content == []
    warning.assert_called_once_with(
        "Empty generation: provider=%s model=%s stop_reason=%s chunks=%s",
        client.config.model_provider,
        client.config.model_name,
        None,
        chunk_count,
    )


@pytest.mark.parametrize("streaming", [False, True])
def test_unnamed_native_call_does_not_suppress_text_recovery(streaming: bool) -> None:
    payload = '{"name":"search","arguments":{"query":"onyx"}}'
    request = GenerationRequest(
        tools=[ToolDefinition(name="search", description="Search", parameters={})],
        options=GenerationOptions(tool_choice=ToolChoiceOptions.REQUIRED),
    )
    if streaming:
        accumulator = MessageAccumulator(request.tools)
        events = list(
            accumulator.consume(
                iter(
                    [
                        _stream_chunk(Delta(content=payload)),
                        _stream_chunk(
                            Delta(tool_calls=[ChatCompletionDeltaToolCall(index=0)])
                        ),
                    ]
                ),
                request,
            )
        )
        events.extend(accumulator.end())
        result = collect_generation(events)
    else:
        result = to_assistant_message(
            ModelResponse(
                id="test",
                created="1",
                choice=Choice(
                    message=ResponseMessage(
                        content=payload,
                        tool_calls=[
                            WireToolCall(
                                id="stray",
                                function=ResponseFunctionCall(arguments="{}"),
                            )
                        ],
                    )
                ),
            ),
            request,
        )
    assert result.text == payload
    assert [call.name for call in result.tool_calls] == ["search"]
    assert result.tool_calls[0].arguments == {"query": "onyx"}


def test_split_surrogate_pair_in_tool_arguments_streams_one_character() -> None:
    accumulator = MessageAccumulator()
    fragments = ['{"text": "hi \\ud83d', '\\ude00"}']
    events = [
        event
        for index, fragment in enumerate(fragments)
        for event in accumulator.add(
            _stream_chunk(
                Delta(
                    tool_calls=[
                        ChatCompletionDeltaToolCall(
                            index=0,
                            id="call" if index == 0 else None,
                            function=ResponseFunctionCall(
                                name="write" if index == 0 else None,
                                arguments=fragment,
                            ),
                        )
                    ]
                )
            )
        )
    ]
    events.extend(accumulator.end())

    texts = [
        event.argument_deltas.get("text", "")
        for event in events
        if isinstance(event, GenerationToolCallEvent)
    ]
    assert "".join(texts) == "hi 😀"
    assert all("\ud83d" not in text for text in texts)
    assert collect_generation(events).tool_calls[0].arguments == {"text": "hi 😀"}


def test_invalid_tool_arguments_stop_argument_deltas_and_keep_raw_text() -> None:
    accumulator = MessageAccumulator()
    # A raw newline inside a JSON string is invalid.
    fragments = ['{"code": "a', "\nb", 'c"}']
    events = [
        event
        for index, fragment in enumerate(fragments)
        for event in accumulator.add(
            _stream_chunk(
                Delta(
                    tool_calls=[
                        ChatCompletionDeltaToolCall(
                            index=0,
                            id="call" if index == 0 else None,
                            function=ResponseFunctionCall(
                                name="python" if index == 0 else None,
                                arguments=fragment,
                            ),
                        )
                    ]
                )
            )
        )
    ]
    accumulator.end()

    deltas = [
        event.argument_deltas
        for event in events
        if isinstance(event, GenerationToolCallEvent)
    ]
    call = accumulator.message.tool_calls[0]
    assert deltas == [{}, {"code": "a"}, {}, {}]
    assert call.raw_arguments == "".join(fragments)
    assert call.argument_error is not None
