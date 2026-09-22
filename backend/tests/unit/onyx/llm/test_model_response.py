"""Round-trip native messages, thinking signatures, cache and tool deltas."""

from pydantic_ai import messages as pm
from pydantic_ai.usage import RequestUsage

from onyx.llm.models import (
    AssistantMessage,
    ChatCompletionMessage,
    FunctionCall,
    ImageContentPart,
    ImageUrlDetail,
    RedactedThinkingBlock,
    TextContentPart,
    ThinkingBlock,
    ToolCall,
    ToolMessage,
    UserMessage,
)
from onyx.llm.pydantic_messages import (
    from_pydantic_event,
    from_pydantic_response,
    to_pydantic_messages,
)


def test_signed_and_redacted_thinking_round_trip() -> None:
    prompt: list[ChatCompletionMessage] = [
        AssistantMessage(
            thinking_blocks=[
                ThinkingBlock(thinking="reason", signature="signed"),
                RedactedThinkingBlock(data="encrypted"),
            ],
            content="hello",
        )
    ]
    native = to_pydantic_messages(prompt, "anthropic")[0]
    assert isinstance(native, pm.ModelResponse)
    converted = from_pydantic_response(native)
    assert isinstance(prompt[0], AssistantMessage)
    assert converted.choice.message.thinking_blocks == prompt[0].thinking_blocks
    assert converted.choice.message.content == "hello"


def test_tool_history_preserves_ids_names_and_arguments() -> None:
    native = to_pydantic_messages(
        [
            AssistantMessage(
                tool_calls=[
                    ToolCall(
                        id="call-1",
                        function=FunctionCall(name="search", arguments='{"q":"term"}'),
                    )
                ]
            ),
            ToolMessage(tool_call_id="call-1", content="result"),
        ]
    )
    assert isinstance(native[0], pm.ModelResponse)
    call = native[0].parts[0]
    assert isinstance(call, pm.ToolCallPart)
    assert call.args_as_dict() == {"q": "term"}
    assert isinstance(native[1], pm.ModelRequest)
    tool_return = native[1].parts[0]
    assert isinstance(tool_return, pm.ToolReturnPart)
    assert tool_return.tool_name == "search" and tool_return.tool_call_id == "call-1"


def test_multimodal_content_and_cache_boundary() -> None:
    native = to_pydantic_messages(
        UserMessage(
            content=[
                TextContentPart(text="look", cache_control={"ttl": "1h"}),
                ImageContentPart(
                    image_url=ImageUrlDetail(
                        url="https://example.com/image.png", detail="high"
                    )
                ),
            ]
        )
    )
    assert isinstance(native[0], pm.ModelRequest)
    prompt = native[0].parts[0]
    assert isinstance(prompt, pm.UserPromptPart)
    assert isinstance(prompt.content[1], pm.CachePoint)
    assert prompt.content[1].ttl == "1h"
    assert isinstance(prompt.content[2], pm.ImageUrl)
    assert prompt.content[2].vendor_metadata == {"detail": "high"}


def test_usage_preserves_cache_write_and_read_tokens() -> None:
    response = from_pydantic_response(
        pm.ModelResponse(
            parts=[pm.TextPart("answer")],
            usage=RequestUsage(
                input_tokens=100,
                output_tokens=20,
                cache_read_tokens=30,
                cache_write_tokens=40,
            ),
        )
    )
    assert response.usage
    assert response.usage.cache_creation_input_tokens == 40
    assert response.usage.cache_read_input_tokens == 30
    assert response.usage.total_tokens == 120


def test_partial_tool_arguments_do_not_gain_empty_json_prefix() -> None:
    response = pm.ModelResponse(parts=[])
    first = from_pydantic_event(
        pm.PartStartEvent(index=2, part=pm.ToolCallPart("search", None, "call-1")),
        response,
    )
    second = from_pydantic_event(
        pm.PartDeltaEvent(
            index=2, delta=pm.ToolCallPartDelta(args_delta='{"q":"term"}')
        ),
        response,
    )
    assert first and second
    call = first.choice.delta.tool_calls[0]
    assert call.function and call.function.arguments == ""
    delta = second.choice.delta.tool_calls[0]
    assert delta.function and delta.function.arguments == '{"q":"term"}'
    assert delta.index == call.index == 2


def test_redacted_stream_start_preserves_ciphertext() -> None:
    chunk = from_pydantic_event(
        pm.PartStartEvent(
            index=0,
            part=pm.ThinkingPart("", id="redacted_thinking", signature="ciphertext"),
        ),
        pm.ModelResponse(parts=[]),
    )
    assert chunk
    assert chunk.choice.delta.thinking_blocks == [
        RedactedThinkingBlock(data="ciphertext")
    ]
