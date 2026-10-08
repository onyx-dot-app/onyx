import json
from collections.abc import Iterator
from unittest.mock import patch

import pytest
from litellm.exceptions import APIConnectionError, InternalServerError
from litellm.types.utils import ModelResponse as LiteLLMModelResponse
from litellm.types.utils import ModelResponseStream as LiteLLMModelResponseStream
from pydantic import JsonValue

from onyx.llm.exceptions import ClassifiedLLMError
from onyx.llm.model_request import format_provider_message
from onyx.llm.model_response import (
    ChatCompletionDeltaToolCall,
    Choice,
    Delta,
    MessageAccumulator,
    ModelResponse,
    ModelResponseStream,
    ResponseFunctionCall,
    StreamingChoice,
    from_litellm_model_response,
    from_litellm_model_response_stream,
    to_assistant_message,
)
from onyx.llm.model_response import ChatCompletionMessageToolCall as WireToolCall
from onyx.llm.model_response import Message as ResponseMessage
from onyx.llm.models import (
    AssistantMessage,
    GenerationEvent,
    GenerationOptions,
    GenerationRequest,
    RedactedThinkingBlock,
    TextDeltaEvent,
    ThinkingBlock,
    ThinkingDeltaEvent,
    ToolChoiceOptions,
    ToolDefinition,
    Usage,
    UserMessage,
    apply_generation_event,
)
from tests.unit.onyx.agents.fakes import ScriptedLLM, collect_generation


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


def test_stream_failure_preserves_unresolved_text_without_executing_it() -> None:
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
    assert [event.type for event in events] == ["start", "text_delta", "error"]
    message = collect_generation(events)
    assert message.text == payload
    assert message.tool_calls == []
    assert payload in str(record.call_args)


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


@pytest.mark.parametrize(
    "payload, expected_text",
    [
        (
            'Searching now. {"name":"search","arguments":{"query":"onyx"}}',
            'Searching now. {"name":"search","arguments":{"query":"onyx"}}',
        ),
        (
            'Searching now.<function_calls><invoke name="search">'
            '<parameter name="query">onyx</parameter></invoke></function_calls>',
            "Searching now.",
        ),
    ],
)
def test_recovered_calls_preserve_text_and_signed_thinking(
    payload: str, expected_text: str
) -> None:
    signed = ThinkingBlock(thinking="plan", signature="provider-signature")
    request = GenerationRequest(
        tools=[ToolDefinition(name="search", description="Search", parameters={})],
        options=GenerationOptions(tool_choice=ToolChoiceOptions.REQUIRED),
    )
    response = ModelResponse(
        id="response",
        created="1",
        choice=Choice(
            message=ResponseMessage(
                content=payload,
                reasoning_content="plan",
                thinking_blocks=[signed],
            )
        ),
    )
    message = to_assistant_message(response, request)
    assert message.text == expected_text
    assert message.thinking == "plan"
    assert message.thinking_blocks == [signed]
    assert [call.name for call in message.tool_calls] == ["search"]
    assert message.tool_calls[0].arguments == {"query": "onyx"}


@pytest.mark.parametrize(
    "text", ['{"answer":', "<section>", "```python", "ordinary prose"]
)
@pytest.mark.parametrize("choice", [ToolChoiceOptions.AUTO, ToolChoiceOptions.REQUIRED])
def test_tool_recovery_does_not_delay_answer_text(
    text: str, choice: ToolChoiceOptions
) -> None:
    def chunks() -> Iterator[ModelResponseStream]:
        yield _stream_chunk(Delta(content=text))
        raise AssertionError("Read ahead before delivering answer text")

    accumulator = MessageAccumulator()
    events = accumulator.consume(
        chunks(),
        GenerationRequest(
            tools=[ToolDefinition(name="search", description="Search", parameters={})],
            options=GenerationOptions(tool_choice=choice),
        ),
    )
    try:
        event = next(events)
        assert isinstance(event, TextDeltaEvent)
        assert event.text == text
    finally:
        events.close()


@pytest.mark.parametrize("has_tools", [False, True])
def test_disabled_recovery_preserves_literal_xml(has_tools: bool) -> None:
    text = '<function_calls><invoke name="search"></invoke></function_calls>'
    request = GenerationRequest(
        tools=[ToolDefinition(name="search", description="Search", parameters={})]
        if has_tools
        else [],
        options=GenerationOptions(
            tool_choice=ToolChoiceOptions.NONE if has_tools else ToolChoiceOptions.AUTO
        ),
    )
    accumulator = MessageAccumulator(request.tools)
    events = list(
        accumulator.consume(
            iter([_stream_chunk(Delta(content=part)) for part in [text[:8], text[8:]]]),
            request,
        )
    )
    events.extend(accumulator.end())
    message = collect_generation(events)
    complete = to_assistant_message(
        ModelResponse(
            id="test", created="1", choice=Choice(message=ResponseMessage(content=text))
        ),
        request,
    )
    assert message.text == complete.text == text
    assert message.tool_calls == []


def test_thinking_fragments_form_signed_blocks_for_replay() -> None:
    accumulator = MessageAccumulator()
    accepted = AssistantMessage()
    blocks = [
        ThinkingBlock(thinking="First"),
        ThinkingBlock(thinking=" thought"),
        ThinkingBlock(signature="first-signature"),
        RedactedThinkingBlock(data="redacted"),
        ThinkingBlock(thinking="Second"),
        ThinkingBlock(signature="second-signature"),
    ]
    saved = None
    events: list[GenerationEvent] = []
    for index, block in enumerate(blocks):
        updates = accumulator.add(_stream_chunk(Delta(thinking_blocks=[block])))
        events.extend(updates)
        for event in updates:
            apply_generation_event(accepted, event)
        if index == 0:
            saved = accepted.model_copy(deep=True)
    for event in accumulator.end():
        apply_generation_event(accepted, event)
    expected = [
        ThinkingBlock(thinking="First thought", signature="first-signature"),
        RedactedThinkingBlock(data="redacted"),
        ThinkingBlock(thinking="Second", signature="second-signature"),
    ]
    assert accepted.thinking_blocks == accumulator.message.thinking_blocks == expected
    assert saved is not None and saved.thinking_blocks == [
        ThinkingBlock(thinking="First")
    ]
    replay = format_provider_message(accepted)
    assert replay.model_dump()["thinking_blocks"] == [
        block.model_dump() for block in expected
    ]
    first = events[0]
    assert isinstance(first, ThinkingDeltaEvent)
    assert first.blocks == [ThinkingBlock(thinking="First")]
