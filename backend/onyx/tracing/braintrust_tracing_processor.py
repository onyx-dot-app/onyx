import datetime
from typing import Any
from typing import Dict
from typing import Optional

import braintrust
from braintrust import NOOP_SPAN

from .processor_interface import TracingProcessor
from onyx.tracing.span_data import AgentSpanData
from onyx.tracing.span_data import FunctionSpanData
from onyx.tracing.span_data import GenerationSpanData
from onyx.tracing.span_data import SpanData
from onyx.tracing.spans import Span
from onyx.tracing.traces import Trace


def _span_type(span: Span[Any]) -> braintrust.SpanTypeAttribute:
    if span.span_data.type in ["agent"]:
        return braintrust.SpanTypeAttribute.TASK
    elif span.span_data.type in ["function"]:
        return braintrust.SpanTypeAttribute.TOOL
    elif span.span_data.type in ["generation"]:
        return braintrust.SpanTypeAttribute.LLM
    else:
        return braintrust.SpanTypeAttribute.TASK


def _span_name(span: Span[Any]) -> str:
    # TODO(sachin): span name should also come from the span_data.
    if isinstance(span.span_data, AgentSpanData) or isinstance(
        span.span_data, FunctionSpanData
    ):
        return span.span_data.name
    elif isinstance(span.span_data, GenerationSpanData):
        return "Generation"
    else:
        return "Unknown"


def _timestamp_from_maybe_iso(timestamp: Optional[str]) -> Optional[float]:
    if timestamp is None:
        return None
    return datetime.datetime.fromisoformat(timestamp).timestamp()


def _maybe_timestamp_elapsed(
    end: Optional[str], start: Optional[str]
) -> Optional[float]:
    if start is None or end is None:
        return None
    return (
        datetime.datetime.fromisoformat(end) - datetime.datetime.fromisoformat(start)
    ).total_seconds()


