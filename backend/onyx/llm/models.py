from enum import Enum
from typing import Any
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
class SystemMessage(BaseModel):
    role: Literal["system"] = "system"
    content: str


class UserMessage(BaseModel):
    role: Literal["user"] = "user"
    content: str | list[ContentPart]


class AssistantMessage(BaseModel):
    role: Literal["assistant"] = "assistant"
    content: str | None = None
    tool_calls: list[ToolCall] | None = None
    # Extra reasoning details for verification, stored in provider-specific format:
    # - Anthropic: {"thinking_blocks": [...]}
    # - OpenRouter/Gemini: {"reasoning_details": [...]}
    # Used during the current turn only (not persisted to DB)
    extra_reasoning_details: dict[str, Any] | None = None

    def model_dump(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        """Override model_dump to flatten extra_reasoning_details for LiteLLM compatibility.

        extra_reasoning_details is a dict for holding arbitrary reasoning content/verification details from the model.
        The key is the provider-specific key for the reasoning details like "thinking_blocks" or "reasoning_details".
        Model dump needs to extract the key and value and add them to the top-level data.
        """
        data = super().model_dump(*args, **kwargs)

        # Flatten extra_reasoning_details into top-level fields
        extra = data.pop("extra_reasoning_details", None)
        if extra:
            for key, value in extra.items():
                data[key] = value

        return data


class ToolMessage(BaseModel):
    role: Literal["tool"] = "tool"
    content: str
    tool_call_id: str


# Union type for all OpenAI Chat Completions messages
ChatCompletionMessage = SystemMessage | UserMessage | AssistantMessage | ToolMessage
# Allows for passing in a string directly. This is provided for convenience and is wrapped as a UserMessage.
LanguageModelInput = list[ChatCompletionMessage] | str
