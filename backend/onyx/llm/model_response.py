from __future__ import annotations

from typing import Any
from typing import List
from typing import TYPE_CHECKING

from pydantic import BaseModel
from pydantic import Field


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


if TYPE_CHECKING:
    from litellm.types.utils import ModelResponseStream as LiteLLMModelResponseStream


class Message(BaseModel):
    content: str | None = None
    role: str = "assistant"
    tool_calls: List[ChatCompletionMessageToolCall] | None = None
    reasoning_content: str | None = None


class Choice(BaseModel):
    finish_reason: str | None = None
    index: int = 0
    message: Message = Field(default_factory=Message)


class ModelResponse(BaseModel):
    id: str
    created: str
    choice: Choice
    usage: Usage | None = None


if TYPE_CHECKING:
    from litellm.types.utils import (
        ModelResponse as LiteLLMModelResponse,
        ModelResponseStream as LiteLLMModelResponseStream,
    )


def _parse_function_call(
    function_payload: dict[str, Any] | None,
) -> FunctionCall | None:
    """Parse a function call payload into a FunctionCall object."""
    if not function_payload or not isinstance(function_payload, dict):
        return None
    return FunctionCall(
        arguments=function_payload.get("arguments"),
        name=function_payload.get("name"),
    )


def _parse_delta_tool_calls(
    tool_calls: list[dict[str, Any]] | None,
) -> list[ChatCompletionDeltaToolCall]:
    """Parse tool calls for streaming responses (delta format)."""
    if not tool_calls:
        return []

    parsed_tool_calls: list[ChatCompletionDeltaToolCall] = []
    for tool_call in tool_calls:
        parsed_tool_calls.append(
            ChatCompletionDeltaToolCall(
                id=tool_call.get("id"),
                index=tool_call.get("index", 0),
                type=tool_call.get("type", "function"),
                function=_parse_function_call(tool_call.get("function")),
            )
        )
    return parsed_tool_calls


def _parse_message_tool_calls(
    tool_calls: list[dict[str, Any]] | None,
) -> list[ChatCompletionMessageToolCall]:
    """Parse tool calls for non-streaming responses (message format)."""
    if not tool_calls:
        return []

    parsed_tool_calls: list[ChatCompletionMessageToolCall] = []
    for tool_call in tool_calls:
        function_call = _parse_function_call(tool_call.get("function"))
        if not function_call:
            continue

        parsed_tool_calls.append(
            ChatCompletionMessageToolCall(
                id=tool_call.get("id", ""),
                type=tool_call.get("type", "function"),
                function=function_call,
            )
        )
    return parsed_tool_calls


def _validate_and_extract_base_fields(
    response_data: dict[str, Any], error_prefix: str
) -> tuple[str, str, dict[str, Any]]:
    """
    Validate and extract common fields (id, created, first choice) from a LiteLLM response.

    Returns:
        Tuple of (id, created, choice_data)
    """
    response_id = response_data.get("id")
    created = response_data.get("created")
    if response_id is None or created is None:
        raise ValueError(f"{error_prefix} must include 'id' and 'created'.")

    choices: list[dict[str, Any]] = response_data.get("choices") or []
    if not choices:
        raise ValueError(f"{error_prefix} must include at least one choice.")

    return str(response_id), str(created), choices[0] or {}


def _usage_from_usage_data(usage_data: dict[str, Any]) -> Usage:
    # NOTE: sometimes the usage data dictionary has these keys and the values are None
    # hence the "or 0" instead of just using default values
    return Usage(
        completion_tokens=usage_data.get("completion_tokens") or 0,
        prompt_tokens=usage_data.get("prompt_tokens") or 0,
        total_tokens=usage_data.get("total_tokens") or 0,
        cache_creation_input_tokens=usage_data.get("cache_creation_input_tokens") or 0,
        cache_read_input_tokens=usage_data.get(
            "cache_read_input_tokens",
            (usage_data.get("prompt_tokens_details") or {}).get("cached_tokens"),
        )
        or 0,
    )


def from_litellm_model_response_stream(
    response: "LiteLLMModelResponseStream",
) -> ModelResponseStream:
    """
    Convert a LiteLLM ModelResponseStream into the simplified Onyx representation.
    """
    response_data = response.model_dump()
    response_id, created, choice_data = _validate_and_extract_base_fields(
        response_data, "LiteLLM response stream"
    )

    delta_data: dict[str, Any] = choice_data.get("delta") or {}
    parsed_delta = Delta(
        content=delta_data.get("content"),
        reasoning_content=delta_data.get("reasoning_content"),
        tool_calls=_parse_delta_tool_calls(delta_data.get("tool_calls")),
    )

    streaming_choice = StreamingChoice(
        finish_reason=choice_data.get("finish_reason"),
        index=choice_data.get("index", 0),
        delta=parsed_delta,
    )

    usage_data = response_data.get("usage")
    return ModelResponseStream(
        id=response_id,
        created=created,
        choice=streaming_choice,
        usage=(_usage_from_usage_data(usage_data) if usage_data else None),
    )


def from_litellm_model_response(
    response: "LiteLLMModelResponse",
) -> ModelResponse:
    """
    Convert a LiteLLM ModelResponse into the simplified Onyx representation.
    """
    response_data = response.model_dump()
    response_id, created, choice_data = _validate_and_extract_base_fields(
        response_data, "LiteLLM response"
    )

    message_data: dict[str, Any] = choice_data.get("message") or {}
    parsed_tool_calls = _parse_message_tool_calls(message_data.get("tool_calls"))

    message = Message(
        content=message_data.get("content"),
        role=message_data.get("role", "assistant"),
        tool_calls=parsed_tool_calls if parsed_tool_calls else None,
        reasoning_content=message_data.get("reasoning_content"),
    )

    choice = Choice(
        finish_reason=choice_data.get("finish_reason"),
        index=choice_data.get("index", 0),
        message=message,
    )

    usage_data = response_data.get("usage")
    return ModelResponse(
        id=response_id,
        created=created,
        choice=choice,
        usage=(_usage_from_usage_data(usage_data) if usage_data else None),
    )
