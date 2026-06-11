"""Pydantic models for the mock LLM server's OpenAI-compatible wire format.

Request models use extra="allow" and optional fields throughout: litellm
sends provider-specific extras (stream_options, user, etc.) and the mock must
never 422 a request the real OpenAI API would accept.
"""

from __future__ import annotations

from typing import Any
from typing import Literal

from pydantic import BaseModel
from pydantic import ConfigDict

################################################
# Request
################################################


class ToolCallFunction(BaseModel):
    model_config = ConfigDict(extra="allow")

    name: str
    arguments: str = "{}"


class ToolCall(BaseModel):
    model_config = ConfigDict(extra="allow")

    id: str
    type: Literal["function"] = "function"
    function: ToolCallFunction


class ChatMessage(BaseModel):
    model_config = ConfigDict(extra="allow")

    role: str
    # str for normal messages, list of content parts for multimodal
    content: str | list[Any] | None = None
    tool_calls: list[ToolCall] | None = None
    tool_call_id: str | None = None


class ToolFunctionDefinition(BaseModel):
    model_config = ConfigDict(extra="allow")

    name: str
    description: str | None = None
    parameters: dict[str, Any] = {}


class ToolDefinition(BaseModel):
    model_config = ConfigDict(extra="allow")

    type: str = "function"
    function: ToolFunctionDefinition


class ChatCompletionRequest(BaseModel):
    model_config = ConfigDict(extra="allow")

    model: str = "mock-model"
    stream: bool = False
    messages: list[ChatMessage] = []
    tools: list[ToolDefinition] | None = None
    # "auto" | "none" | "required" | {"type": "function", "function": {...}}
    tool_choice: str | dict[str, Any] | None = None
    max_tokens: int | None = None
    max_completion_tokens: int | None = None

    @property
    def effective_max_tokens(self) -> int | None:
        return self.max_tokens or self.max_completion_tokens


################################################
# Non-streaming response
################################################


class Usage(BaseModel):
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int


class AssistantMessage(BaseModel):
    role: Literal["assistant"] = "assistant"
    content: str | None = None
    tool_calls: list[ToolCall] | None = None


class Choice(BaseModel):
    index: int = 0
    message: AssistantMessage
    finish_reason: str


class ChatCompletionResponse(BaseModel):
    id: str
    object: Literal["chat.completion"] = "chat.completion"
    created: int
    model: str
    choices: list[Choice]
    usage: Usage


################################################
# Streaming chunks
################################################


class StreamToolCallFunction(BaseModel):
    name: str | None = None
    arguments: str | None = None


class StreamToolCall(BaseModel):
    index: int
    id: str | None = None
    type: Literal["function"] | None = None
    function: StreamToolCallFunction


class ChunkDelta(BaseModel):
    role: str | None = None
    content: str | None = None
    tool_calls: list[StreamToolCall] | None = None


class ChunkChoice(BaseModel):
    index: int = 0
    delta: ChunkDelta
    finish_reason: str | None = None


class ChatCompletionChunk(BaseModel):
    id: str
    object: Literal["chat.completion.chunk"] = "chat.completion.chunk"
    created: int
    model: str
    choices: list[ChunkChoice]
