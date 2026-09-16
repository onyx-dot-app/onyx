import pytest
from litellm.types.utils import ModelResponse as LiteLLMModelResponse
from litellm.types.utils import ModelResponseStream as LiteLLMModelResponseStream
from pydantic import JsonValue

from onyx.llm.litellm_conversion import (
    MessageAccumulator,
    from_litellm_model_response,
    from_litellm_model_response_stream,
)
from onyx.llm.litellm_models import (
    ChatCompletionDeltaToolCall,
    Delta,
    FunctionCall,
    ModelResponse,
    ModelResponseStream,
    StreamingChoice,
)
from onyx.llm.models import ThinkingBlock, ToolCallEndEvent


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
        function=FunctionCall(arguments='{"', name=None),
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
        function=FunctionCall(
            arguments='{"queries": ["new agent framework"]}',
            name="internal_search",
        ),
    )
    assert tool_calls[1] == ChatCompletionDeltaToolCall(
        id="call_42273e8ee5ac4c0a97237d6d25a6",
        index=1,
        type="function",
        function=FunctionCall(
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
            function=FunctionCall(name="search", arguments='{"query":"fir'),
        ),
        ChatCompletionDeltaToolCall(
            index=1,
            id="second",
            function=FunctionCall(name="search", arguments='{"query":"second"}'),
        ),
        ChatCompletionDeltaToolCall(index=0, function=FunctionCall(arguments='st"}')),
        ChatCompletionDeltaToolCall(
            index=2,
            id="invalid",
            function=FunctionCall(name="search", arguments='{"query":broken'),
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
    message = events[-1].message
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
