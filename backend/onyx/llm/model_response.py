from __future__ import annotations

from typing import List

from pydantic import BaseModel, Field

from onyx.llm.models import AnyThinkingBlock
from onyx.utils.logger import setup_logger

logger = setup_logger()


class FunctionCall(BaseModel):
    arguments: str | None = None
    name: str | None = None


class ChatCompletionMessageToolCall(BaseModel):
    id: str
    type: str = "function"
    function: FunctionCall


class ChatCompletionDeltaToolCall(BaseModel):
    id: str | None = None
    index: int = 0
    type: str = "function"
    function: FunctionCall | None = None


class Delta(BaseModel):
    content: str | None = None
    reasoning_content: str | None = None
    thinking_blocks: List[AnyThinkingBlock] | None = None
    tool_calls: List[ChatCompletionDeltaToolCall] = Field(default_factory=list)


class StreamingChoice(BaseModel):
    finish_reason: str | None = None
    index: int = 0
    delta: Delta = Field(default_factory=Delta)


class Usage(BaseModel):
    completion_tokens: int
    prompt_tokens: int
    total_tokens: int
    cache_creation_input_tokens: int
    cache_read_input_tokens: int


class ModelResponseStream(BaseModel):
    id: str
    created: str
    choice: StreamingChoice
    usage: Usage | None = None


class Message(BaseModel):
    content: str | None = None
    role: str = "assistant"
    tool_calls: List[ChatCompletionMessageToolCall] | None = None
    reasoning_content: str | None = None
    thinking_blocks: List[AnyThinkingBlock] | None = None


class Choice(BaseModel):
    finish_reason: str | None = None
    index: int = 0
    message: Message = Field(default_factory=Message)


class ModelResponse(BaseModel):
    id: str
    created: str
    choice: Choice
    usage: Usage | None = None
