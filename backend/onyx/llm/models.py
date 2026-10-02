from enum import Enum
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, JsonValue


class LLMErrorInfo(BaseModel):
    message: str
    error_code: str
    is_retryable: bool


class ToolChoiceOptions(str, Enum):
    REQUIRED = "required"
    AUTO = "auto"
    NONE = "none"


class NamedToolChoice(BaseModel):
    model_config = ConfigDict(frozen=True)

    name: str


ToolChoice = ToolChoiceOptions | NamedToolChoice


class ReasoningEffort(str, Enum):
    """Reasoning effort levels for models that support extended thinking.

    Different providers map these values differently:
    - OpenAI: Uses "low", "medium", "high" directly for reasoning_effort. Recently added "none" for 5 series
              which is like "minimal"
    - Claude: Uses budget_tokens with different values for each level
    - Gemini: Uses "none", "low", "medium", "high" for thinking_budget (via litellm mapping)
    """

    AUTO = "auto"
    OFF = "off"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    # Supported by OpenAI and Anthropic adaptive-thinking models (Claude >= 4.7).
    # Other provider mappings clamp it to their highest supported effort.
    XHIGH = "xhigh"


# Reasoning-effort values a user may pin per chat session. AUTO is excluded
# because a cleared override (NULL) already resolves to AUTO.
USER_SELECTABLE_REASONING_EFFORTS: frozenset[ReasoningEffort] = frozenset(
    {
        ReasoningEffort.OFF,
        ReasoningEffort.LOW,
        ReasoningEffort.MEDIUM,
        ReasoningEffort.HIGH,
        ReasoningEffort.XHIGH,
    }
)


def parse_user_selectable_reasoning_effort(value: str) -> ReasoningEffort:
    """Parse a user-supplied override value. Raises ValueError for an unknown
    value or an explicit "auto", neither of which is user-selectable."""
    effort = ReasoningEffort(value)
    if effort not in USER_SELECTABLE_REASONING_EFFORTS:
        raise ValueError(f"{value!r} is not a selectable reasoning effort")
    return effort


# AUTO has no rank: it defers a choice rather than naming an amount.
_REASONING_EFFORT_RANK: dict[ReasoningEffort, int] = {
    ReasoningEffort.OFF: 0,
    ReasoningEffort.LOW: 1,
    ReasoningEffort.MEDIUM: 2,
    ReasoningEffort.HIGH: 3,
    ReasoningEffort.XHIGH: 4,
}


def reasoning_effort_exceeds(effort: ReasoningEffort, cap: ReasoningEffort) -> bool:
    """Whether `effort` asks for more thinking than `cap` allows."""
    return _REASONING_EFFORT_RANK[effort] > _REASONING_EFFORT_RANK[cap]


class UserChatDefaults(BaseModel):
    """A user's own chat defaults, resolved below any admin per-model
    setting. See resolve_reasoning_effort for the reasoning chain."""

    temperature_default: float | None = None
    reasoning_effort_default: ReasoningEffort | None = None


def resolve_reasoning_effort(
    requested: ReasoningEffort,
    *,
    default: ReasoningEffort | None,
    user_default: ReasoningEffort | None,
    maximum: ReasoningEffort | None,
) -> ReasoningEffort:
    """Settle a request against the admin's per-model default, the user's own
    default, and the cap.

    Ordered chain, first concrete source wins. The cap applies last and
    unconditionally.

    AUTO is concretized before clamping because it maps to medium downstream,
    which would quietly exceed a cap of LOW.
    """
    if requested != ReasoningEffort.AUTO:
        effort = requested
    elif default is not None and default != ReasoningEffort.AUTO:
        effort = default
    elif user_default is not None and user_default != ReasoningEffort.AUTO:
        effort = user_default
    else:
        if maximum is None:
            return ReasoningEffort.AUTO
        effort = ReasoningEffort.MEDIUM

    if maximum is not None and reasoning_effort_exceeds(effort, maximum):
        return maximum
    return effort


# Content part structures for multimodal messages
# The classes in this mirror the OpenAI Chat Completions message types and work well with routers like LiteLLM
class TextContentPart(BaseModel):
    type: Literal["text"] = "text"
    text: str
    # Some providers (e.g. Anthropic/Gemini) support prompt caching controls on content blocks.
    cache_control: dict | None = None


