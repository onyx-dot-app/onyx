"""Translate persisted Onyx messages at the Pydantic AI boundary."""

from pydantic_ai import messages as pm
from pydantic_ai.usage import RequestUsage

from onyx.llm import model_response as response
from onyx.llm.models import (
    AssistantMessage,
    ImageContentPart,
    LanguageModelInput,
    RedactedThinkingBlock,
    SystemMessage,
    ThinkingBlock,
    ToolMessage,
    UserMessage,
)


def to_pydantic_messages(
    prompt: LanguageModelInput, provider_name: str = ""
) -> list[pm.ModelMessage]:
    messages = prompt if isinstance(prompt, list) else [prompt]
    result: list[pm.ModelMessage] = []
    tool_names: dict[str, str] = {}
    for message in messages:
        if isinstance(message, SystemMessage):
            result.append(pm.ModelRequest(parts=[pm.SystemPromptPart(message.content)]))
        elif isinstance(message, UserMessage):
            content: str | list[pm.UserContent]
            if isinstance(message.content, str):
                content = message.content
            else:
                content = []
                for part in message.content:
                    if isinstance(part, ImageContentPart):
                        content.append(
                            pm.ImageUrl(
                                part.image_url.url,
                                vendor_metadata={
                                    "detail": part.image_url.detail or "auto"
                                },
                            )
                        )
                    else:
                        content.append(part.text)
                        if part.cache_control:
                            content.append(
                                pm.CachePoint(
                                    ttl="1h"
                                    if part.cache_control.get("ttl") == "1h"
                                    else "5m"
                                )
                            )
            if message.cache_control:
                cache_content: list[pm.UserContent] = (
                    [content] if isinstance(content, str) else content
                )
                cache_content.append(
                    pm.CachePoint(
                        ttl="1h" if message.cache_control.get("ttl") == "1h" else "5m"
                    )
                )
                content = cache_content
            result.append(pm.ModelRequest(parts=[pm.UserPromptPart(content)]))
        elif isinstance(message, ToolMessage):
            result.append(
                pm.ModelRequest(
                    parts=[
                        pm.ToolReturnPart(
                            tool_name=tool_names.get(message.tool_call_id, "tool"),
                            content=message.content,
                            tool_call_id=message.tool_call_id,
                        )
                    ]
                )
            )
        elif isinstance(message, AssistantMessage):
            parts: list[pm.ModelResponsePart] = []
            for block in message.thinking_blocks or []:
                if isinstance(block, RedactedThinkingBlock):
                    parts.append(
                        pm.ThinkingPart(
                            "",
                            signature=block.data,
                            provider_name=provider_name,
                            id="redacted_thinking",
                        )
                    )
                else:
                    parts.append(
                        pm.ThinkingPart(
                            block.thinking,
                            signature=block.signature,
                            provider_name=provider_name,
                        )
                    )
            if message.content:
                parts.append(pm.TextPart(message.content))
            for call in message.tool_calls or []:
                tool_names[call.id] = call.function.name
                parts.append(
                    pm.ToolCallPart(
                        call.function.name, call.function.arguments, call.id
                    )
                )
            if parts:
                result.append(
                    pm.ModelResponse(parts=parts, provider_name=provider_name)
                )
    return result


def from_pydantic_usage(usage: RequestUsage) -> response.Usage:
    return response.Usage(
        completion_tokens=usage.output_tokens,
        prompt_tokens=usage.input_tokens,
        total_tokens=usage.total_tokens,
        cache_creation_input_tokens=usage.cache_write_tokens,
        cache_read_input_tokens=usage.cache_read_tokens,
    )


def from_pydantic_response(value: pm.ModelResponse) -> response.ModelResponse:
    text: list[str] = []
    thoughts: list[ThinkingBlock | RedactedThinkingBlock] = []
    calls: list[response.ChatCompletionMessageToolCall] = []
    for part in value.parts:
        if isinstance(part, pm.TextPart):
            text.append(part.content)
        elif isinstance(part, pm.ThinkingPart):
            if part.id == "redacted_thinking":
                thoughts.append(RedactedThinkingBlock(data=part.signature or ""))
            else:
                thoughts.append(
                    ThinkingBlock(thinking=part.content, signature=part.signature)
                )
        elif isinstance(part, pm.ToolCallPart):
            calls.append(
                response.ChatCompletionMessageToolCall(
                    id=part.tool_call_id,
                    function=response.FunctionCall(
                        name=part.tool_name,
                        arguments=(
                            part.args
                            if isinstance(part.args, str)
                            else part.args_as_json_str()
                            if part.args is not None
                            else ""
                        ),
                    ),
                )
            )
    return response.ModelResponse(
        id=value.provider_response_id or "",
        created=value.timestamp.isoformat(),
        choice=response.Choice(
            finish_reason=value.finish_reason,
            message=response.Message(
                content="".join(text) or None,
                reasoning_content="".join(
                    p.thinking for p in thoughts if isinstance(p, ThinkingBlock)
                )
                or None,
                thinking_blocks=thoughts or None,
                tool_calls=calls or None,
            ),
        ),
        usage=from_pydantic_usage(value.usage),
    )


def from_pydantic_event(
    event: pm.ModelResponseStreamEvent, value: pm.ModelResponse
) -> response.ModelResponseStream | None:
    delta = response.Delta()
    if isinstance(event, pm.PartStartEvent):
        part = event.part
        if isinstance(part, pm.TextPart):
            delta.content = part.content
        elif isinstance(part, pm.ThinkingPart):
            delta.reasoning_content = part.content
            delta.thinking_blocks = [
                RedactedThinkingBlock(data=part.signature or "")
                if part.id == "redacted_thinking"
                else ThinkingBlock(thinking=part.content, signature=part.signature)
            ]
        elif isinstance(part, pm.ToolCallPart):
            delta.tool_calls = [
                response.ChatCompletionDeltaToolCall(
                    index=event.index,
                    id=part.tool_call_id,
                    function=response.FunctionCall(
                        name=part.tool_name,
                        arguments=(
                            part.args
                            if isinstance(part.args, str)
                            else part.args_as_json_str()
                            if part.args is not None
                            else ""
                        ),
                    ),
                )
            ]
        else:
            return None
    elif isinstance(event, pm.PartDeltaEvent):
        part_delta = event.delta
        if isinstance(part_delta, pm.TextPartDelta):
            delta.content = part_delta.content_delta
        elif isinstance(part_delta, pm.ThinkingPartDelta):
            delta.reasoning_content = part_delta.content_delta
            delta.thinking_blocks = [
                ThinkingBlock(
                    thinking=part_delta.content_delta or "",
                    signature=part_delta.signature_delta,
                )
            ]
        elif isinstance(part_delta, pm.ToolCallPartDelta):
            import json

            args = part_delta.args_delta
            delta.tool_calls = [
                response.ChatCompletionDeltaToolCall(
                    index=event.index,
                    id=part_delta.tool_call_id,
                    function=response.FunctionCall(
                        name=part_delta.tool_name_delta,
                        arguments=json.dumps(args) if isinstance(args, dict) else args,
                    ),
                )
            ]
        else:
            return None
    else:
        return None
    return response.ModelResponseStream(
        id=value.provider_response_id or "",
        created=value.timestamp.isoformat(),
        choice=response.StreamingChoice(delta=delta),
    )
