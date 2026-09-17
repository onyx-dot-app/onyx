"""Convert shared generation requests and provider responses, including stream events."""

import json
from collections.abc import Generator, Iterator, Sequence
from typing import TYPE_CHECKING, Protocol, overload, runtime_checkable
from uuid import uuid4

from pydantic import BaseModel, Field, JsonValue, TypeAdapter, ValidationError

from onyx.llm.constants import LlmProviderNames
from onyx.llm.interfaces import LLMConfig
from onyx.llm.litellm_models import AssistantMessage as WireAssistantMessage
from onyx.llm.litellm_models import (
    ChatCompletionDeltaToolCall,
    ChatCompletionMessage,
    Choice,
    Delta,
    ModelResponse,
    ModelResponseStream,
    StreamingChoice,
)
from onyx.llm.litellm_models import FunctionCall as DeltaFunctionCall
from onyx.llm.litellm_models import Message as ResponseMessage
from onyx.llm.litellm_models import SystemMessage as WireSystemMessage
from onyx.llm.litellm_models import ToolCall as ProviderToolCall
from onyx.llm.litellm_models import ToolFunctionCall as ProviderFunctionCall
from onyx.llm.litellm_models import ToolMessage as ProviderToolMessage
from onyx.llm.litellm_models import UserMessage as WireUserMessage
from onyx.llm.models import (
    AnyThinkingBlock,
    AssistantMessage,
    GenerationDoneEvent,
    GenerationEvent,
    GenerationRequest,
    Message,
    SystemMessage,
    TextContent,
    TextDeltaEvent,
    TextEndEvent,
    TextStartEvent,
    ThinkingContent,
    ThinkingDeltaEvent,
    ThinkingEndEvent,
    ThinkingStartEvent,
    ToolCall,
    ToolCallDeltaEvent,
    ToolCallEndEvent,
    ToolCallStartEvent,
    ToolChoiceOptions,
    ToolDefinition,
    ToolResultMessage,
    Usage,
    UserMessage,
)
from onyx.llm.prompt_cache.processor import process_with_prompt_cache
from onyx.llm.tool_parsing import (
    _looks_like_xml_tool_call_payload,
    extract_tool_calls_from_response_text,
)
from onyx.llm.utils import model_needs_formatting_reenabled
from onyx.tools.tool_name import sanitize_tool_name
from onyx.utils.jsonriver import Parser
from onyx.utils.logger import setup_logger
from onyx.utils.postgres_sanitization import sanitize_string

# OpenAI reasoning models need this prefix to enable Markdown formatting.
CODE_BLOCK_MARKDOWN = "Formatting re-enabled. "

logger = setup_logger()

if TYPE_CHECKING:
    from litellm.types.utils import ModelResponse as LiteLLMModelResponse
    from litellm.types.utils import ModelResponseStream as LiteLLMModelResponseStream


class _CachedTokens(BaseModel):
    cached_tokens: int | None = None


class _ProviderUsage(BaseModel):
    completion_tokens: int | None = None
    prompt_tokens: int | None = None
    total_tokens: int | None = None
    cache_creation_input_tokens: int | None = None
    cache_read_input_tokens: int | None = None
    prompt_tokens_details: _CachedTokens | None = None

    def to_usage(self) -> Usage:
        cached = self.cache_read_input_tokens
        if cached is None and self.prompt_tokens_details is not None:
            cached = self.prompt_tokens_details.cached_tokens
        # Providers omit counters they do not measure, including cache usage.
        return Usage(
            completion_tokens=self.completion_tokens or 0,
            prompt_tokens=self.prompt_tokens or 0,
            total_tokens=self.total_tokens or 0,
            cache_creation_input_tokens=self.cache_creation_input_tokens or 0,
            cache_read_input_tokens=cached or 0,
        )


class _ProviderDelta(BaseModel):
    content: str | None = None
    reasoning_content: str | None = None
    thinking_blocks: list[AnyThinkingBlock] | None = None
    tool_calls: list[ChatCompletionDeltaToolCall] | None = None

    def to_delta(self) -> Delta:
        return Delta(
            content=self.content,
            reasoning_content=self.reasoning_content,
            thinking_blocks=self.thinking_blocks,
            tool_calls=self.tool_calls or [],
        )


