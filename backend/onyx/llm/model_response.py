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


class ModelResponseStream(BaseModel):
    id: str
    created: str
    choice: StreamingChoice


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


if TYPE_CHECKING:
    from litellm.types.utils import (
        ModelResponse as LiteLLMModelResponse,
        ModelResponseStream as LiteLLMModelResponseStream,
    )


def _parse_tool_calls(
    tool_calls: list[dict[str, Any]] | None,
) -> list[ChatCompletionDeltaToolCall]:
    parsed_tool_calls: list[ChatCompletionDeltaToolCall] = []
    if not tool_calls:
        return parsed_tool_calls

    for tool_call in tool_calls:
        function_payload = tool_call.get("function")
        function_call = (
            FunctionCall(
                arguments=function_payload.get("arguments"),
                name=function_payload.get("name"),
            )
            if isinstance(function_payload, dict)
            else None
        )
        parsed_tool_calls.append(
            ChatCompletionDeltaToolCall(
                id=tool_call.get("id"),
                index=tool_call.get("index", 0),
                type=tool_call.get("type", "function"),
                function=function_call,
            )
        )
    return parsed_tool_calls


def _parse_message_tool_calls(
    tool_calls: list[dict[str, Any]] | None,
) -> list[ChatCompletionMessageToolCall]:
    parsed_tool_calls: list[ChatCompletionMessageToolCall] = []
    if not tool_calls:
        return parsed_tool_calls

    for tool_call in tool_calls:
        function_payload = tool_call.get("function")
        if not function_payload or not isinstance(function_payload, dict):
            continue

        function_call = FunctionCall(
            arguments=function_payload.get("arguments"),
            name=function_payload.get("name"),
        )
        parsed_tool_calls.append(
            ChatCompletionMessageToolCall(
                id=tool_call.get("id", ""),
                type=tool_call.get("type", "function"),
                function=function_call,
            )
        )
    return parsed_tool_calls


def from_litellm_model_response_stream(
    response: "LiteLLMModelResponseStream",
) -> ModelResponseStream:
    """
    Convert a LiteLLM ModelResponseStream into the simplified Onyx representation.
    """

    response_data = response.model_dump()
    response_id = response_data.get("id")
    created = response_data.get("created")
    if response_id is None or created is None:
        raise ValueError("LiteLLM response stream must include 'id' and 'created'.")

    choices: list[dict[str, Any]] = response_data.get("choices") or []
    if not choices:
        raise ValueError("LiteLLM response stream must include at least one choice.")

    choice_data = choices[0] or {}
    delta_data: dict[str, Any] = choice_data.get("delta") or {}
    parsed_delta = Delta(
        content=delta_data.get("content"),
        reasoning_content=delta_data.get("reasoning_content"),
        tool_calls=_parse_tool_calls(delta_data.get("tool_calls")),
    )

    streaming_choice = StreamingChoice(
        finish_reason=choice_data.get("finish_reason"),
        index=choice_data.get("index", 0),
        delta=parsed_delta,
    )

    return ModelResponseStream(
        id=str(response_id),
        created=str(created),
        choice=streaming_choice,
    )


def from_litellm_model_response(
    response: "LiteLLMModelResponse",
) -> ModelResponse:
    """
    Convert a LiteLLM ModelResponse into the simplified Onyx representation.
    """

    response_data = response.model_dump()
    response_id = response_data.get("id")
    created = response_data.get("created")
    if response_id is None or created is None:
        raise ValueError("LiteLLM response must include 'id' and 'created'.")

    choices: list[dict[str, Any]] = response_data.get("choices") or []
    if not choices:
        raise ValueError("LiteLLM response must include at least one choice.")

    choice_data = choices[0] or {}
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

    return ModelResponse(
        id=str(response_id),
        created=str(created),
        choice=choice,
    )
