from __future__ import annotations

from collections.abc import Iterator
from collections.abc import Mapping
from collections.abc import Sequence
from contextlib import contextmanager
from typing import Any
from typing import cast

from onyx.llm.interfaces import LLM
from onyx.llm.model_response import ModelResponse
from onyx.llm.models import ToolCall
from onyx.tracing.framework.create import generation_span
from onyx.tracing.framework.span_data import GenerationSpanData
from onyx.tracing.framework.spans import Span


def build_llm_model_config(llm: LLM, flow: str | None = None) -> dict[str, str]:
    model_config: dict[str, str] = {
        "base_url": str(llm.config.api_base or ""),
        "model_provider": llm.config.model_provider,
    }
    if flow:
        model_config["flow"] = flow
    return model_config


@contextmanager
def llm_generation_span(
    llm: LLM,
    flow: str | None,
    input_messages: Sequence[Any] | Any | None = None,
    parent: Any | None = None,
) -> Iterator[Span[GenerationSpanData]]:
    with generation_span(
        model=llm.config.model_name,
        model_config=build_llm_model_config(llm, flow),
        parent=parent,
    ) as span:
        if input_messages is not None:
            if isinstance(input_messages, Sequence) and not isinstance(
                input_messages, (str, bytes)
            ):
                normalized_messages = input_messages
            else:
                normalized_messages = [input_messages]
            span.span_data.input = cast(
                Sequence[Mapping[str, Any]], normalized_messages
            )
        yield span


def record_llm_response(
    span: Span[GenerationSpanData],
    response: ModelResponse,
) -> None:
    """Standard way to record a complete LLM response to a generation span.

    Extracts content, reasoning, tool_calls, and usage automatically from the
    ModelResponse object.

    Args:
        span: The generation span to record to.
        response: The ModelResponse from the LLM.
    """
    message = response.choice.message

    # Build output dict matching AssistantMessage format
    output_dict: dict[str, Any] = {"role": "assistant"}

    if message.content is not None:
        output_dict["content"] = message.content

    if message.tool_calls:
        output_dict["tool_calls"] = [tc.model_dump() for tc in message.tool_calls]

    span.span_data.output = [output_dict]

    # Record reasoning (extended thinking from reasoning models)
    if message.reasoning_content:
        span.span_data.reasoning = message.reasoning_content

    # Record usage
    if response.usage:
        usage_dict = _build_usage_dict(response.usage)
        if usage_dict:
            span.span_data.usage = usage_dict


def record_llm_span_output(
    span: Span[GenerationSpanData],
    output: str | Sequence[Mapping[str, Any]] | None,
    usage: Any | None = None,
    reasoning: str | None = None,
    tool_calls: list[ToolCall] | None = None,
) -> None:
    """Record LLM output to a generation span for streaming scenarios.

    This function is useful for streaming where content, reasoning, tool_calls,
    and usage are accumulated separately.

    Args:
        span: The generation span to record to.
        output: The text output or list of message dicts.
        usage: Optional usage information.
        reasoning: Optional reasoning/extended thinking content.
        tool_calls: Optional list of tool calls.
    """
    if output is None:
        output_dict: dict[str, Any] = {"role": "assistant", "content": None}
        if tool_calls:
            output_dict["tool_calls"] = [tc.model_dump() for tc in tool_calls]
        span.span_data.output = [output_dict]
    elif isinstance(output, str):
        output_dict = {"role": "assistant", "content": output}
        if tool_calls:
            output_dict["tool_calls"] = [tc.model_dump() for tc in tool_calls]
        span.span_data.output = [output_dict]
    else:
        span.span_data.output = cast(Sequence[Mapping[str, Any]], output)

    usage_dict = _build_usage_dict(usage)
    if usage_dict:
        span.span_data.usage = usage_dict

    if reasoning:
        span.span_data.reasoning = reasoning


def _build_usage_dict(usage: Any | None) -> dict[str, Any] | None:
    if not usage:
        return None
    if isinstance(usage, dict):
        return usage

    usage_dict: dict[str, Any] = {}
    prompt_tokens = getattr(usage, "prompt_tokens", None)
    completion_tokens = getattr(usage, "completion_tokens", None)
    input_tokens = getattr(usage, "input_tokens", None)
    output_tokens = getattr(usage, "output_tokens", None)
    total_tokens = getattr(usage, "total_tokens", None)
    cache_read_input_tokens = getattr(usage, "cache_read_input_tokens", None)
    cache_creation_input_tokens = getattr(usage, "cache_creation_input_tokens", None)

    if prompt_tokens is not None:
        usage_dict["input_tokens"] = prompt_tokens
    elif input_tokens is not None:
        usage_dict["input_tokens"] = input_tokens
    if completion_tokens is not None:
        usage_dict["output_tokens"] = completion_tokens
    elif output_tokens is not None:
        usage_dict["output_tokens"] = output_tokens
    if total_tokens is not None:
        usage_dict["total_tokens"] = total_tokens
    if cache_read_input_tokens is not None:
        usage_dict["cache_read_input_tokens"] = cache_read_input_tokens
    if cache_creation_input_tokens is not None:
        usage_dict["cache_creation_input_tokens"] = cache_creation_input_tokens

    return usage_dict or None