class _ProviderChoice(BaseModel):
    finish_reason: str | None = None
    index: int = 0
    delta: _ProviderDelta = Field(default_factory=_ProviderDelta)
    message: ResponseMessage = Field(default_factory=ResponseMessage)


class _ProviderResponse(BaseModel):
    id: str | int
    created: str | int
    choices: list[_ProviderChoice] = Field(default_factory=list)
    usage: _ProviderUsage | None = None


def from_litellm_model_response_stream(
    response: "LiteLLMModelResponseStream",
) -> ModelResponseStream:
    data = _ProviderResponse.model_validate(response.model_dump())
    # Usage-only terminal chunks have no choices.
    choice = data.choices[0] if data.choices else _ProviderChoice()
    return ModelResponseStream(
        id=str(data.id),
        created=str(data.created),
        choice=StreamingChoice(
            finish_reason=choice.finish_reason,
            index=choice.index,
            delta=choice.delta.to_delta(),
        ),
        usage=data.usage.to_usage() if data.usage is not None else None,
    )


def from_litellm_model_response(
    response: "LiteLLMModelResponse",
) -> ModelResponse:
    data = _ProviderResponse.model_validate(response.model_dump())
    if not data.choices:
        raise ValueError("LiteLLM response must include at least one choice.")
    choice = data.choices[0]
    return ModelResponse(
        id=str(data.id),
        created=str(data.created),
        choice=Choice(
            finish_reason=choice.finish_reason,
            index=choice.index,
            message=choice.message,
        ),
        usage=data.usage.to_usage() if data.usage is not None else None,
    )


def serialize_request(
    request: GenerationRequest, config: LLMConfig
) -> list[ChatCompletionMessage]:
    history = (
        [SystemMessage(content=request.system_prompt, cacheable=True)]
        if request.system_prompt
        else []
    ) + request.messages
    messages: list[ChatCompletionMessage] = []
    cacheable_prefix = 0
    ollama = config.model_provider == LlmProviderNames.OLLAMA_CHAT
    for index, message in enumerate(history):
        if message.cacheable and cacheable_prefix == index:
            cacheable_prefix += 1
        if isinstance(message, AssistantMessage):
            content = [
                block.model_copy(update={"name": sanitize_tool_name(block.name)})
                if isinstance(block, ToolCall)
                else block
                for block in message.content
            ]
            message = message.model_copy(update={"content": content})
            if ollama and message.tool_calls:
                calls = [
                    f"[Tool Call] name={call.name} id={call.id} args={json.dumps(call.arguments)}"
                    for call in message.tool_calls
                ]
                messages.append(
                    WireAssistantMessage(
                        content="\n".join(
                            ([message.text] if message.text else []) + calls
                        )
                    )
                )
                continue
        if isinstance(message, ToolResultMessage) and not message.tool_call_id:
            raise ValueError("Provider tool messages require tool_call_id")
        if ollama and isinstance(message, ToolResultMessage):
            messages.append(
                WireUserMessage(
                    content=f"[Tool Result] id={message.tool_call_id}\n{message.text}"
                )
            )
        else:
            messages.append(format_provider_message(message))
    if model_needs_formatting_reenabled(config.model_name, config.deployment_name):
        for index, message in enumerate(messages):
            if isinstance(message, WireSystemMessage):
                messages[index] = WireSystemMessage(
                    content=CODE_BLOCK_MARKDOWN + message.content
                )
                break
    if cacheable_prefix:
        prepared, _ = process_with_prompt_cache(
            llm_info=config,
            cacheable_prefix=messages[:cacheable_prefix],
            suffix=messages[cacheable_prefix:],
            continuation=False,
        )
        if not isinstance(prepared, list):
            raise TypeError("Prompt caching must preserve the message list")
        messages = prepared
    return messages


