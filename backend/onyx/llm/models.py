"""Shared LLM messages, generation requests, options, and stream events."""

from enum import Enum
from typing import Annotated, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    JsonValue,
    SerializeAsAny,
)


class ContentType(str, Enum):
    TEXT = "text"
    IMAGE_URL = "image_url"
    THINKING = "thinking"
    REDACTED_THINKING = "redacted_thinking"
    TOOL_CALL = "tool_call"


class MessageRole(str, Enum):
    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"
    TOOL_RESULT = "tool_result"
    TOOL = "tool"


class ImageDetail(str, Enum):
    AUTO = "auto"
    LOW = "low"
    HIGH = "high"


class TextContentPart(BaseModel):
    type: Literal[ContentType.TEXT] = ContentType.TEXT
    text: str
    # Some providers (e.g. Anthropic/Gemini) support prompt caching controls on content blocks.
    cache_control: dict[str, JsonValue] | None = None


class ImageUrlDetail(BaseModel):
    url: str
    detail: ImageDetail | None = None


class ImageContentPart(BaseModel):
    type: Literal[ContentType.IMAGE_URL] = ContentType.IMAGE_URL
    image_url: ImageUrlDetail


ContentPart = TextContentPart | ImageContentPart


class ThinkingBlock(BaseModel):
    type: Literal[ContentType.THINKING] = ContentType.THINKING
    thinking: str = ""
    signature: str | None = None


class RedactedThinkingBlock(BaseModel):
    type: Literal[ContentType.REDACTED_THINKING] = ContentType.REDACTED_THINKING
    data: str


AnyThinkingBlock = ThinkingBlock | RedactedThinkingBlock


class Usage(BaseModel):
    completion_tokens: int
    prompt_tokens: int
    total_tokens: int
    cache_creation_input_tokens: int
    cache_read_input_tokens: int


class TextContent(BaseModel):
    type: Literal[ContentType.TEXT] = ContentType.TEXT
    text: str


class ThinkingContent(BaseModel):
    type: Literal[ContentType.THINKING] = ContentType.THINKING
    text: str
    blocks: list[AnyThinkingBlock] | None = None


class ToolCall(BaseModel):
    type: Literal[ContentType.TOOL_CALL] = ContentType.TOOL_CALL
    id: str
    name: str
    arguments: dict[str, JsonValue]
    argument_error: str | None = None


AssistantContent = Annotated[
    TextContent | ThinkingContent | ToolCall, Field(discriminator="type")
]


class BaseMessage(BaseModel):
    # Request metadata never becomes provider content or durable transcript data.
    metadata: SerializeAsAny[BaseModel] | None = Field(default=None, exclude=True)
    cacheable: bool = Field(default=False, exclude=True)


class SystemMessage(BaseMessage):
    role: Literal[MessageRole.SYSTEM] = MessageRole.SYSTEM
    content: str

    @property
    def text(self) -> str:
        return self.content


class UserMessage(BaseMessage):
    role: Literal[MessageRole.USER] = MessageRole.USER
    content: str | list[TextContentPart | ImageContentPart]

    @property
    def text(self) -> str:
        return content_text(self.content)


class AssistantMessage(BaseMessage):
    role: Literal[MessageRole.ASSISTANT] = MessageRole.ASSISTANT
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


class ToolResult(BaseMessage):
    content: str | list[TextContentPart | ImageContentPart]
    details: SerializeAsAny[BaseModel] | None = None
    is_error: bool = False
    terminate: bool = False

    @property
    def text(self) -> str:
        return content_text(self.content)


class ToolResultMessage(ToolResult):
    role: Literal[MessageRole.TOOL_RESULT] = MessageRole.TOOL_RESULT
    tool_call_id: str
    tool_name: str


Message = Annotated[
    SystemMessage | UserMessage | AssistantMessage | ToolResultMessage,
    Field(discriminator="role"),
]


def content_text(content: str | list[TextContentPart | ImageContentPart]) -> str:
    if isinstance(content, str):
        return content
    return "".join(part.text for part in content if isinstance(part, TextContentPart))


class ReasoningEffort(str, Enum):
    """Reasoning effort levels mapped by each provider."""

    AUTO = "auto"
    OFF = "off"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    # Supported by OpenAI and Anthropic adaptive-thinking models (Claude >= 4.7).
    # Other provider mappings clamp it to their highest supported effort.
    XHIGH = "xhigh"


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


