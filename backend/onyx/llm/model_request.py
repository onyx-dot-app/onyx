"""Provider request messages in the OpenAI Chat Completions shape."""

from typing import Literal

from pydantic import BaseModel

from onyx.llm.models import AnyThinkingBlock, ContentPart

# Specifically for OpenAI models, this prefix needs to be in place for the model to output markdown and correct styling
CODE_BLOCK_MARKDOWN = "Formatting re-enabled. "


# Tool call structures
class RequestFunctionCall(BaseModel):
    name: str
    arguments: str


class ToolCall(BaseModel):
    type: Literal["function"] = "function"
    id: str
    function: RequestFunctionCall


# Message types


# Base class for all cacheable messages
class CacheableMessage(BaseModel):
    # Some providers support prompt caching controls at the message level (passed through via LiteLLM).
    cache_control: dict | None = None


class SystemMessage(CacheableMessage):
    role: Literal["system"] = "system"
    content: str


class UserMessage(CacheableMessage):
    role: Literal["user"] = "user"
    content: str | list[ContentPart]


class AssistantMessage(CacheableMessage):
    role: Literal["assistant"] = "assistant"
    content: str | None = None
    tool_calls: list[ToolCall] | None = None
    thinking_blocks: list[AnyThinkingBlock] | None = None


class ToolMessage(CacheableMessage):
    role: Literal["tool"] = "tool"
    content: str
    tool_call_id: str


# Union type for all OpenAI Chat Completions messages
ChatCompletionMessage = SystemMessage | UserMessage | AssistantMessage | ToolMessage
# Allows for passing in a string directly. This is provided for convenience and is wrapped as a UserMessage.
LanguageModelInput = list[ChatCompletionMessage] | ChatCompletionMessage
