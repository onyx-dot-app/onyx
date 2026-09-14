"""LiteLLM request messages, response envelopes, and streaming chunks."""

from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field, JsonValue

from onyx.llm.models import AnyThinkingBlock, ContentPart, MessageRole, Usage


class ToolType(str, Enum):
    FUNCTION = "function"


class ToolFunctionCall(BaseModel):
    """Function name and JSON arguments in an outgoing tool call."""

    name: str
    arguments: str


class ToolCall(BaseModel):
    type: Literal[ToolType.FUNCTION] = ToolType.FUNCTION
    id: str
    function: ToolFunctionCall


class CacheableMessage(BaseModel):
    # Some providers support prompt caching controls at the message level (passed through via LiteLLM).
    cache_control: dict[str, JsonValue] | None = None


class SystemMessage(CacheableMessage):
    role: Literal[MessageRole.SYSTEM] = MessageRole.SYSTEM
    content: str


class UserMessage(CacheableMessage):
    role: Literal[MessageRole.USER] = MessageRole.USER
    content: str | list[ContentPart]


class AssistantMessage(CacheableMessage):
    role: Literal[MessageRole.ASSISTANT] = MessageRole.ASSISTANT
    content: str | None = None
    tool_calls: list[ToolCall] | None = None
    thinking_blocks: list[AnyThinkingBlock] | None = None


class ToolMessage(CacheableMessage):
    role: Literal[MessageRole.TOOL] = MessageRole.TOOL
    content: str
    tool_call_id: str


ChatCompletionMessage = SystemMessage | UserMessage | AssistantMessage | ToolMessage

LanguageModelInput = list[ChatCompletionMessage] | ChatCompletionMessage


class FunctionCall(BaseModel):
    """Function fields received in a response or partial stream chunk."""

    arguments: str | None = None
    name: str | None = None


class ChatCompletionMessageToolCall(BaseModel):
    id: str
    type: Literal[ToolType.FUNCTION] = ToolType.FUNCTION
    function: FunctionCall


class ChatCompletionDeltaToolCall(BaseModel):
    id: str | None = None
    index: int = 0
    type: Literal[ToolType.FUNCTION] = ToolType.FUNCTION
    function: FunctionCall | None = None


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