def resolve_reasoning_effort(
    requested: ReasoningEffort,
    *,
    default: ReasoningEffort | None,
    user_default: ReasoningEffort | None,
    maximum: ReasoningEffort | None,
) -> ReasoningEffort:
    """Apply admin and user defaults, then cap the effective reasoning effort.

    AUTO resolves before clamping because providers interpret it as medium.
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


class ToolChoiceOptions(str, Enum):
    REQUIRED = "required"
    AUTO = "auto"
    NONE = "none"


class NamedToolChoice(BaseModel):
    model_config = ConfigDict(frozen=True)

    name: str


ToolChoice = ToolChoiceOptions | NamedToolChoice


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


class GenerationEventType(str, Enum):
    START = "start"
    DONE = "done"
    ERROR = "error"
    TEXT_START = "text_start"
    TEXT_DELTA = "text_delta"
    TEXT_END = "text_end"
    THINKING_START = "thinking_start"
    THINKING_DELTA = "thinking_delta"
    THINKING_END = "thinking_end"
    TOOL_CALL_START = "tool_call_start"
    TOOL_CALL_DELTA = "tool_call_delta"
    TOOL_CALL_END = "tool_call_end"


class _Event(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    request_params: GenerationRequestParams | None = None


class GenerationLifecycleEvent(_Event):
    message: AssistantMessage


class GenerationStartEvent(GenerationLifecycleEvent):
    type: Literal[GenerationEventType.START] = GenerationEventType.START


class GenerationDoneEvent(GenerationLifecycleEvent):
    type: Literal[GenerationEventType.DONE] = GenerationEventType.DONE


class GenerationErrorEvent(GenerationLifecycleEvent):
    type: Literal[GenerationEventType.ERROR] = GenerationEventType.ERROR


class GenerationTextEvent(_Event):
    message: AssistantMessage
    content_index: int = Field(ge=0)
    text: str = ""


class TextStartEvent(GenerationTextEvent):
    type: Literal[GenerationEventType.TEXT_START] = GenerationEventType.TEXT_START


class TextDeltaEvent(GenerationTextEvent):
    type: Literal[GenerationEventType.TEXT_DELTA] = GenerationEventType.TEXT_DELTA


class TextEndEvent(GenerationTextEvent):
    type: Literal[GenerationEventType.TEXT_END] = GenerationEventType.TEXT_END


class ThinkingStartEvent(GenerationTextEvent):
    type: Literal[GenerationEventType.THINKING_START] = (
        GenerationEventType.THINKING_START
    )


class ThinkingDeltaEvent(GenerationTextEvent):
    type: Literal[GenerationEventType.THINKING_DELTA] = (
        GenerationEventType.THINKING_DELTA
    )


class ThinkingEndEvent(GenerationTextEvent):
    type: Literal[GenerationEventType.THINKING_END] = GenerationEventType.THINKING_END


class GenerationToolCallEvent(_Event):
    message: AssistantMessage
    content_index: int = Field(ge=0)
    tool_call: ToolCall
    argument_deltas: dict[str, str] = Field(default_factory=dict)


class ToolCallStartEvent(GenerationToolCallEvent):
    type: Literal[GenerationEventType.TOOL_CALL_START] = (
        GenerationEventType.TOOL_CALL_START
    )


class ToolCallDeltaEvent(GenerationToolCallEvent):
    type: Literal[GenerationEventType.TOOL_CALL_DELTA] = (
        GenerationEventType.TOOL_CALL_DELTA
    )


class ToolCallEndEvent(GenerationToolCallEvent):
    type: Literal[GenerationEventType.TOOL_CALL_END] = GenerationEventType.TOOL_CALL_END


GenerationEvent = Annotated[
    GenerationStartEvent
    | GenerationDoneEvent
    | GenerationErrorEvent
    | TextStartEvent
    | TextDeltaEvent
    | TextEndEvent
    | ThinkingStartEvent
    | ThinkingDeltaEvent
    | ThinkingEndEvent
    | ToolCallStartEvent
    | ToolCallDeltaEvent
    | ToolCallEndEvent,
    Field(discriminator="type"),
]
