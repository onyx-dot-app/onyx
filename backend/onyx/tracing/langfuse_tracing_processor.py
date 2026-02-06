"""Langfuse tracing processor using the native Langfuse SDK."""

from __future__ import annotations

import logging
import threading
from datetime import datetime
from typing import Any
from typing import Optional
from typing import Union

from langfuse import Langfuse
from langfuse._client.span import LangfuseObservationWrapper

from onyx.tracing.framework.processor_interface import TracingProcessor
from onyx.tracing.framework.span_data import AgentSpanData
from onyx.tracing.framework.span_data import FunctionSpanData
from onyx.tracing.framework.span_data import GenerationSpanData
from onyx.tracing.framework.span_data import SpanData
from onyx.tracing.framework.spans import Span
from onyx.tracing.framework.traces import Trace

logger = logging.getLogger(__name__)


def _timestamp_from_maybe_iso(timestamp: Optional[str]) -> Optional[datetime]:
    """Convert ISO timestamp string to datetime."""
    if timestamp is None:
        return None
    try:
        return datetime.fromisoformat(timestamp)
    except ValueError:
        return None


class LangfuseTracingProcessor(TracingProcessor):
    """TracingProcessor that logs traces to Langfuse using the native SDK.

    Args:
        client: A Langfuse client instance. If None, uses get_client().
        enable_masking: Whether to mask sensitive data before sending.
    """

    def __init__(
        self,
        client: Optional[Langfuse] = None,
        enable_masking: bool = True,
    ) -> None:
        self._client: Optional[Langfuse] = client
        self._enable_masking = enable_masking
        self._lock = threading.Lock()  # Protects all dict access
        self._spans: dict[str, LangfuseObservationWrapper] = {}
        self._trace_spans: dict[str, LangfuseObservationWrapper] = (
            {}
        )  # Root spans for traces
        self._first_input: dict[str, Any] = {}
        self._last_output: dict[str, Any] = {}
        self._trace_metadata: dict[str, dict[str, Any]] = {}
        # Langfuse IDs for thread-safe parent linking via trace_context
        self._langfuse_trace_ids: dict[str, str] = (
            {}
        )  # framework_trace_id -> langfuse_trace_id
        self._langfuse_span_ids: dict[str, str] = (
            {}
        )  # framework_span_id -> langfuse_span.id

    def _get_client(self) -> Langfuse:
        """Get or create Langfuse client."""
        if self._client is None:
            from langfuse import get_client

            self._client = get_client()
        return self._client

    def _mask_if_enabled(self, data: Any) -> Any:
        """Apply masking to data if masking is enabled."""
        if not self._enable_masking:
            return data
        try:
            from onyx.tracing.masking import mask_sensitive_data

            return mask_sensitive_data(data)
        except Exception as e:
            logger.warning(f"Failed to mask data: {e}")
            return data

    def _calculate_cost(self, data: GenerationSpanData) -> Optional[float]:
        """Calculate LLM cost for this generation span."""
        try:
            from onyx.llm.cost import calculate_llm_cost_cents

            usage = data.usage or {}
            prompt_tokens = usage.get("prompt_tokens") or usage.get("input_tokens") or 0
            completion_tokens = (
                usage.get("completion_tokens") or usage.get("output_tokens") or 0
            )

            if data.model and prompt_tokens and completion_tokens:
                cost_cents = calculate_llm_cost_cents(
                    model_name=data.model,
                    prompt_tokens=int(prompt_tokens),
                    completion_tokens=int(completion_tokens),
                )
                if cost_cents > 0:
                    # Convert cents to dollars for Langfuse
                    return cost_cents / 100.0
        except Exception as e:
            logger.debug(f"Failed to calculate cost: {e}")
        return None

    def on_trace_start(self, trace: Trace) -> None:
        """Called when a trace is started."""
        try:
            client = self._get_client()
            trace_meta = trace.export() or {}
            metadata = trace_meta.get("metadata") or {}

            # Create a root span which implicitly creates a Langfuse trace
            # The span name becomes the trace name in Langfuse UI
            # In Langfuse SDK v3, use start_observation instead of start_span
            langfuse_span = client.start_observation(
                name=trace.name,
            )

            # Always update the trace-level properties to set the trace name
            # session_id is optional but name should always be set
            session_id = metadata.get("chat_session_id")
            langfuse_span.update_trace(
                name=trace.name,
                session_id=session_id if session_id else None,
                metadata=metadata if metadata else None,
            )

            with self._lock:
                if metadata:
                    self._trace_metadata[trace.trace_id] = metadata
                self._trace_spans[trace.trace_id] = langfuse_span
                # Store Langfuse IDs for thread-safe parent linking
                self._langfuse_trace_ids[trace.trace_id] = langfuse_span.trace_id
                # Use trace_id as key for root span's ID (children with no parent_id will use this)
                self._langfuse_span_ids[trace.trace_id] = langfuse_span.id
        except Exception as e:
            logger.error(f"Error starting Langfuse trace: {e}")

    def on_trace_end(self, trace: Trace) -> None:
        """Called when a trace is finished."""
        try:
            with self._lock:
                langfuse_span = self._trace_spans.pop(trace.trace_id, None)
                self._trace_metadata.pop(trace.trace_id, None)
                self._langfuse_trace_ids.pop(trace.trace_id, None)  # Clean up trace ID
                self._langfuse_span_ids.pop(
                    trace.trace_id, None
                )  # Clean up root span ID
                trace_first_input = self._first_input.pop(trace.trace_id, None)
                trace_last_output = self._last_output.pop(trace.trace_id, None)

            if langfuse_span:
                # Update the root span with input/output and end it
                langfuse_span.update(
                    input=self._mask_if_enabled(trace_first_input),
                    output=self._mask_if_enabled(trace_last_output),
                )
                langfuse_span.end()
        except Exception as e:
            logger.error(f"Error ending Langfuse trace: {e}")

    def on_span_start(self, span: Span[SpanData]) -> None:
        """Called when a span is started.

        Uses trace_context parameter for thread-safe parent linking instead of
        calling methods on parent span objects. This is necessary because research
        agents run in parallel threads, and calling methods on span objects created
        in other threads can cause OpenTelemetry context issues.
        """
        try:
            data = span.span_data
            # Declare as Any since different code paths return different observation types
            langfuse_span: Any = None

            # Get Langfuse IDs and metadata under lock for thread-safe access
            with self._lock:
                trace_metadata = self._trace_metadata.get(span.trace_id)
                langfuse_trace_id = self._langfuse_trace_ids.get(span.trace_id)
                # Get parent's Langfuse span ID
                if span.parent_id is not None:
                    parent_langfuse_id = self._langfuse_span_ids.get(span.parent_id)
                else:
                    # Parent is the root trace span (use trace_id as key)
                    parent_langfuse_id = self._langfuse_span_ids.get(span.trace_id)

            # If no trace ID found, we can't create a properly linked span
            if langfuse_trace_id is None:
                logger.warning(
                    f"No Langfuse trace ID found for span {span.span_id}, creating orphan"
                )
                # Fall back to creating an orphan span
                # In Langfuse SDK v3, use start_observation instead of start_span
                client = self._get_client()
                langfuse_span = client.start_observation(
                    name=data.type if hasattr(data, "type") else "unknown",
                )
                with self._lock:
                    self._spans[span.span_id] = langfuse_span
                    self._langfuse_span_ids[span.span_id] = langfuse_span.id
                return

            client = self._get_client()

            # Build trace_context for thread-safe parent linking
            # This uses immutable string IDs instead of mutable span objects
            # Type is Any to satisfy SDK's TraceContext type while passing a dict
            trace_context: Any = {"trace_id": langfuse_trace_id}
            if parent_langfuse_id:
                trace_context["parent_span_id"] = parent_langfuse_id

            # Create spans using trace_context (thread-safe ID-based approach)
            # In Langfuse SDK v3, use start_observation with as_type parameter
            if isinstance(data, GenerationSpanData):
                langfuse_span = client.start_observation(  # type: ignore[call-overload]
                    trace_context=trace_context,
                    name=self._get_generation_name(data),
                    as_type="generation",
                    metadata=trace_metadata,
                    model=data.model,
                    model_parameters=self._get_model_parameters(data),
                )
            elif isinstance(data, FunctionSpanData):
                langfuse_span = client.start_observation(
                    trace_context=trace_context,
                    name=data.name,
                    as_type="tool",
                    metadata=trace_metadata,
                )
            elif isinstance(data, AgentSpanData):
                langfuse_span = client.start_observation(
                    trace_context=trace_context,
                    name=data.name,
                    as_type="agent",
                    metadata={
                        **(trace_metadata or {}),
                        "tools": data.tools,
                        "handoffs": data.handoffs,
                        "output_type": data.output_type,
                    },
                )
            else:
                langfuse_span = client.start_observation(
                    trace_context=trace_context,
                    name=data.type if hasattr(data, "type") else "unknown",
                    as_type="span",
                    metadata=trace_metadata,
                )

            with self._lock:
                self._spans[span.span_id] = langfuse_span
                # Store Langfuse span ID for future children to reference
                self._langfuse_span_ids[span.span_id] = langfuse_span.id
        except Exception as e:
            logger.error(f"Error starting Langfuse span: {e}")

    def on_span_end(self, span: Span[SpanData]) -> None:
        """Called when a span is finished."""
        try:
            with self._lock:
                langfuse_span = self._spans.pop(span.span_id, None)
                self._langfuse_span_ids.pop(span.span_id, None)  # Clean up ID mapping

            if not langfuse_span:
                return

            data = span.span_data
            input_data: Optional[Any] = None
            output_data: Optional[Any] = None

            if isinstance(data, GenerationSpanData):
                input_data = data.input
                output_data = data.output
                usage = self._get_usage_details(data)
                cost = self._calculate_cost(data)

                update_kwargs: dict[str, Any] = {
                    "input": self._mask_if_enabled(input_data),
                    "output": self._mask_if_enabled(output_data),
                }
                if usage:
                    update_kwargs["usage_details"] = usage
                if cost is not None:
                    update_kwargs["cost_details"] = {"total": cost}
                if data.reasoning:
                    update_kwargs["metadata"] = {"reasoning": data.reasoning}
                if data.time_to_first_action_seconds is not None:
                    update_kwargs["completion_start_time"] = _timestamp_from_maybe_iso(
                        span.started_at
                    )

                langfuse_span.update(**update_kwargs)

            elif isinstance(data, FunctionSpanData):
                input_data = data.input
                output_data = data.output
                langfuse_span.update(
                    input=self._mask_if_enabled(input_data),
                    output=self._mask_if_enabled(output_data),
                )

            elif isinstance(data, AgentSpanData):
                # Agent spans don't have direct input/output
                pass

            # Handle errors
            if span.error:
                langfuse_span.update(
                    level="ERROR",
                    status_message=f"{span.error.get('message')}: {span.error.get('data')}",
                )

            langfuse_span.end()

            # Store first input and last output per trace_id
            trace_id = span.trace_id
            with self._lock:
                if trace_id not in self._first_input and input_data is not None:
                    self._first_input[trace_id] = input_data

                if output_data is not None:
                    self._last_output[trace_id] = output_data

        except Exception as e:
            logger.error(f"Error ending Langfuse span: {e}")

    def _get_generation_name(self, data: GenerationSpanData) -> str:
        """Get a descriptive name for a generation span."""
        if data.model:
            return f"Generation with {data.model}"
        return "Generation"

    def _get_model_parameters(
        self, data: GenerationSpanData
    ) -> Optional[dict[str, Union[str, int, bool, None]]]:
        """Extract model parameters from generation span data."""
        if not isinstance(data.model_config, dict):
            return None

        params: dict[str, Union[str, int, bool, None]] = {}
        for key in [
            "temperature",
            "max_tokens",
            "top_p",
            "frequency_penalty",
            "presence_penalty",
        ]:
            if key in data.model_config:
                params[key] = data.model_config[key]
        return params if params else None

    def _get_usage_details(self, data: GenerationSpanData) -> Optional[dict[str, int]]:
        """Extract usage details from generation span data."""
        usage = data.usage or {}
        details: dict[str, int] = {}

        prompt_tokens = usage.get("prompt_tokens") or usage.get("input_tokens")
        if prompt_tokens is not None:
            details["input"] = int(prompt_tokens)

        completion_tokens = usage.get("completion_tokens") or usage.get("output_tokens")
        if completion_tokens is not None:
            details["output"] = int(completion_tokens)

        if "total_tokens" in usage:
            details["total"] = int(usage["total_tokens"])
        elif details.get("input") and details.get("output"):
            details["total"] = details["input"] + details["output"]

        # Cache-related tokens
        if "cache_read_input_tokens" in usage:
            details["cache_read_input_tokens"] = int(usage["cache_read_input_tokens"])
        if "cache_creation_input_tokens" in usage:
            details["cache_creation_input_tokens"] = int(
                usage["cache_creation_input_tokens"]
            )

        return details if details else None

    def force_flush(self) -> None:
        """Forces an immediate flush of all queued spans/traces."""
        try:
            client = self._get_client()
            if client:
                client.flush()
        except Exception as e:
            logger.warning(f"Failed to flush Langfuse client: {e}")

    def shutdown(self) -> None:
        """Called when the application stops."""
        try:
            self.force_flush()
            client = self._get_client()
            if client:
                client.shutdown()
        except Exception as e:
            logger.warning(f"Failed to shutdown Langfuse client: {e}")
