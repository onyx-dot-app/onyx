"""Provider responses, normalization, and application message accumulation."""

from collections.abc import Generator, Iterator, Sequence
from typing import TYPE_CHECKING, Literal, Protocol, runtime_checkable
from uuid import uuid4

from pydantic import (
    BaseModel,
    Field,
    JsonValue,
    TypeAdapter,
    ValidationError,
    field_validator,
)

from onyx.llm.models import (
    AnyThinkingBlock,
    AssistantMessage,
    GenerationDoneEvent,
    GenerationEvent,
    GenerationRequest,
    MessageRole,
    TextContent,
    TextDeltaEvent,
    ThinkingContent,
    ThinkingDeltaEvent,
    ToolCall,
    ToolCallDeltaEvent,
    ToolCallEndEvent,
    ToolCallStartEvent,
    ToolChoiceOptions,
    ToolDefinition,
    Usage,
    apply_generation_event,
)
from onyx.llm.tool_parsing import (
    XmlToolCallContentFilter,
    _looks_like_xml_tool_call_payload,
    extract_tool_calls_from_response_text,
)
from onyx.utils.jsonriver import Parser
from onyx.utils.logger import setup_logger
from onyx.utils.postgres_sanitization import sanitize_string

logger = setup_logger()

if TYPE_CHECKING:
    from litellm.types.utils import ModelResponse as LiteLLMModelResponse
    from litellm.types.utils import ModelResponseStream as LiteLLMModelResponseStream


class ResponseFunctionCall(BaseModel):
    """Function fields received from the provider; streaming fields may be absent."""

    arguments: str | None = None
    name: str | None = None


class ChatCompletionMessageToolCall(BaseModel):
    id: str
    type: Literal["function"] = "function"
    function: ResponseFunctionCall


class ChatCompletionDeltaToolCall(BaseModel):
    id: str | None = None
    index: int = 0
    type: Literal["function"] = "function"
    function: ResponseFunctionCall | None = None


class Delta(BaseModel):
    content: str | None = None
    reasoning_content: str | None = None
    thinking_blocks: list[AnyThinkingBlock] | None = None
    tool_calls: list[ChatCompletionDeltaToolCall] = Field(default_factory=list)


class StreamingChoice(BaseModel):
    finish_reason: str | None = None
    index: int = 0
    delta: Delta = Field(default_factory=Delta)


class ModelResponseStream(BaseModel):
    id: str
    created: str
    choice: StreamingChoice
    usage: Usage | None = None


class Message(BaseModel):
    content: str | None = None
    role: Literal[MessageRole.ASSISTANT] = MessageRole.ASSISTANT
    tool_calls: list[ChatCompletionMessageToolCall] | None = None
    reasoning_content: str | None = None
    thinking_blocks: list[AnyThinkingBlock] | None = None


class Choice(BaseModel):
    finish_reason: str | None = None
    index: int = 0
    message: Message = Field(default_factory=Message)


class ModelResponse(BaseModel):
    id: str
    created: str
    choice: Choice
    usage: Usage | None = None


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
    message: Message = Field(default_factory=Message)

    @field_validator("delta", "message", mode="before")
    @classmethod
    def normalize_payload(cls, value: object) -> object:
        if value is None:
            return {}
        if not isinstance(value, dict):
            return value
        thinking_blocks = value.get("thinking_blocks")
        if not isinstance(thinking_blocks, list) or not thinking_blocks:
            return value
        # Providers can return incomplete thinking blocks.
        blocks: list[dict[str, object]] = []
        for block in thinking_blocks:
            if not isinstance(block, dict):
                logger.warning(
                    "Dropping malformed thinking block of type %s", type(block).__name__
                )
                continue
            if block.get("type") == "redacted_thinking":
                blocks.append(
                    {"type": "redacted_thinking", "data": block.get("data") or ""}
                )
            else:
                blocks.append(
                    {
                        "type": "thinking",
                        "thinking": block.get("thinking") or "",
                        "signature": block.get("signature"),
                    }
                )
        return {**value, "thinking_blocks": blocks or None}


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
    if len(data.choices) > 1:
        messages = [item.message for item in data.choices]
        finish_reasons = [
            item.finish_reason for item in data.choices if item.finish_reason
        ]
        choice = _ProviderChoice(
            index=0,
            finish_reason=finish_reasons[-1] if finish_reasons else None,
            message=Message(
                role=messages[0].role,
                content="".join(
                    message.content for message in messages if message.content
                )
                or None,
                reasoning_content="\n\n".join(
                    message.reasoning_content
                    for message in messages
                    if message.reasoning_content
                )
                or None,
                tool_calls=[
                    call for message in messages for call in message.tool_calls or []
                ]
                or None,
                thinking_blocks=[
                    block
                    for message in messages
                    for block in message.thinking_blocks or []
                ]
                or None,
            ),
        )
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


