from __future__ import annotations

from typing import TYPE_CHECKING, Any, List

from pydantic import BaseModel, Field

from onyx.llm.models import (
    AnyThinkingBlock,
    RedactedThinkingBlock,
    ThinkingBlock,
    Usage,
)
from onyx.utils.logger import setup_logger

logger = setup_logger()


class ResponseFunctionCall(BaseModel):
    arguments: str | None = None
    name: str | None = None


class ChatCompletionMessageToolCall(BaseModel):
    id: str
    type: str = "function"
    function: ResponseFunctionCall


class ChatCompletionDeltaToolCall(BaseModel):
    id: str | None = None
    index: int = 0
    type: str = "function"
    function: ResponseFunctionCall | None = None


class Delta(BaseModel):
    content: str | None = None
    reasoning_content: str | None = None
    thinking_blocks: List[AnyThinkingBlock] | None = None
    tool_calls: List[ChatCompletionDeltaToolCall] = Field(default_factory=list)


class StreamingChoice(BaseModel):
    finish_reason: str | None = None
    index: int = 0
    delta: Delta = Field(default_factory=Delta)


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


if TYPE_CHECKING:
    from litellm.types.utils import ModelResponse as LiteLLMModelResponse
    from litellm.types.utils import ModelResponseStream as LiteLLMModelResponseStream


def _parse_function_call(
    function_payload: dict[str, Any] | None,
) -> ResponseFunctionCall | None:
    """Parse a function call payload into a ResponseFunctionCall object."""
    if not function_payload or not isinstance(function_payload, dict):
        return None
    return ResponseFunctionCall(
        arguments=function_payload.get("arguments"),
        name=function_payload.get("name"),
    )


def _parse_delta_tool_calls(
    tool_calls: list[dict[str, Any]] | None,
) -> list[ChatCompletionDeltaToolCall]:
    """Parse tool calls for streaming responses (delta format)."""
    if not tool_calls:
        return []

    parsed_tool_calls: list[ChatCompletionDeltaToolCall] = [
        ChatCompletionDeltaToolCall(
            id=tool_call.get("id"),
            index=tool_call.get("index", 0),
            type=tool_call.get("type", "function"),
            function=_parse_function_call(tool_call.get("function")),
        )
        for tool_call in tool_calls
    ]
    return parsed_tool_calls


def _parse_thinking_blocks(
    thinking_blocks: list[dict[str, Any]] | None,
) -> list[AnyThinkingBlock] | None:
    if not thinking_blocks:
        return None

    parsed: list[AnyThinkingBlock] = []
    for block in thinking_blocks:
        if not isinstance(block, dict):
            logger.warning(
                "Dropping malformed thinking block of type %s", type(block).__name__
            )
            continue
        if block.get("type") == "redacted_thinking":
            parsed.append(RedactedThinkingBlock(data=block.get("data") or ""))
        else:
            parsed.append(
                ThinkingBlock(
                    thinking=block.get("thinking") or "",
                    signature=block.get("signature"),
                )
            )
    return parsed or None


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


def _extract_id_and_created(
    response_data: dict[str, Any], error_prefix: str
) -> tuple[str, str]:
    response_id = response_data.get("id")
    created = response_data.get("created")
    if response_id is None or created is None:
        raise ValueError(f"{error_prefix} must include 'id' and 'created'.")
    return str(response_id), str(created)


def _merge_choices_into_one(
    response_data: dict[str, Any], error_prefix: str
) -> dict[str, Any]:
    """Collapse a response's ``choices`` into the single answer they describe.

    ``choices`` normally holds one entry per requested completion, and Onyx only
    ever requests one. litellm's OpenAI-responses bridge (non-streamed) is the
    exception: it emits one choice per message content part, then one holding
    every tool call. Reading ``choices[0]`` drops the tool calls, and on
    gpt-5.4+ it can return a preamble instead of the answer.

    Upstream: BerriAI/litellm#37299, open PRs #33931 and #41123 (unfixed in
    1.102.1). Once a single choice comes back, this is a pass-through.

    Merging is safe because Onyx never sets ``n``: more than one choice always
    means a split answer, never alternative answers.
    """
    choices: list[dict[str, Any]] = response_data.get("choices") or []
    if not choices:
        raise ValueError(f"{error_prefix} must include at least one choice.")
    if len(choices) == 1:
        return choices[0] or {}

    messages = [(choice or {}).get("message") or {} for choice in choices]
    reasonings = [message.get("reasoning_content") for message in messages]
    # Kept as sent, repeats included. gpt-5.4+ sometimes re-sends a message
    # item, but a choice carries no item id, so a resend cannot be told apart
    # from text that really repeats. The streamed path keeps resends too
    # (litellm#41117 is open), so both transports return the same text.
    merged_text = "".join(
        message["content"] for message in messages if message.get("content")
    )
    # The bridge appends the tool-call choice after the text ones, so the last
    # stated finish_reason is the one describing how the answer ended.
    finish_reasons = [
        (choice or {}).get("finish_reason")
        for choice in choices
        if (choice or {}).get("finish_reason")
    ]

    merged_message: dict[str, Any] = {
        "role": next(
            (message["role"] for message in messages if message.get("role")),
            "assistant",
        ),
        "content": merged_text or None,
        "tool_calls": [
            tool_call
            for message in messages
            for tool_call in (message.get("tool_calls") or [])
        ]
        or None,
        "reasoning_content": "\n\n".join(
            reasoning for reasoning in reasonings if reasoning
        )
        or None,
        "thinking_blocks": [
            block
            for message in messages
            for block in (message.get("thinking_blocks") or [])
        ]
        or None,
    }
    return {
        "index": 0,
        "finish_reason": finish_reasons[-1] if finish_reasons else None,
        "message": merged_message,
    }


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
    response_id, created = _extract_id_and_created(
        response_data, "LiteLLM response stream"
    )

    # OpenAI (and other providers) emit a final usage-only chunk with an empty
    # `choices` array when stream_options.include_usage is set. Treat it as an
    # empty-delta chunk that still carries usage rather than failing the stream.
    choices: list[dict[str, Any]] = response_data.get("choices") or []
    choice_data: dict[str, Any] = (choices[0] or {}) if choices else {}

    delta_data: dict[str, Any] = choice_data.get("delta") or {}
    parsed_delta = Delta(
        content=delta_data.get("content"),
        reasoning_content=delta_data.get("reasoning_content"),
        thinking_blocks=_parse_thinking_blocks(delta_data.get("thinking_blocks")),
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
    response_id, created = _extract_id_and_created(response_data, "LiteLLM response")
    choice_data = _merge_choices_into_one(response_data, "LiteLLM response")

    message_data: dict[str, Any] = choice_data.get("message") or {}
    parsed_tool_calls = _parse_message_tool_calls(message_data.get("tool_calls"))

    message = Message(
        content=message_data.get("content"),
        role=message_data.get("role", "assistant"),
        tool_calls=parsed_tool_calls or None,
        reasoning_content=message_data.get("reasoning_content"),
        thinking_blocks=_parse_thinking_blocks(message_data.get("thinking_blocks")),
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