class ImageUrlDetail(BaseModel):
    url: str
    detail: Literal["auto", "low", "high"] | None = None


class ImageContentPart(BaseModel):
    type: Literal["image_url"] = "image_url"
    image_url: ImageUrlDetail


ContentPart = TextContentPart | ImageContentPart


# The signature is minted by the provider and must be round-tripped unmodified
# for replay to be accepted.
class ThinkingBlock(BaseModel):
    type: Literal["thinking"] = "thinking"
    thinking: str = ""
    signature: str | None = None


class RedactedThinkingBlock(BaseModel):
    type: Literal["redacted_thinking"] = "redacted_thinking"
    data: str


AnyThinkingBlock = ThinkingBlock | RedactedThinkingBlock


class Usage(BaseModel):
    completion_tokens: int
    prompt_tokens: int
    total_tokens: int
    cache_creation_input_tokens: int
    cache_read_input_tokens: int


class TextContent(BaseModel):
    type: Literal["text"] = "text"
    text: str


class ThinkingContent(BaseModel):
    type: Literal["thinking"] = "thinking"
    text: str
    blocks: list[AnyThinkingBlock] | None = None


class ToolCall(BaseModel):
    type: Literal["tool_call"] = "tool_call"
    id: str
    name: str
    arguments: dict[str, JsonValue]
    argument_error: str | None = None
    raw_arguments: str | None = None
    arguments_complete: bool = True


AssistantContent = Annotated[
    TextContent | ThinkingContent | ToolCall, Field(discriminator="type")
]


class BaseMessage(BaseModel):
    # Marks a stable prompt prefix for provider prompt caching; never sent as content.
    cacheable: bool = Field(default=False, exclude=True)


class SystemMessage(BaseMessage):
    role: Literal["system"] = "system"
    content: str

    @property
    def text(self) -> str:
        return self.content


class UserMessage(BaseMessage):
    role: Literal["user"] = "user"
    content: str | list[ContentPart]

    @property
    def text(self) -> str:
        return content_text(self.content)


class AssistantMessage(BaseMessage):
    role: Literal["assistant"] = "assistant"
    content: list[AssistantContent] = Field(default_factory=list)
    stop_reason: str | None = None
    error_message: str | None = None
    usage: Usage | None = None

    @property
    def text(self) -> str:
        return "".join(
            block.text for block in self.content if isinstance(block, TextContent)
        )

    @property
    def thinking(self) -> str:
        return "".join(
            block.text for block in self.content if isinstance(block, ThinkingContent)
        )

    @property
    def thinking_blocks(self) -> list[AnyThinkingBlock] | None:
        return [
            block
            for content in self.content
            if isinstance(content, ThinkingContent)
            for block in content.blocks or []
        ] or None

    @property
    def tool_calls(self) -> list[ToolCall]:
        return [block for block in self.content if isinstance(block, ToolCall)]


class ToolResultMessage(BaseMessage):
    role: Literal["tool_result"] = "tool_result"
    # Provider tool messages carry text only.
    content: str
    tool_call_id: str
    tool_name: str

    @property
    def text(self) -> str:
        return self.content


Message = Annotated[
    SystemMessage | UserMessage | AssistantMessage | ToolResultMessage,
    Field(discriminator="role"),
]


def content_text(content: str | list[ContentPart]) -> str:
    if isinstance(content, str):
        return content
    return "".join(part.text for part in content if isinstance(part, TextContentPart))


class ToolDefinition(BaseModel):
    model_config = ConfigDict(frozen=True)
    name: str
    description: str
    parameters: dict[str, JsonValue]


