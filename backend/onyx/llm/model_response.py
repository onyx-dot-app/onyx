from __future__ import annotations

from typing import Any
from typing import List
from typing import TYPE_CHECKING

from pydantic import BaseModel
from pydantic import Field


class FunctionCall(BaseModel):
    arguments: str | None = None
    name: str | None = None


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
    created: int
    choice: StreamingChoice


if TYPE_CHECKING:
    from litellm.types.utils import ModelResponseStream as LiteLLMModelResponseStream


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
        created=int(created),
        choice=streaming_choice,
    )
