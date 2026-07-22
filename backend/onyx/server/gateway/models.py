from typing import Any, Literal

from pydantic import BaseModel, ConfigDict

from onyx.llm.model_response import ModelResponse, ModelResponseStream, Usage


class ChatCompletionRequest(BaseModel):
    """Unknown params (e.g. ``reasoningSummary`` from opencode) must be
    accepted and ignored, not rejected."""

    model_config = ConfigDict(extra="allow")

    model: str
    messages: list[dict[str, Any]]
    tools: list[dict[str, Any]] | None = None
    tool_choice: Any = None
    stream: bool = False
    max_tokens: int | None = None
    max_completion_tokens: int | None = None
    temperature: float | None = None
    reasoning_effort: str | None = None
    response_format: dict[str, Any] | None = None


def _created_epoch(created: str) -> int:
    try:
        return int(float(created))
    except (TypeError, ValueError):
        return 0


class _WireModel(BaseModel):
    """OpenAI-compatible response DTO. The wire contract has field-PRESENCE
    semantics (some keys must be present even when null, others absent — not
    null — when empty), encoded via ``model_fields_set``: factory methods
    assign always-present fields explicitly and never assign absent-when-empty
    fields, and ``to_wire`` serializes with ``exclude_unset``. Frozen so no
    later assignment can corrupt the unset state; construct ONLY through the
    factory methods."""

    model_config = ConfigDict(frozen=True)

    def to_wire(self) -> dict[str, Any]:
        return self.model_dump(mode="json", exclude_unset=True)


class UsagePayload(_WireModel):
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    prompt_tokens_details: dict[str, int]

    @classmethod
    def from_usage(cls, usage: Usage) -> "UsagePayload":
        return cls(
            prompt_tokens=usage.prompt_tokens,
            completion_tokens=usage.completion_tokens,
            total_tokens=usage.total_tokens,
            prompt_tokens_details={"cached_tokens": usage.cache_read_input_tokens},
        )


class AssistantMessagePayload(_WireModel):
    role: str
    content: str | None
    reasoning_content: str | None = None
    tool_calls: list[dict[str, Any]] | None = None


class CompletionChoicePayload(_WireModel):
    index: int
    message: AssistantMessagePayload
    finish_reason: str | None


class ChatCompletionResponse(_WireModel):
    id: str
    object: Literal["chat.completion"] = "chat.completion"
    created: int
    model: str
    choices: list[CompletionChoicePayload]
    usage: UsagePayload | None = None

    @classmethod
    def from_model_response(
        cls, response: ModelResponse, model: str
    ) -> "ChatCompletionResponse":
        message_kwargs: dict[str, Any] = {}
        if response.choice.message.reasoning_content:
            message_kwargs["reasoning_content"] = (
                response.choice.message.reasoning_content
            )
        if response.choice.message.tool_calls:
            message_kwargs["tool_calls"] = [
                tc.model_dump() for tc in response.choice.message.tool_calls
            ]
        response_kwargs: dict[str, Any] = {}
        if response.usage is not None:
            response_kwargs["usage"] = UsagePayload.from_usage(response.usage)
        return cls(
            id=response.id,
            object="chat.completion",
            created=_created_epoch(response.created),
            model=model,
            choices=[
                CompletionChoicePayload(
                    index=response.choice.index,
                    message=AssistantMessagePayload(
                        role=response.choice.message.role,
                        content=response.choice.message.content,
                        **message_kwargs,
                    ),
                    finish_reason=response.choice.finish_reason,
                )
            ],
            **response_kwargs,
        )


class ChunkDeltaPayload(_WireModel):
    role: str | None = None
    content: str | None = None
    reasoning_content: str | None = None
    tool_calls: list[dict[str, Any]] | None = None


class ChunkChoicePayload(_WireModel):
    index: int
    delta: ChunkDeltaPayload
    finish_reason: str | None


class ChatCompletionChunk(_WireModel):
    id: str
    object: Literal["chat.completion.chunk"] = "chat.completion.chunk"
    created: int
    model: str
    choices: list[ChunkChoicePayload]
    usage: UsagePayload | None = None

    @classmethod
    def from_stream_chunk(
        cls, chunk: ModelResponseStream, model: str, include_role: bool
    ) -> "ChatCompletionChunk":
        delta_kwargs: dict[str, Any] = {}
        if include_role:
            delta_kwargs["role"] = "assistant"
        if chunk.choice.delta.content is not None:
            delta_kwargs["content"] = chunk.choice.delta.content
        if chunk.choice.delta.reasoning_content is not None:
            delta_kwargs["reasoning_content"] = chunk.choice.delta.reasoning_content
        if chunk.choice.delta.tool_calls:
            delta_kwargs["tool_calls"] = [
                tc.model_dump(exclude_none=True) for tc in chunk.choice.delta.tool_calls
            ]
        chunk_kwargs: dict[str, Any] = {}
        if chunk.usage is not None:
            chunk_kwargs["usage"] = UsagePayload.from_usage(chunk.usage)
        return cls(
            id=chunk.id,
            object="chat.completion.chunk",
            created=_created_epoch(chunk.created),
            model=model,
            choices=[
                ChunkChoicePayload(
                    index=chunk.choice.index,
                    delta=ChunkDeltaPayload(**delta_kwargs),
                    finish_reason=chunk.choice.finish_reason,
                )
            ],
            **chunk_kwargs,
        )