def _finish_tool_call(
    call: ToolCall, arguments: str, definition: ToolDefinition | None
) -> None:
    try:
        decoded = _ENCODED_ARGUMENTS.validate_json(sanitize_string(arguments or "{}"))
        if isinstance(decoded, str):
            decoded = _ARGUMENTS.validate_json(decoded)
        call.arguments = _normalize_arguments(decoded, definition)
        call.arguments_complete = True
        call.raw_arguments = None
    except ValidationError:
        logger.debug("Tool arguments are not a JSON object", exc_info=True)
        call.arguments = {}
        call.argument_error = "Tool arguments are not a valid JSON object."


def to_assistant_message(
    response: ModelResponse, request: GenerationRequest
) -> AssistantMessage:
    """Convert a complete provider response without creating stream events."""
    source = response.choice.message
    message = AssistantMessage(
        stop_reason=response.choice.finish_reason, usage=response.usage
    )
    if source.reasoning_content or source.thinking_blocks:
        message.content.append(
            ThinkingContent(
                text=source.reasoning_content or "", blocks=source.thinking_blocks
            )
        )
    if source.content:
        message.content.append(TextContent(text=source.content))
    definitions = {tool.name: tool for tool in request.tools}
    for source_call in source.tool_calls or []:
        arguments = source_call.function.arguments or ""
        call = ToolCall(
            id=source_call.id or str(uuid4()),
            name=source_call.function.name or "",
            arguments={},
            raw_arguments=arguments,
            arguments_complete=False,
        )
        _finish_tool_call(call, arguments, definitions.get(call.name))
        message.content.append(call)
    if request.tools:
        message = recover_tool_calls(message, request)
    return message.model_copy(deep=True)


