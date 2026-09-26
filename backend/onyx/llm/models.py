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
    content: str | list[ContentPart]
    tool_call_id: str
    tool_name: str

    @property
    def text(self) -> str:
        return content_text(self.content)


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
