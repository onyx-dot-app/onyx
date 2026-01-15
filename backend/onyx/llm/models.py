from enum import Enum
from typing import Literal

from pydantic import BaseModel


class ToolChoiceOptions(str, Enum):
    REQUIRED = "required"
    AUTO = "auto"
    NONE = "none"


class ReasoningEffort(str, Enum):
    """Reasoning effort levels for models that support extended thinking.

    Different providers map these values differently:
    - OpenAI: Uses "low", "medium", "high" directly for reasoning_effort. Recently added "none" for 5 series
              which is like "minimal"
    - Claude: Uses budget_tokens with different values for each level
    - Gemini: Uses "none", "low", "medium", "high" for thinking_budget (via litellm mapping)
    """

    OFF = "off"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


# OpenAI reasoning effort mapping
OPENAI_REASONING_EFFORT: dict[ReasoningEffort | None, str] = {
    None: "low",
    ReasoningEffort.OFF: "none",
    ReasoningEffort.LOW: "low",
    ReasoningEffort.MEDIUM: "medium",
    ReasoningEffort.HIGH: "high",
}


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


# Tool call structures
class FunctionCall(BaseModel):
    name: str
    arguments: str


class ToolCall(BaseModel):
    type: Literal["function"] = "function"
    id: str
    function: FunctionCall


# Message types


# Base class for all cacheable messages
class CacheableMessage(BaseModel):
    # Some providers support prompt caching controls at the message level (passed through via LiteLLM).
    cache_control: dict | None = None


class SystemMessage(CacheableMessage):
    role: Literal["system"] = "system"
    content: str | list[ContentPart]


class UserMessage(CacheableMessage):
    role: Literal["user"] = "user"
    content: str | list[ContentPart]


class AssistantMessage(CacheableMessage):
    role: Literal["assistant"] = "assistant"
    content: str | None = None
    tool_calls: list[ToolCall] | None = None


class ToolMessage(CacheableMessage):
    role: Literal["tool"] = "tool"
    content: str
    tool_call_id: str


# Union type for all OpenAI Chat Completions messages
ChatCompletionMessage = SystemMessage | UserMessage | AssistantMessage | ToolMessage
# Allows for passing in a string directly. This is provided for convenience and is wrapped as a UserMessage.
LanguageModelInput = list[ChatCompletionMessage] | str