@overload
def format_provider_message(message: SystemMessage) -> WireSystemMessage: ...


@overload
def format_provider_message(message: UserMessage) -> WireUserMessage: ...


@overload
def format_provider_message(message: AssistantMessage) -> WireAssistantMessage: ...


@overload
def format_provider_message(message: ToolResultMessage) -> ProviderToolMessage: ...


def format_provider_message(message: Message) -> ChatCompletionMessage:
    """Serialize message content, replaying thinking only when provider signatures exist."""
    if isinstance(message, SystemMessage):
        return WireSystemMessage(content=message.content)
    if isinstance(message, UserMessage):
        return WireUserMessage(content=message.content)
    if isinstance(message, AssistantMessage):
        return WireAssistantMessage(
            content=message.text or None,
            thinking_blocks=message.thinking_blocks,
            tool_calls=[
                ProviderToolCall(
                    id=call.id,
                    function=ProviderFunctionCall(
                        name=call.name, arguments=json.dumps(call.arguments)
                    ),
                )
                for call in message.tool_calls
            ]
            or None,
        )
    if isinstance(message, ToolResultMessage):
        if not isinstance(message.content, str):
            raise ValueError("Provider tool messages require text content")
        if not message.tool_call_id:
            raise ValueError("Provider tool messages require tool_call_id")
        return ProviderToolMessage(
            content=message.content, tool_call_id=message.tool_call_id
        )
    raise TypeError(f"Unsupported message type: {type(message).__name__}")


def serialize_tools(tools: Sequence[ToolDefinition]) -> list[dict[str, JsonValue]]:
    return [
        {
            "type": "function",
            "function": {
                "name": tool.name,
                "description": tool.description,
                "parameters": tool.parameters,
            },
        }
        for tool in tools
    ]


@runtime_checkable
class Closable(Protocol):
    def close(self) -> None: ...


_ARGUMENTS = TypeAdapter(dict[str, JsonValue])
_ENCODED_ARGUMENTS = TypeAdapter(dict[str, JsonValue] | str)
_JSON_VALUE = TypeAdapter(JsonValue)


def _normalize_arguments(
    arguments: dict[str, JsonValue], definition: ToolDefinition | None
) -> dict[str, JsonValue]:
    if definition is None:
        return arguments
    properties = definition.parameters.get("properties")
    if not isinstance(properties, dict):
        return arguments
    normalized = arguments.copy()
    for name, value in arguments.items():
        schema = properties.get(name)
        if not isinstance(value, str) or not isinstance(schema, dict):
            continue
        expected_type = schema.get("type")
        if expected_type not in ("array", "object"):
            continue
        # Only structured fields accept JSON strings; string fields retain literal text.
        try:
            decoded = _JSON_VALUE.validate_json(value)
        except ValidationError:
            logger.debug("Tool field %s is not encoded JSON", name, exc_info=True)
            continue
        if (expected_type == "array" and isinstance(decoded, list)) or (
            expected_type == "object" and isinstance(decoded, dict)
        ):
            normalized[name] = decoded
    return normalized


class _PendingToolCall:
    def __init__(self, content_index: int, call: ToolCall) -> None:
        self.content_index = content_index
        self.call = call
        self.arguments = ""
        self.parser: Parser | None = Parser()

    def update(self, delta: ChatCompletionDeltaToolCall) -> dict[str, str]:
        if delta.id:
            self.call.id = delta.id
        if delta.function is None:
            return {}
        if delta.function.name:
            self.call.name = delta.function.name
        text = delta.function.arguments or ""
        self.arguments += text
        self.call.raw_arguments = self.arguments
        if self.parser is None or not text:
            return {}
        try:
            updates = self.parser.feed(text)
        except ValueError:
            # Retain invalid arguments so execution can return a paired tool error.
            logger.debug("Tool arguments cannot be parsed incrementally", exc_info=True)
            self.parser = None
            return {}
        fragments: dict[str, str] = {}
        for update in updates:
            if isinstance(update, dict):
                for key, value in update.items():
                    if isinstance(value, str):
                        fragments[key] = fragments.get(key, "") + value
        partial = self.parser.snapshot()
        if isinstance(partial, dict):
            self.call.arguments = partial
        return fragments