class _PendingToolCall:
    def __init__(self, content_index: int, call: ToolCall) -> None:
        self.content_index = content_index
        self.call = call
        self.arguments: str | None = ""
        self.parser: Parser | None = Parser()
        self.finalized = False

    def update(self, delta: ChatCompletionDeltaToolCall) -> dict[str, str]:
        self.finalized = False
        if delta.id:
            self.call.id = delta.id
        if delta.function is None:
            return {}
        if delta.function.name:
            self.call.name = delta.function.name
        text = delta.function.arguments or ""
        self.arguments = (self.arguments or "") + text
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

    def _add_text(
        self, content: TextContent | ThinkingContent
    ) -> list[GenerationEvent]:
        if self.active_text is None or type(
            self.message.content[self.active_text]
        ) is not type(content):
            self.active_text = len(self.message.content)
        event = (
            ThinkingDeltaEvent(
                content_index=self.active_text,
                text=content.text,
                blocks=[block.model_copy(deep=True) for block in content.blocks]
                if content.blocks
                else None,
            )
            if isinstance(content, ThinkingContent)
            else TextDeltaEvent(content_index=self.active_text, text=content.text)
        )
        apply_generation_event(self.message, event)
        return [event]

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
            self.active_text = None
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
                        content_index=pending.content_index,
                        tool_call=block.model_copy(deep=True),
                    )
                )
            fragments = pending.update(call)
            events.append(
                ToolCallDeltaEvent(
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

    def _add_recovered_calls(self, calls: Sequence[ToolCall]) -> list[GenerationEvent]:
        self.active_text = None
        events: list[GenerationEvent] = []
        for call in calls:
            block = ToolCall(
                id=call.id, name=call.name, arguments={}, arguments_complete=False
            )
            pending = _PendingToolCall(len(self.message.content), block)
            # Recovery already parsed and normalized these arguments.
            pending.arguments = None
            self.calls[len(self.calls)] = pending
            self.message.content.append(block)
            events.append(
                ToolCallStartEvent(
                    content_index=pending.content_index,
                    tool_call=block.model_copy(deep=True),
                )
            )
            block.arguments = call.arguments.copy()
            events.append(
                ToolCallDeltaEvent(
                    content_index=pending.content_index,
                    tool_call=block.model_copy(deep=True),
                    argument_deltas={
                        name: value
                        for name, value in call.arguments.items()
                        if isinstance(value, str)
                    },
                )
            )
        return events

    def consume(
        self, stream: Iterator[ModelResponseStream], request: GenerationRequest
    ) -> Generator[GenerationEvent, None, None]:
        """Filter provider text and recover calls before producing shared events."""
        ids: dict[int, str] = {}
        buffered: list[ModelResponseStream] = []
        recover = (
            bool(request.tools)
            and request.options.tool_choice != ToolChoiceOptions.NONE
        )
        buffering = recover
        raw_text: list[str] = []
        raw_thinking: list[str] = []
        content_filter = XmlToolCallContentFilter()
        usage: Usage | None = None
        stop_reason: str | None = None

        def add_filtered(chunk: ModelResponseStream) -> list[GenerationEvent]:
            chunk = chunk.model_copy(deep=True)
            for call in chunk.choice.delta.tool_calls:
                call.id = ids.setdefault(call.index, call.id or str(uuid4()))
            if chunk.choice.delta.content:
                chunk.choice.delta.content = content_filter.process(
                    chunk.choice.delta.content
                )
            return self.add(chunk)

        try:
            for chunk in stream:
                delta = chunk.choice.delta
                if delta.tool_calls:
                    recover = False
                    raw_text.clear()
                    raw_thinking.clear()
                if recover:
                    raw_text.append(delta.content or "")
                    raw_thinking.append(delta.reasoning_content or "")
                if chunk.usage is not None:
                    usage = chunk.usage
                if chunk.choice.finish_reason:
                    stop_reason = chunk.choice.finish_reason
                if not buffering:
                    yield from add_filtered(chunk)
                    continue
                buffered.append(chunk)
                text = "".join(raw_text).lstrip()
                prose = (
                    request.options.tool_choice != ToolChoiceOptions.REQUIRED
                    and bool(text)
                    and not text.startswith(("<", "`", "{"))
                )
                if delta.tool_calls or prose:
                    for pending_chunk in buffered:
                        yield from add_filtered(pending_chunk)
                    buffered.clear()
                    buffering = False

            recovered: AssistantMessage | None = None
            if recover and not self.calls:
                recovered = recover_tool_calls(
                    AssistantMessage(
                        content=[
                            TextContent(text="".join(raw_text)),
                            ThinkingContent(text="".join(raw_thinking)),
                        ]
                    ),
                    request,
                )
            if buffered:
                if recovered is not None and recovered.tool_calls:
                    if recovered.text:
                        yield from self._add_text(
                            TextContent(text=content_filter.process(recovered.text))
                        )
                    yield from self._add_recovered_calls(recovered.tool_calls)
                else:
                    for pending_chunk in buffered:
                        yield from add_filtered(pending_chunk)
            tail = content_filter.flush()
            if tail:
                yield from self._add_text(TextContent(text=tail))
            if not self.calls and recovered is not None and recovered.tool_calls:
                yield from self._add_recovered_calls(recovered.tool_calls)
            self.message.usage = usage
            self.message.stop_reason = stop_reason
        finally:
            if isinstance(stream, Closable):
                stream.close()

    def finalize(self) -> None:
        """Finalize owned tool arguments without making a message snapshot."""
        for pending in self.calls.values():
            if pending.finalized:
                continue
            if pending.arguments is None:
                pending.call.arguments_complete = True
            else:
                _finish_tool_call(
                    pending.call, pending.arguments, self.tools.get(pending.call.name)
                )
            pending.finalized = True

    def end(self) -> list[GenerationEvent]:
        self.active_text = None
        self.finalize()
        events: list[GenerationEvent] = [
            ToolCallEndEvent(
                content_index=pending.content_index,
                tool_call=pending.call.model_copy(deep=True),
            )
            for pending in self.calls.values()
        ]
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
    calls = extract_tool_calls_from_response_text(
        message.text, request.tools
    ) or extract_tool_calls_from_response_text(message.thinking, request.tools)
    if not calls:
        return message
    tools = {tool.name: tool for tool in request.tools}
    for call in calls:
        call.arguments = _normalize_arguments(call.arguments, tools.get(call.name))
    content: list[TextContent | ToolCall] = []
    if _looks_like_xml_tool_call_payload(message.text):
        content_filter = XmlToolCallContentFilter()
        visible_text = content_filter.process(message.text) + content_filter.flush()
        if visible_text:
            content.append(TextContent(text=visible_text))
    content.extend(calls)
    return message.model_copy(update={"content": content})