class BraintrustTracingProcessor(TracingProcessor):
    """
    `BraintrustTracingProcessor` is a `tracing.TracingProcessor` that logs traces to Braintrust.

    Args:
        logger: A `braintrust.Span` or `braintrust.Experiment` or `braintrust.Logger` to use for logging.
            If `None`, the current span, experiment, or logger will be selected exactly as in `braintrust.start_span`.
    """

    def __init__(self, logger: Optional[braintrust.Logger] = None):
        self._logger = logger
        self._spans: Dict[str, Span] = {}
        self._first_input: Dict[str, Any] = {}
        self._last_output: Dict[str, Any] = {}

    def on_trace_start(self, trace: Trace) -> None:
        trace_meta = trace.export() or {}
        metadata = {
            "group_id": trace_meta.get("group_id"),
            **(trace_meta.get("metadata") or {}),
        }

        current_context = braintrust.current_span()
        if current_context != NOOP_SPAN:
            self._spans[trace.trace_id] = current_context.start_span(
                name=trace.name,
                span_attributes={"type": "task", "name": trace.name},
                metadata=metadata,
            )
        elif self._logger is not None:
            self._spans[trace.trace_id] = self._logger.start_span(
                span_attributes={"type": "task", "name": trace.name},
                span_id=trace.trace_id,
                root_span_id=trace.trace_id,
                metadata=metadata,
                # TODO(sachin): Add start time when SDK provides it.
                # start_time=_timestamp_from_maybe_iso(trace.started_at),
            )
        else:
            self._spans[trace.trace_id] = braintrust.start_span(
                id=trace.trace_id,
                span_attributes={"type": "task", "name": trace.name},
                metadata=metadata,
                # TODO(sachin): Add start time when SDK provides it.
                # start_time=_timestamp_from_maybe_iso(trace.started_at),
            )

    def on_trace_end(self, trace: Trace) -> None:
        span = self._spans.pop(trace.trace_id)
        # Get the first input and last output for this specific trace
        trace_first_input = self._first_input.pop(trace.trace_id, None)
        trace_last_output = self._last_output.pop(trace.trace_id, None)
        span.log(input=trace_first_input, output=trace_last_output)
        span.end()
        # TODO(sachin): Add end time when SDK provides it.
        # span.end(_timestamp_from_maybe_iso(trace.ended_at))

    def _agent_log_data(self, span: Span[AgentSpanData]) -> Dict[str, Any]:
        return {
            "metadata": {
                "tools": span.span_data.tools,
                "handoffs": span.span_data.handoffs,
                "output_type": span.span_data.output_type,
            }
        }

    def _function_log_data(self, span: Span[FunctionSpanData]) -> Dict[str, Any]:
        return {
            "input": span.span_data.input,
            "output": span.span_data.output,
        }

    def _generation_log_data(self, span: Span[GenerationSpanData]) -> Dict[str, Any]:
        metrics = {}
        ttft = _maybe_timestamp_elapsed(span.ended_at, span.started_at)

        if ttft is not None:
            metrics["time_to_first_token"] = ttft

        usage = span.span_data.usage or {}
        if "prompt_tokens" in usage:
            metrics["prompt_tokens"] = usage["prompt_tokens"]
        elif "input_tokens" in usage:
            metrics["prompt_tokens"] = usage["input_tokens"]

        if "completion_tokens" in usage:
            metrics["completion_tokens"] = usage["completion_tokens"]
        elif "output_tokens" in usage:
            metrics["completion_tokens"] = usage["output_tokens"]

        if "total_tokens" in usage:
            metrics["tokens"] = usage["total_tokens"]
        elif "input_tokens" in usage and "output_tokens" in usage:
            metrics["tokens"] = usage["input_tokens"] + usage["output_tokens"]

        if "cache_read_input_tokens" in usage:
            metrics["prompt_cached_tokens"] = usage["cache_read_input_tokens"]
        if "cache_creation_input_tokens" in usage:
            metrics["prompt_cache_creation_tokens"] = usage[
                "cache_creation_input_tokens"
            ]

        return {
            "input": span.span_data.input,
            "output": span.span_data.output,
            "metadata": {
                "model": span.span_data.model,
                "model_config": span.span_data.model_config,
            },
            "metrics": metrics,
        }

    def _log_data(self, span: Span[Any]) -> Dict[str, Any]:
        if isinstance(span.span_data, AgentSpanData):
            return self._agent_log_data(span)
        elif isinstance(span.span_data, FunctionSpanData):
            return self._function_log_data(span)
        elif isinstance(span.span_data, GenerationSpanData):
            return self._generation_log_data(span)
        else:
            return {}

    def on_span_start(self, span: Span[SpanData]) -> None:
        if span.parent_id is not None:
            parent = self._spans[span.parent_id]
        else:
            parent = self._spans[span.trace_id]
        created_span = parent.start_span(
            id=span.span_id,
            name=_span_name(span),
            type=_span_type(span),
            start_time=_timestamp_from_maybe_iso(span.started_at),
        )
        self._spans[span.span_id] = created_span

        # Set the span as current so current_span() calls will return it
        created_span.set_current()

    def on_span_end(self, span: Span[SpanData]) -> None:
        s = self._spans.pop(span.span_id)
        event = dict(error=span.error, **self._log_data(span))
        s.log(**event)
        s.unset_current()
        s.end(_timestamp_from_maybe_iso(span.ended_at))

        input_ = event.get("input")
        output = event.get("output")
        # Store first input and last output per trace_id
        trace_id = span.trace_id
        if trace_id not in self._first_input and input_ is not None:
            self._first_input[trace_id] = input_

        if output is not None:
            self._last_output[trace_id] = output

    def shutdown(self) -> None:
        if self._logger is not None:
            self._logger.flush()
        else:
            braintrust.flush()

    def force_flush(self) -> None:
        if self._logger is not None:
            self._logger.flush()
        else:
            braintrust.flush()
