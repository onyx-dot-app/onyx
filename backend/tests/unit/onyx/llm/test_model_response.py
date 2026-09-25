import json
from collections.abc import Iterator
from unittest.mock import patch

import pytest
from litellm.exceptions import APIConnectionError, InternalServerError
from litellm.types.utils import ModelResponse as LiteLLMModelResponse
from litellm.types.utils import ModelResponseStream as LiteLLMModelResponseStream
from pydantic import BaseModel, JsonValue

from onyx.llm.exceptions import ClassifiedLLMError
from onyx.llm.litellm_conversion import (
    MessageAccumulator,
    from_litellm_model_response,
    from_litellm_model_response_stream,
    recover_tool_calls,
    to_assistant_message,
)
from onyx.llm.litellm_models import (
    ChatCompletionDeltaToolCall,
    Choice,
    Delta,
    ModelResponse,
    ModelResponseStream,
    ResponseFunctionCall,
    StreamingChoice,
)
from onyx.llm.litellm_models import ChatCompletionMessageToolCall as WireToolCall
from onyx.llm.litellm_models import Message as ResponseMessage
from onyx.llm.models import (
    AssistantMessage,
    GenerationDoneEvent,
    GenerationEvent,
    GenerationLifecycleEvent,
    GenerationOptions,
    GenerationRequest,
    GenerationTextEvent,
    GenerationToolCallEvent,
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
from tests.unit.onyx.agents.fakes import ScriptedLLM


def _build_tool_call_payload() -> dict[str, JsonValue]:
    return {
        "id": "chatcmpl-f739f09c-7c9b-4dd6-aea7-cf41d4fd2196",
        "created": 1762544538,
        "model": "gpt-5",
        "object": "chat.completion.chunk",
        "choices": [
            {
                "finish_reason": None,
                "index": 0,
                "delta": {
                    "content": "",
                    "tool_calls": [
                        {
                            "id": None,
                            "index": 0,
                            "type": "function",
                            "function": {
                                "arguments": '{"',
                                "name": None,
                            },
                        }
                    ],
                },
            }
        ],
    }


def _build_reasoning_payload() -> dict[str, JsonValue]:
    return {
        "id": "chatcmpl-c2a25682-5715-4ca2-84a9-061498f79626",
        "created": 1762544538,
        "model": "gpt-5",
        "object": "chat.completion.chunk",
        "choices": [
            {
                "finish_reason": None,
                "index": 0,
                "delta": {
                    "reasoning_content": " variations",
                },
            }
        ],
    }


def _build_multiple_tool_calls_payload() -> dict[str, JsonValue]:
    return {
        "id": "Yn4SaajROLXEnvgP5JTN-AQ",
        "created": 1762819684,
        "model": "gemini-2.5-flash",
        "object": "chat.completion.chunk",
        "choices": [
            {
                "finish_reason": None,
                "index": 0,
                "delta": {
                    "content": None,
                    "tool_calls": [
                        {
                            "id": "call_130bec4755e544ea95f4b1bafd81",
                            "function": {
                                "arguments": '{"queries": ["new agent framework"]}',
                                "name": "internal_search",
                            },
                            "type": "function",
                            "index": 0,
                        },
                        {
                            "id": "call_42273e8ee5ac4c0a97237d6d25a6",
                            "function": {
                                "arguments": '{"queries": ["cheese"]}',
                                "name": "web_search",
                            },
                            "type": "function",
                            "index": 1,
                        },
                    ],
                },
            }
        ],
    }


def _build_usage_only_chunk_payload() -> dict[str, JsonValue]:
    # Final chunk OpenAI emits when stream_options.include_usage is set: empty
    # `choices` array plus usage. litellm forwards it through verbatim.
    return {
        "id": "chatcmpl-usage-only",
        "created": 1762544600,
        "model": "gpt-5.1",
        "object": "chat.completion.chunk",
        "choices": [],
        "usage": {
            "prompt_tokens": 11,
            "completion_tokens": 22,
            "total_tokens": 33,
        },
    }


def _build_non_streaming_response_payload() -> dict[str, JsonValue]:
    return {
        "id": "chatcmpl-abc123",
        "created": 1234567890,
        "model": "gpt-4",
        "object": "chat.completion",
        "choices": [
            {
                "finish_reason": "stop",
                "index": 0,
                "message": {
                    "content": "Hello, world!",
                    "role": "assistant",
                },
            }
        ],
    }


def _build_non_streaming_tool_call_payload() -> dict[str, JsonValue]:
    return {
        "id": "chatcmpl-xyz789",
        "created": 9876543210,
        "model": "gpt-4",
        "object": "chat.completion",
        "choices": [
            {
                "finish_reason": "tool_calls",
                "index": 0,
                "message": {
                    "content": None,
                    "role": "assistant",
                    "tool_calls": [
                        {
                            "id": "call_abc123",
                            "type": "function",
                            "function": {
                                "name": "search_documents",
                                "arguments": '{"query": "test"}',
                            },
                        }
                    ],
                },
            }
        ],
    }


def test_from_litellm_model_response_stream_parses_tool_calls() -> None:
    response = from_litellm_model_response_stream(
        LiteLLMModelResponseStream.model_validate(_build_tool_call_payload())
    )

    assert isinstance(response, ModelResponseStream)
    assert response.id == "chatcmpl-f739f09c-7c9b-4dd6-aea7-cf41d4fd2196"
    assert response.created == "1762544538"

    tool_calls = response.choice.delta.tool_calls
    assert len(tool_calls) == 1
    assert tool_calls[0] == ChatCompletionDeltaToolCall(
        id=None,
        index=0,
        type="function",
        function=ResponseFunctionCall(arguments='{"', name=None),
    )


def test_from_litellm_model_response_stream_preserves_reasoning_content() -> None:
    response = from_litellm_model_response_stream(
        LiteLLMModelResponseStream.model_validate(_build_reasoning_payload())
    )

    assert response.choice.delta.content is None
    assert response.choice.delta.reasoning_content == " variations"
    assert response.choice.finish_reason is None


@pytest.mark.parametrize(
    "expected_finish_reason, expected_content",
    [pytest.param(None, "?", id="content"), pytest.param("stop", None, id="finish")],
)
def test_from_litellm_model_response_stream_handles_content_and_finish_reason(
    expected_finish_reason: str | None,
    expected_content: str | None,
) -> None:
    response = from_litellm_model_response_stream(
        LiteLLMModelResponseStream.model_validate(
            {
                "id": "chatcmpl-2b136068-c6fb-4af1-97d5-d2c9d84cd52b",
                "created": 1762544448,
                "object": "chat.completion.chunk",
                "choices": [
                    {
                        "finish_reason": expected_finish_reason,
                        "index": 0,
                        "delta": {"content": expected_content}
                        if expected_content is not None
                        else {},
                    }
                ],
            }
        )
    )

    assert response.id == "chatcmpl-2b136068-c6fb-4af1-97d5-d2c9d84cd52b"
    assert response.created == "1762544448"
    assert response.choice.index == 0
    assert response.choice.finish_reason == expected_finish_reason
    assert response.choice.delta.content == expected_content


def test_from_litellm_model_response_stream_parses_multiple_tool_calls() -> None:
    response = from_litellm_model_response_stream(
        LiteLLMModelResponseStream.model_validate(_build_multiple_tool_calls_payload())
    )

    tool_calls = response.choice.delta.tool_calls
    assert response.id == "Yn4SaajROLXEnvgP5JTN-AQ"
    assert response.created == "1762819684"
    assert response.choice.finish_reason is None
    assert response.choice.delta.content is None
    assert len(tool_calls) == 2
    assert tool_calls[0] == ChatCompletionDeltaToolCall(
        id="call_130bec4755e544ea95f4b1bafd81",
        index=0,
        type="function",
        function=ResponseFunctionCall(
            arguments='{"queries": ["new agent framework"]}',
            name="internal_search",
        ),
    )
    assert tool_calls[1] == ChatCompletionDeltaToolCall(
        id="call_42273e8ee5ac4c0a97237d6d25a6",
        index=1,
        type="function",
        function=ResponseFunctionCall(
            arguments='{"queries": ["cheese"]}',
            name="web_search",
        ),
    )


def test_from_litellm_model_response_stream_handles_empty_choices_usage_chunk() -> None:
    response = from_litellm_model_response_stream(
        LiteLLMModelResponseStream.model_validate(_build_usage_only_chunk_payload())
    )

    assert isinstance(response, ModelResponseStream)
    assert response.id == "chatcmpl-usage-only"
    assert response.created == "1762544600"
    assert response.choice.finish_reason is None
    assert response.choice.delta.content is None
    assert response.choice.delta.tool_calls == []
    assert response.usage is not None
    assert response.usage.prompt_tokens == 11
    assert response.usage.completion_tokens == 22
    assert response.usage.total_tokens == 33


def test_from_litellm_model_response_parses_basic_message() -> None:
    response = from_litellm_model_response(
        LiteLLMModelResponse.model_validate(_build_non_streaming_response_payload())
    )

    assert isinstance(response, ModelResponse)
    assert response.id == "chatcmpl-abc123"
    assert response.created == "1234567890"
    assert response.choice.finish_reason == "stop"
    assert response.choice.message.content == "Hello, world!"
    assert response.choice.message.role == "assistant"
    assert response.choice.message.tool_calls is None


def test_from_litellm_model_response_parses_tool_calls() -> None:
    response = from_litellm_model_response(
        LiteLLMModelResponse.model_validate(_build_non_streaming_tool_call_payload())
    )

    assert isinstance(response, ModelResponse)
    assert response.id == "chatcmpl-xyz789"
    assert response.created == "9876543210"
    assert response.choice.finish_reason == "tool_calls"
    assert response.choice.message.content is None
    assert response.choice.message.role == "assistant"
    assert response.choice.message.tool_calls is not None
    assert len(response.choice.message.tool_calls) == 1

    tool_call = response.choice.message.tool_calls[0]
    assert tool_call.id == "call_abc123"
    assert tool_call.type == "function"
    assert tool_call.function.name == "search_documents"
    assert tool_call.function.arguments == '{"query": "test"}'


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
    message = terminal.message
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


def test_provider_stream_accepts_null_optional_tool_calls() -> None:
    response = from_litellm_model_response_stream(
        LiteLLMModelResponseStream.model_validate(
            {
                "id": "response",
                "created": 0,
                "choices": [
                    {"index": 0, "delta": {"content": "hello", "tool_calls": None}}
                ],
            }
        )
    )
    assert response.choice.delta.content == "hello"
    assert response.choice.delta.tool_calls == []


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
    assert terminal.message.text == "first partlast"


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
            message = terminal.message
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
@pytest.mark.parametrize(
    "error, expected_type",
    [
        (
            APIConnectionError(
                message="connection failed", model="test", llm_provider="openai"
            ),
            ClassifiedLLMError,
        ),
        (
            InternalServerError(
                message="server failed", model="test", llm_provider="openai"
            ),
            ClassifiedLLMError,
        ),
        (TypeError("bad local implementation"), TypeError),
    ],
)
def test_shared_client_classifies_only_provider_failures(
    streaming: bool, error: Exception, expected_type: type[Exception]
) -> None:
    transport = ScriptedLLM([])
    client = transport
    request = GenerationRequest(messages=[UserMessage(content="Hello")])
    with (
        patch.object(
            transport, "stream_raw" if streaming else "invoke_raw", side_effect=error
        ),
        pytest.raises(expected_type) as caught,
    ):
        if streaming:
            list(client.stream(request))
        else:
            client.invoke(request)
    if expected_type is ClassifiedLLMError:
        assert caught.value.__cause__ is error
    else:
        assert caught.value is error


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


@pytest.mark.parametrize(
    "arguments, expected, valid",
    [
        ("", {}, True),
        ('{"query":"term"}', {"query": "term"}, True),
        (json.dumps('{"query":"term"}'), {"query": "term"}, True),
        ('{"query":broken', {}, False),
        ("[]", {}, False),
    ],
)
def test_complete_conversion_preserves_native_calls_and_response_metadata(
    arguments: str, expected: dict[str, JsonValue], valid: bool
) -> None:
    signed = ThinkingBlock(thinking="plan", signature="provider-signature")
    usage = Usage(
        prompt_tokens=10,
        completion_tokens=3,
        total_tokens=13,
        cache_creation_input_tokens=1,
        cache_read_input_tokens=2,
    )
    fallback = '{"name":"search","arguments":{"query":"fallback"}}'
    request = GenerationRequest(
        tools=[ToolDefinition(name="search", description="Search", parameters={})],
        options=GenerationOptions(tool_choice=ToolChoiceOptions.REQUIRED),
    )
    response = ModelResponse(
        id="response",
        created="1",
        usage=usage,
        choice=Choice(
            finish_reason="tool_calls",
            message=ResponseMessage(
                content=fallback,
                reasoning_content="plan",
                thinking_blocks=[signed],
                tool_calls=[
                    WireToolCall(
                        id="native-call",
                        function=ResponseFunctionCall(
                            name="search", arguments=arguments
                        ),
                    )
                ],
            ),
        ),
    )
    message = to_assistant_message(response, request)
    assert message.text == fallback
    assert message.thinking == "plan"
    assert message.thinking_blocks == [signed]
    assert message.usage == usage
    assert message.stop_reason == "tool_calls"
    assert len(message.tool_calls) == 1
    call = message.tool_calls[0]
    assert call.id == "native-call"
    assert call.arguments == expected
    assert call.arguments_complete is valid
    assert (call.argument_error is None) is valid
    assert call.raw_arguments == (None if valid else arguments)
    assert response.choice.message.tool_calls is not None
    assert response.choice.message.tool_calls[0].function.arguments == arguments
    assert message.thinking_blocks is not None
    thinking = message.thinking_blocks[0]
    assert isinstance(thinking, ThinkingBlock)
    thinking.signature = "changed-signature"
    assert message.usage is not None
    message.usage.prompt_tokens = 999
    assert response.choice.message.thinking_blocks == [signed]
    assert signed.signature == "provider-signature"
    assert response.usage is not None and response.usage.prompt_tokens == 10


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
    assert start.message.content == []
    assert isinstance(delta, TextDeltaEvent)
    assert delta.text == fallback
    assert isinstance(terminal, GenerationDoneEvent)
    assert terminal.message.text == fallback
    assert len(terminal.message.tool_calls) == 1
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
def test_buffered_recovery_emits_one_call_with_usage_and_no_payload_text(
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
    closed: list[bool] = []

    def chunks() -> Iterator[ModelResponseStream]:
        try:
            for fragment in [payload[:15], payload[15:]]:
                yield _stream_chunk(
                    Delta(reasoning_content=fragment)
                    if reasoning
                    else Delta(content=fragment)
                )
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
    assert [event.type for event in events] == [
        "start",
        "tool_call_start",
        "tool_call_delta",
        "tool_call_end",
        "done",
    ]
    assert all(
        not event.message.text and not event.message.thinking
        for event in events
        if isinstance(event, GenerationLifecycleEvent)
    )
    calls = [
        event.tool_call
        for event in events
        if isinstance(event, GenerationToolCallEvent)
    ]
    assert len({call.id for call in calls}) == 1
    assert calls[-1].arguments == {"query": "recovered"}
    terminal = events[-1]
    assert isinstance(terminal, GenerationDoneEvent)
    final = terminal.message
    assert final.usage == usage
    assert final.stop_reason == "stop"
    assert final.tool_calls == [calls[-1]]


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
    assert all(
        isinstance(event, GenerationLifecycleEvent) and event.message.content == []
        for event in events
    )
    assert payload not in str(record.call_args)


def test_incremental_events_preserve_partial_content_and_snapshot_isolation() -> None:
    accumulator = MessageAccumulator()
    accepted = AssistantMessage(id="run:0")
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
        if isinstance(event, GenerationDoneEvent):
            event.message.content.clear()
        elif isinstance(event, GenerationToolCallEvent):
            event.tool_call.arguments.clear()
    assert accepted.id == "run:0"
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


@pytest.mark.parametrize("stream", [False, True])
@pytest.mark.parametrize(
    "payload, expected_blocks",
    [
        (None, None),
        (
            {
                "thinking_blocks": [
                    "malformed",
                    None,
                    {"thinking": None, "signature": "signed"},
                    {"type": "redacted_thinking", "data": None},
                ]
            },
            [
                {"type": "thinking", "thinking": "", "signature": "signed"},
                {"type": "redacted_thinking", "data": ""},
            ],
        ),
    ],
)
def test_provider_payload_tolerance(
    stream: bool,
    payload: dict[str, JsonValue] | None,
    expected_blocks: list[dict[str, JsonValue]] | None,
) -> None:
    data = {
        "id": "response",
        "created": 123,
        "choices": [{"delta" if stream else "message": payload}],
    }
    # Exercise the adapter with the payload before LiteLLM normalizes it.
    if stream:
        with patch.object(LiteLLMModelResponseStream, "model_dump", return_value=data):
            result = from_litellm_model_response_stream(LiteLLMModelResponseStream())
        content = result.choice.delta.content
        blocks = result.choice.delta.thinking_blocks
    else:
        with patch.object(LiteLLMModelResponse, "model_dump", return_value=data):
            response = from_litellm_model_response(LiteLLMModelResponse())
        content = response.choice.message.content
        blocks = response.choice.message.thinking_blocks
    assert content is None
    assert (
        [block.model_dump() for block in blocks] if blocks else None
    ) == expected_blocks
