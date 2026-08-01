from collections.abc import Sequence
from typing import Any, Literal, TypeAlias

from pydantic import BaseModel, ConfigDict, Field

from onyx.llm.model_response import ModelResponse, ModelResponseStream, Usage

GatewayModality: TypeAlias = Literal["text", "audio", "image", "video", "pdf"]


class GatewayModelCapabilities(BaseModel):
    """Effective capabilities exposed by the Onyx OpenAI-compatible gateway."""

    model_config = ConfigDict(frozen=True)

    input_modalities: tuple[GatewayModality, ...] = ("text",)
    output_modalities: tuple[GatewayModality, ...] = ("text",)
    supports_reasoning: bool = False
    supports_tool_calls: bool = True
    supports_temperature: bool = False
    supports_interleaved_reasoning: bool = False


class GatewayModelDescriptor(BaseModel):
    """Provider-neutral model metadata shared by gateway protocol adapters."""

    model_config = ConfigDict(frozen=True)

    id: str
    display_name: str
    provider: str
    capabilities: GatewayModelCapabilities = Field(
        default_factory=GatewayModelCapabilities
    )
    max_input_tokens: int | None = None
    max_output_tokens: int | None = None


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


class ModelListEntry(_WireModel):
    id: str
    object: Literal["model"] = "model"
    owned_by: str

    @classmethod
    def from_descriptor(cls, descriptor: GatewayModelDescriptor) -> "ModelListEntry":
        return cls(id=descriptor.id, object="model", owned_by=descriptor.provider)


class ModelListResponse(_WireModel):
    object: Literal["list"] = "list"
    data: list[ModelListEntry]

    @classmethod
    def from_catalog(
        cls, catalog: Sequence[GatewayModelDescriptor]
    ) -> "ModelListResponse":
        return cls(
            object="list",
            data=[ModelListEntry.from_descriptor(d) for d in catalog],
        )


class ResponsesRequest(BaseModel):
    """Codex sends ``store: false`` and no ``previous_response_id``, so
    conversation persistence is intentionally not implemented."""

    model_config = ConfigDict(extra="allow")

    model: str
    input: str | list[dict[str, Any]] = Field(default_factory=list)
    instructions: str | None = None
    tools: list[dict[str, Any]] | None = None
    tool_choice: Any = None
    stream: bool = False
    max_output_tokens: int | None = None
    temperature: float | None = None
    reasoning: dict[str, Any] | None = None


# Subset of the Responses error enum we can actually produce; the schema has
# no timeout code, so timeouts report as server_error.
ResponsesErrorCode: TypeAlias = Literal["server_error", "rate_limit_exceeded"]


class ResponsesOutputTextPart(_WireModel):
    type: Literal["output_text"] = "output_text"
    text: str
    annotations: list[Any] = Field(default_factory=list)

    @classmethod
    def create(cls, *, text: str) -> "ResponsesOutputTextPart":
        return cls(type="output_text", text=text, annotations=[])


class ResponsesMessageItem(_WireModel):
    type: Literal["message"] = "message"
    id: str
    status: str
    role: Literal["assistant"] = "assistant"
    content: list[ResponsesOutputTextPart]

    @classmethod
    def create(
        cls, *, id: str, status: str, content: list[ResponsesOutputTextPart]
    ) -> "ResponsesMessageItem":
        return cls(
            type="message", id=id, status=status, role="assistant", content=content
        )


class ResponsesFunctionCallItem(_WireModel):
    type: Literal["function_call"] = "function_call"
    id: str
    call_id: str
    name: str
    arguments: str
    status: str = "completed"

    @classmethod
    def create(
        cls, *, id: str, call_id: str, name: str, arguments: str
    ) -> "ResponsesFunctionCallItem":
        return cls(
            type="function_call",
            id=id,
            call_id=call_id,
            name=name,
            arguments=arguments,
            status="completed",
        )


ResponsesOutputItem: TypeAlias = ResponsesMessageItem | ResponsesFunctionCallItem


class ResponsesUsagePayload(_WireModel):
    input_tokens: int
    output_tokens: int
    total_tokens: int

    @classmethod
    def from_usage(cls, usage: Usage) -> "ResponsesUsagePayload":
        return cls(
            input_tokens=usage.prompt_tokens,
            output_tokens=usage.completion_tokens,
            total_tokens=usage.total_tokens,
        )


class ResponsesObjectPayload(_WireModel):
    id: str
    object: Literal["response"] = "response"
    created_at: int
    status: str
    model: str
    output: list[ResponsesOutputItem]
    # Required by the Responses schema even when empty, so a strict SDK client
    # can parse the object; we do not echo the request's tools.
    parallel_tool_calls: bool = True
    tool_choice: str = "auto"
    tools: list[dict[str, Any]] = Field(default_factory=list)
    usage: ResponsesUsagePayload | None = None
    error: dict[str, Any] | None = None

    @classmethod
    def from_parts(
        cls,
        *,
        response_id: str,
        created_at: int,
        model: str,
        status: str,
        output: list[ResponsesOutputItem],
        usage: Usage | None = None,
    ) -> "ResponsesObjectPayload":
        kwargs: dict[str, Any] = {}
        if usage is not None:
            kwargs["usage"] = ResponsesUsagePayload.from_usage(usage)
        return cls(
            id=response_id,
            object="response",
            created_at=created_at,
            status=status,
            model=model,
            output=output,
            parallel_tool_calls=True,
            tool_choice="auto",
            tools=[],
            **kwargs,
        )

    @classmethod
    def failed(
        cls,
        *,
        response_id: str,
        created_at: int,
        model: str,
        message: str,
        code: ResponsesErrorCode = "server_error",
    ) -> "ResponsesObjectPayload":
        return cls(
            id=response_id,
            object="response",
            created_at=created_at,
            status="failed",
            model=model,
            output=[],
            parallel_tool_calls=True,
            tool_choice="auto",
            tools=[],
            error={"code": code, "message": message},
        )