class MessageAccumulator:
    """Maintain ordered assistant content and incremental tool arguments."""

    def __init__(self, tools: Sequence[ToolDefinition] = ()) -> None:
        self.tools = {tool.name: tool for tool in tools}
        self.message = AssistantMessage()
        self.calls: dict[int, _PendingToolCall] = {}
        self.active_text: int | None = None

    def close_text(self) -> list[GenerationEvent]:
        if self.active_text is None:
            return []
        index, self.active_text = self.active_text, None
        block = self.message.content[index]
        message = self.message.model_copy(deep=True)
        if isinstance(block, ThinkingContent):
            return [ThinkingEndEvent(message=message, content_index=index)]
        return [TextEndEvent(message=message, content_index=index)]

    def _add_text(
        self, content: TextContent | ThinkingContent
    ) -> list[GenerationEvent]:
        events: list[GenerationEvent] = []
        if self.active_text is None or type(
            self.message.content[self.active_text]
        ) is not type(content):
            events.extend(self.close_text())
            self.active_text = len(self.message.content)
            block = content.model_copy(deep=True)
            block.text = ""
            if isinstance(block, ThinkingContent):
                block.blocks = None
            self.message.content.append(block)
            start = (
                ThinkingStartEvent
                if isinstance(content, ThinkingContent)
                else TextStartEvent
            )
            events.append(
                start(
                    message=self.message.model_copy(deep=True),
                    content_index=self.active_text,
                )
            )
        block = self.message.content[self.active_text]
        if not isinstance(block, (TextContent, ThinkingContent)):
            raise RuntimeError("Active text block must contain text or thinking")
        block.text += content.text
        if isinstance(block, ThinkingContent) and isinstance(content, ThinkingContent):
            block.blocks = (block.blocks or []) + (content.blocks or []) or None
        delta = (
            ThinkingDeltaEvent
            if isinstance(content, ThinkingContent)
            else TextDeltaEvent
        )
        events.append(
            delta(
                message=self.message.model_copy(deep=True),
                content_index=self.active_text,
                text=content.text,
            )
        )
        return events

    def add(self, chunk: ModelResponseStream) -> list[GenerationEvent]:
        delta = chunk.choice.delta
        events: list[GenerationEvent] = []
        if delta.reasoning_content or delta.thinking_blocks:
            events.extend(
                self._add_text(
                    ThinkingContent(
                        text=delta.reasoning_content or "", blocks=delta.thinking_blocks
                    )
                )
            )
        if delta.content:
            events.extend(self._add_text(TextContent(text=delta.content)))
        for call in delta.tool_calls:
            events.extend(self.close_text())
            pending = self.calls.get(call.index)
            if pending is None:
                block = ToolCall(
                    id=call.id or f"fallback_{uuid4().hex}",
                    name=call.function.name or "" if call.function else "",
                    arguments={},
                    arguments_complete=False,
                )
                pending = _PendingToolCall(len(self.message.content), block)
                self.calls[call.index] = pending
                self.message.content.append(block)
                events.append(
                    ToolCallStartEvent(
                        message=self.message.model_copy(deep=True),
                        content_index=pending.content_index,
                        tool_call=block.model_copy(deep=True),
                    )
                )
            fragments = pending.update(call)
            events.append(
                ToolCallDeltaEvent(
                    message=self.message.model_copy(deep=True),
                    content_index=pending.content_index,
                    tool_call=pending.call.model_copy(deep=True),
                    argument_deltas=fragments,
                )
            )
        if chunk.choice.finish_reason:
            self.message.stop_reason = chunk.choice.finish_reason
        if chunk.usage is not None:
            self.message.usage = chunk.usage
        return events

    def finish(self) -> AssistantMessage:
        for pending in self.calls.values():
            try:
                arguments = _ENCODED_ARGUMENTS.validate_json(
                    sanitize_string(pending.arguments or "{}")
                )
                if isinstance(arguments, str):
                    arguments = _ARGUMENTS.validate_json(arguments)
                pending.call.arguments = _normalize_arguments(
                    arguments, self.tools.get(pending.call.name)
                )
                pending.call.arguments_complete = True
                pending.call.raw_arguments = None
            except ValidationError:
                logger.debug("Tool arguments are not a JSON object", exc_info=True)
                pending.call.arguments = {}
                pending.call.argument_error = (
                    "Tool arguments are not a valid JSON object."
                )
        return self.message.model_copy(deep=True)

    def end(self) -> list[GenerationEvent]:
        events = self.close_text()
        self.finish()
        for pending in self.calls.values():
            events.append(
                ToolCallEndEvent(
                    message=self.message.model_copy(deep=True),
                    content_index=pending.content_index,
                    tool_call=pending.call.model_copy(deep=True),
                )
            )
        events.append(GenerationDoneEvent(message=self.message.model_copy(deep=True)))
        return events


