import datetime
from typing import Any
from typing import Dict
from typing import Optional

import braintrust
from braintrust import NOOP_SPAN

from .framework.processor_interface import TracingProcessor
from .framework.span_data import AgentSpanData
from .framework.span_data import FunctionSpanData
from .framework.span_data import GenerationSpanData
from .framework.span_data import SpanData
from .framework.spans import Span
from .framework.traces import Trace
from onyx.llm.cost import calculate_llm_cost_cents


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
        self._spans: Dict[str, Any] = {}
        self._first_input: Dict[str, Any] = {}
        self._last_output: Dict[str, Any] = {}
        self._trace_metadata: Dict[str, Dict[str, Any]] = {}
        self._span_names: Dict[str, str] = {}

    def on_trace_start(self, trace: Trace) -> None:
        trace_meta = trace.export() or {}
        metadata = trace_meta.get("metadata") or {}
        if metadata:
            self._trace_metadata[trace.trace_id] = metadata

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
            )
        else:
            self._spans[trace.trace_id] = braintrust.start_span(
                id=trace.trace_id,
                span_attributes={"type": "task", "name": trace.name},
                metadata=metadata,
            )
        self._span_names[trace.trace_id] = trace.name

    def on_trace_end(self, trace: Trace) -> None:
        span: Any = self._spans.pop(trace.trace_id)
        self._trace_metadata.pop(trace.trace_id, None)
        self._span_names.pop(trace.trace_id, None)
        # Get the first input and last output for this specific trace
        trace_first_input = self._first_input.pop(trace.trace_id, None)
        trace_last_output = self._last_output.pop(trace.trace_id, None)
        span.log(input=trace_first_input, output=trace_last_output)
        span.end()

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
        total_latency = _maybe_timestamp_elapsed(span.ended_at, span.started_at)

        if total_latency is not None:
            metrics["total_latency_seconds"] = total_latency

        if span.span_data.time_to_first_action_seconds is not None:
            metrics["time_to_first_action_seconds"] = (
                span.span_data.time_to_first_action_seconds
            )

        usage = span.span_data.usage or {}
        prompt_tokens = None
        completion_tokens = None
        prompt_tokens = usage.get("prompt_tokens")
        if prompt_tokens is None:
            prompt_tokens = usage.get("input_tokens")
        if prompt_tokens is not None:
            metrics["prompt_tokens"] = int(prompt_tokens)
        completion_tokens = usage.get("completion_tokens")
        if completion_tokens is None:
            completion_tokens = usage.get("output_tokens")
        if completion_tokens is not None:
            metrics["completion_tokens"] = int(completion_tokens)

        if "total_tokens" in usage:
            metrics["tokens"] = usage["total_tokens"]
        elif prompt_tokens is not None and completion_tokens is not None:
            metrics["tokens"] = prompt_tokens + completion_tokens

        if "cache_read_input_tokens" in usage:
            metrics["prompt_cached_tokens"] = usage["cache_read_input_tokens"]
        if "cache_creation_input_tokens" in usage:
            metrics["prompt_cache_creation_tokens"] = usage[
                "cache_creation_input_tokens"
            ]

        model_name = span.span_data.model
        if model_name and prompt_tokens is not None and completion_tokens is not None:
            cost_cents = calculate_llm_cost_cents(
                model_name=model_name,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
            )
            if cost_cents > 0:
                metrics["cost_cents"] = cost_cents

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
        parent: Any = (
            self._spans[span.parent_id]
            if span.parent_id is not None
            else self._spans[span.trace_id]
        )
        trace_metadata = self._trace_metadata.get(span.trace_id)
        span_name = _span_name(span)
        if isinstance(span.span_data, GenerationSpanData):
            parent_name = (
                self._span_names.get(span.parent_id)
                if span.parent_id is not None
                else self._span_names.get(span.trace_id)
            )
            if parent_name:
                span_name = parent_name
        span_kwargs: Dict[str, Any] = dict(
            id=span.span_id,
            name=span_name,
            type=_span_type(span),
            start_time=_timestamp_from_maybe_iso(span.started_at),
        )
        if trace_metadata:
            span_kwargs["metadata"] = trace_metadata
        created_span: Any = parent.start_span(**span_kwargs)
        self._spans[span.span_id] = created_span
        self._span_names[span.span_id] = span_name

        # Set the span as current so current_span() calls will return it
        created_span.set_current()

    def on_span_end(self, span: Span[SpanData]) -> None:
        s: Any = self._spans.pop(span.span_id)
        self._span_names.pop(span.span_id, None)
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