class GenerationOptions(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tool_choice: ToolChoice = ToolChoiceOptions.AUTO
    reasoning_effort: ReasoningEffort = ReasoningEffort.AUTO
    max_tokens: int | None = Field(default=None, gt=0)
    structured_response_format: dict[str, JsonValue] | None = None


class GenerationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    messages: list[Message] = Field(default_factory=list)
    system_prompt: str = ""
    tools: list[ToolDefinition] = Field(default_factory=list)
    options: GenerationOptions = Field(default_factory=GenerationOptions)


class GenerationRequestParams(BaseModel):
    """Effective provider settings for the attempt that produced the response."""

    model_config = ConfigDict(extra="forbid")
    model_name: str
    model_provider: str
    reasoning_effort: ReasoningEffort
    max_tokens: int | None
    sent_kwargs: dict[str, JsonValue]


class _Event(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    request_params: GenerationRequestParams | None = None


class GenerationLifecycleEvent(_Event):
    """Generation status; content arrives through incremental content events."""


class GenerationStartEvent(GenerationLifecycleEvent):
    type: Literal["start"] = "start"


class GenerationDoneEvent(GenerationLifecycleEvent):
    type: Literal["done"] = "done"
    usage: Usage | None = None
    stop_reason: str | None = None


class GenerationErrorEvent(GenerationLifecycleEvent):
    type: Literal["error"] = "error"
    usage: Usage | None = None
    stop_reason: Literal["error"] = "error"
    error_message: str


class GenerationTextEvent(_Event):
    content_index: int = Field(ge=0)
    text: str = ""


class TextDeltaEvent(GenerationTextEvent):
    type: Literal["text_delta"] = "text_delta"


class ThinkingDeltaEvent(GenerationTextEvent):
    blocks: list[AnyThinkingBlock] | None = None
    type: Literal["thinking_delta"] = "thinking_delta"


class GenerationToolCallEvent(_Event):
    content_index: int = Field(ge=0)
    tool_call: ToolCall
    argument_deltas: dict[str, str] = Field(default_factory=dict)


class ToolCallStartEvent(GenerationToolCallEvent):
    type: Literal["tool_call_start"] = "tool_call_start"


class ToolCallDeltaEvent(GenerationToolCallEvent):
    type: Literal["tool_call_delta"] = "tool_call_delta"


class ToolCallEndEvent(GenerationToolCallEvent):
    type: Literal["tool_call_end"] = "tool_call_end"


GenerationEvent = Annotated[
    GenerationStartEvent
    | GenerationDoneEvent
    | GenerationErrorEvent
    | TextDeltaEvent
    | ThinkingDeltaEvent
    | ToolCallStartEvent
    | ToolCallDeltaEvent
    | ToolCallEndEvent,
    Field(discriminator="type"),
]


def apply_generation_event(message: AssistantMessage, event: GenerationEvent) -> None:
    """Mutate caller-owned output while preserving its identity and application metadata.

    The caller must serialize access to the message. Mutable event payloads are
    copied, so later message updates cannot alter the event. Copy the message
    before exposing it as a snapshot.
    """
    if isinstance(event, GenerationStartEvent):
        return
    if isinstance(event, (GenerationDoneEvent, GenerationErrorEvent)):
        message.stop_reason = event.stop_reason
        message.error_message = (
            event.error_message if isinstance(event, GenerationErrorEvent) else None
        )
        message.usage = event.usage.model_copy(deep=True) if event.usage else None
        return
    index = event.content_index
    if index > len(message.content):
        raise ValueError("Generation update skips a content block")
    if isinstance(event, GenerationToolCallEvent):
        block = event.tool_call.model_copy(deep=True)
        if index == len(message.content):
            if not isinstance(event, ToolCallStartEvent):
                raise ValueError("Tool update requires a started call")
            message.content.append(block)
        else:
            if not isinstance(message.content[index], ToolCall):
                raise ValueError("Tool update targets non-tool content")
            message.content[index] = block
        return
    if index == len(message.content):
        message.content.append(
            ThinkingContent(text="")
            if isinstance(event, ThinkingDeltaEvent)
            else TextContent(text="")
        )
    content = message.content[index]
    if isinstance(event, ThinkingDeltaEvent):
        if not isinstance(content, ThinkingContent):
            raise ValueError("Thinking update targets non-thinking content")
        content.text += event.text
        if event.blocks:
            if content.blocks is None:
                content.blocks = []
            for block in event.blocks:
                last = content.blocks[-1] if content.blocks else None
                # Providers stream one thinking block as text fragments and then
                # its signature. Merge them so the block can be replayed.
                if (
                    isinstance(block, ThinkingBlock)
                    and isinstance(last, ThinkingBlock)
                    and not last.signature
                ):
                    last.thinking += block.thinking
                    last.signature = block.signature
                else:
                    content.blocks.append(block.model_copy(deep=True))
    else:
        if not isinstance(content, TextContent):
            raise ValueError("Text update targets non-text content")
        content.text += event.text