def recover_tool_calls(
    message: AssistantMessage, request: GenerationRequest
) -> AssistantMessage:
    """Recover provider text tool payloads when native calls are absent."""
    if message.tool_calls or request.options.tool_choice == ToolChoiceOptions.NONE:
        return message
    should_try = (
        request.options.tool_choice == ToolChoiceOptions.REQUIRED
        or bool(message.thinking and not message.text)
        or _looks_like_xml_tool_call_payload(message.text)
        or _looks_like_xml_tool_call_payload(message.thinking)
    )
    if not should_try:
        return message
    definitions = serialize_tools(request.tools)
    calls = extract_tool_calls_from_response_text(
        message.text, definitions
    ) or extract_tool_calls_from_response_text(message.thinking, definitions)
    if not calls:
        return message
    tools = {tool.name: tool for tool in request.tools}
    for call in calls:
        call.arguments = _normalize_arguments(call.arguments, tools.get(call.name))
    return message.model_copy(update={"content": [*calls]})


def normalized_stream(
    stream: Iterator[ModelResponseStream],
    request: GenerationRequest,
) -> Generator[ModelResponseStream, None, None]:
    """Normalize IDs and resolve text compatibility before events or rendering."""
    ids: dict[int, str] = {}
    buffered: list[ModelResponseStream] = []
    accumulator = MessageAccumulator(request.tools)
    buffering = (
        bool(request.tools) and request.options.tool_choice != ToolChoiceOptions.NONE
    )
    try:
        for chunk in stream:
            chunk = chunk.model_copy(deep=True)
            for call in chunk.choice.delta.tool_calls:
                call.id = ids.setdefault(call.index, call.id or str(uuid4()))
            if not buffering:
                yield chunk
                continue
            buffered.append(chunk)
            accumulator.add(chunk)
            # Native calls and ordinary prose can stream immediately. Ambiguous payloads wait for parsing.
            text = accumulator.message.text.lstrip()
            native = bool(accumulator.calls)
            prose = (
                request.options.tool_choice != ToolChoiceOptions.REQUIRED
                and bool(text)
                and not text.startswith(("<", "`", "{"))
            )
            if native or prose:
                yield from buffered
                buffered.clear()
                buffering = False
        if buffered:
            message = recover_tool_calls(accumulator.finish(), request)
            if message.tool_calls:
                last = buffered[-1]
                yield ModelResponseStream(
                    id=last.id,
                    created=last.created,
                    usage=message.usage,
                    choice=StreamingChoice(
                        finish_reason=message.stop_reason,
                        delta=Delta(
                            tool_calls=[
                                ChatCompletionDeltaToolCall(
                                    index=index,
                                    id=call.id,
                                    function=DeltaFunctionCall(
                                        name=call.name,
                                        arguments=json.dumps(call.arguments),
                                    ),
                                )
                                for index, call in enumerate(message.tool_calls)
                            ]
                        ),
                    ),
                )
            else:
                yield from buffered
    finally:
        if isinstance(stream, Closable):
            stream.close()