class ResponsesCreatedEvent(_WireModel):
    type: Literal["response.created"] = "response.created"
    response: ResponsesObjectPayload

    @classmethod
    def create(cls, response: ResponsesObjectPayload) -> "ResponsesCreatedEvent":
        return cls(type="response.created", response=response)


class ResponsesOutputTextDeltaEvent(_WireModel):
    type: Literal["response.output_text.delta"] = "response.output_text.delta"
    item_id: str
    output_index: int = 0
    content_index: int = 0
    delta: str
    logprobs: list[Any] = Field(default_factory=list)

    @classmethod
    def create(cls, *, item_id: str, delta: str) -> "ResponsesOutputTextDeltaEvent":
        return cls(
            type="response.output_text.delta",
            item_id=item_id,
            output_index=0,
            content_index=0,
            delta=delta,
            logprobs=[],
        )


class ResponsesOutputItemAddedEvent(_WireModel):
    type: Literal["response.output_item.added"] = "response.output_item.added"
    output_index: int = 0
    item: ResponsesOutputItem

    @classmethod
    def create(
        cls, *, output_index: int, item: ResponsesOutputItem
    ) -> "ResponsesOutputItemAddedEvent":
        return cls(
            type="response.output_item.added", output_index=output_index, item=item
        )


class ResponsesOutputItemDoneEvent(_WireModel):
    type: Literal["response.output_item.done"] = "response.output_item.done"
    output_index: int = 0
    item: ResponsesOutputItem

    @classmethod
    def create(
        cls, *, output_index: int, item: ResponsesOutputItem
    ) -> "ResponsesOutputItemDoneEvent":
        return cls(
            type="response.output_item.done", output_index=output_index, item=item
        )


class ResponsesContentPartAddedEvent(_WireModel):
    type: Literal["response.content_part.added"] = "response.content_part.added"
    item_id: str
    output_index: int = 0
    content_index: int = 0
    part: ResponsesOutputTextPart

    @classmethod
    def create(
        cls, *, item_id: str, output_index: int, part: ResponsesOutputTextPart
    ) -> "ResponsesContentPartAddedEvent":
        return cls(
            type="response.content_part.added",
            item_id=item_id,
            output_index=output_index,
            content_index=0,
            part=part,
        )


class ResponsesContentPartDoneEvent(_WireModel):
    type: Literal["response.content_part.done"] = "response.content_part.done"
    item_id: str
    output_index: int = 0
    content_index: int = 0
    part: ResponsesOutputTextPart

    @classmethod
    def create(
        cls, *, item_id: str, output_index: int, part: ResponsesOutputTextPart
    ) -> "ResponsesContentPartDoneEvent":
        return cls(
            type="response.content_part.done",
            item_id=item_id,
            output_index=output_index,
            content_index=0,
            part=part,
        )


class ResponsesOutputTextDoneEvent(_WireModel):
    type: Literal["response.output_text.done"] = "response.output_text.done"
    item_id: str
    output_index: int = 0
    content_index: int = 0
    text: str
    logprobs: list[Any] = Field(default_factory=list)

    @classmethod
    def create(
        cls, *, item_id: str, output_index: int, text: str
    ) -> "ResponsesOutputTextDoneEvent":
        return cls(
            type="response.output_text.done",
            item_id=item_id,
            output_index=output_index,
            content_index=0,
            text=text,
            logprobs=[],
        )


class ResponsesFunctionCallArgumentsDoneEvent(_WireModel):
    type: Literal["response.function_call_arguments.done"] = (
        "response.function_call_arguments.done"
    )
    item_id: str
    output_index: int = 0
    arguments: str
    name: str

    @classmethod
    def create(
        cls, *, item_id: str, output_index: int, arguments: str, name: str
    ) -> "ResponsesFunctionCallArgumentsDoneEvent":
        return cls(
            type="response.function_call_arguments.done",
            item_id=item_id,
            output_index=output_index,
            arguments=arguments,
            name=name,
        )


class ResponsesCompletedEvent(_WireModel):
    type: Literal["response.completed"] = "response.completed"
    response: ResponsesObjectPayload

    @classmethod
    def create(cls, response: ResponsesObjectPayload) -> "ResponsesCompletedEvent":
        return cls(type="response.completed", response=response)


class ResponsesFailedEvent(_WireModel):
    type: Literal["response.failed"] = "response.failed"
    response: ResponsesObjectPayload

    @classmethod
    def create(cls, response: ResponsesObjectPayload) -> "ResponsesFailedEvent":
        return cls(type="response.failed", response=response)
