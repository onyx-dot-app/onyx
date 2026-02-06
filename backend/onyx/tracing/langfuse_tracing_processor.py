import datetime
from typing import Any
from typing import Dict
from typing import Optional

from langfuse import Langfuse
from langfuse import LangfuseSpan

from onyx.configs.app_configs import LANGFUSE_PUBLIC_KEY
from onyx.configs.app_configs import LANGFUSE_SECRET_KEY
from onyx.llm.cost import calculate_llm_cost_cents
from onyx.tracing.framework.processor_interface import TracingProcessor
from onyx.tracing.framework.span_data import AgentSpanData
from onyx.tracing.framework.span_data import FunctionSpanData
from onyx.tracing.framework.span_data import GenerationSpanData
from onyx.tracing.framework.span_data import SpanData
from onyx.tracing.framework.spans import Span
from onyx.tracing.framework.traces import Trace
from onyx.utils.logger import setup_logger

logger = setup_logger()


def _span_type(span: Span[Any]) -> str:
    """Map span type to Langfuse observation type."""
    if span.span_data.type in ["agent"]:
        return "agent"
    elif span.span_data.type in ["function"]:
        return "tool"
    elif span.span_data.type in ["generation"]:
        return "generation"
    else:
        return "span"


def _span_name(span: Span[Any]) -> str:
    """Get the name for a span."""
    if isinstance(span.span_data, AgentSpanData) or isinstance(
        span.span_data, FunctionSpanData
    ):
        return span.span_data.name
    elif isinstance(span.span_data, GenerationSpanData):
        return "Generation"
    else:
        return "Unknown"


def _timestamp_from_maybe_iso(timestamp: Optional[str]) -> Optional[float]:
    """Convert ISO timestamp string to Unix timestamp."""
    if timestamp is None:
        return None
    return datetime.datetime.fromisoformat(timestamp).timestamp()


def _maybe_timestamp_elapsed(
    end: Optional[str], start: Optional[str]
) -> Optional[float]:
    """Calculate elapsed time between two ISO timestamps."""
    if start is None or end is None:
        return None
    return (
        datetime.datetime.fromisoformat(end) - datetime.datetime.fromisoformat(start)
    ).total_seconds()


class LangfuseTracingProcessor(TracingProcessor):
    """
    `LangfuseTracingProcessor` is a `tracing.TracingProcessor` that logs traces to Langfuse.

    This processor creates Langfuse traces and spans using our internal trace IDs,
    ensuring that the trace_id saved to messages matches what Langfuse uses.
    """

    def __init__(self, client: Optional[Any] = None):
        """
        Initialize the Langfuse tracing processor.

        Args:
            client: Optional Langfuse client. If None, will use get_client().
        """
        self._client = client
        self._spans: Dict[str, LangfuseSpan] = {}
        self._first_input: Dict[str, Any] = {}
        self._last_output: Dict[str, Any] = {}
        self._trace_metadata: Dict[str, Dict[str, Any]] = {}
        self._span_names: Dict[str, str] = {}

    def _get_client(self) -> Langfuse:
        """Get or create Langfuse client."""
        if self._client is None:
            from langfuse import get_client

            self._client = get_client()
        return self._client

    def on_trace_start(self, trace: Trace) -> None:
        """Called when a trace is started.

        Args:
            trace: The trace that started.
        """
        try:
            trace_meta = trace.export() or {}
            metadata = trace_meta.get("metadata") or {}
            if metadata:
                self._trace_metadata[trace.trace_id] = metadata

            client = self._get_client()

            # Build metadata dict for Langfuse
            langfuse_metadata: Dict[str, Any] = {}
            if metadata:
                # Copy metadata, but handle special fields
                for key, value in metadata.items():
                    if key not in ["user_id", "chat_session_id"]:
                        langfuse_metadata[key] = value

            # Langfuse expects trace_id to be a 32-character hex string (no prefix)
            # Our internal trace_id format is "trace_{32_hex_chars}", so we need to strip the prefix
            langfuse_trace_id = trace.trace_id
            if langfuse_trace_id.startswith("trace_"):
                langfuse_trace_id = langfuse_trace_id[6:]  # Remove "trace_" prefix

            # Create root observation with trace_context to set our trace_id
            # This creates the trace implicitly with our custom trace_id
            langfuse_trace = client.start_observation(
                name=trace.name,
                as_type="span",
                trace_context={
                    "trace_id": langfuse_trace_id,
                },
                metadata=langfuse_metadata if langfuse_metadata else None,
            )

            # Set user_id and session_id via update_trace (these are trace-level attributes)
            if metadata.get("user_id") or metadata.get("chat_session_id"):
                langfuse_trace.update_trace(
                    user_id=(
                        str(metadata.get("user_id"))
                        if metadata.get("user_id")
                        else None
                    ),
                    session_id=(
                        str(metadata.get("chat_session_id"))
                        if metadata.get("chat_session_id")
                        else None
                    ),
                )

            self._spans[trace.trace_id] = langfuse_trace
            self._span_names[trace.trace_id] = trace.name
            logger.debug(
                f"Successfully started trace {trace.trace_id} in Langfuse, stored in _spans"
            )
        except Exception as e:
            logger.error(
                f"Failed to start trace {trace.trace_id} in Langfuse: {e}",
                exc_info=True,
            )
            # Don't re-raise - let other processors continue

    def on_trace_end(self, trace: Trace) -> None:
        """Called when a trace is finished.

        Args:
            trace: The trace that finished.
        """
        langfuse_trace = self._spans.pop(trace.trace_id, None)
        self._trace_metadata.pop(trace.trace_id, None)
        self._span_names.pop(trace.trace_id, None)

        if langfuse_trace:
            # Get the first input and last output for this specific trace
            trace_first_input = self._first_input.pop(trace.trace_id, None)
            trace_last_output = self._last_output.pop(trace.trace_id, None)

            # Also check metadata for user_input and final_answer
            metadata = trace.metadata or {}
            if not trace_first_input and metadata.get("user_input"):
                trace_first_input = metadata.get("user_input")
            if not trace_last_output and metadata.get("final_answer"):
                trace_last_output = metadata.get("final_answer")

            # Update trace with input/output
            update_data: Dict[str, Any] = {}
            if trace_first_input is not None:
                update_data["input"] = trace_first_input
            if trace_last_output is not None:
                update_data["output"] = trace_last_output

            if update_data:
                langfuse_trace.update(**update_data)

            # End the trace
            langfuse_trace.end()

    def _agent_log_data(self, span: Span[AgentSpanData]) -> Dict[str, Any]:
        """Extract log data from an agent span."""
        return {
            "metadata": {
                "tools": span.span_data.tools,
                "handoffs": span.span_data.handoffs,
                "output_type": span.span_data.output_type,
            }
        }

    def _function_log_data(self, span: Span[FunctionSpanData]) -> Dict[str, Any]:
        """Extract log data from a function span."""
        return {
            "input": span.span_data.input,
            "output": span.span_data.output,
        }

    def _generation_log_data(self, span: Span[GenerationSpanData]) -> Dict[str, Any]:
        """Extract log data from a generation span."""
        usage_details: Dict[str, int] = {}
        cost_details: Dict[str, float] = {}
        metadata: Dict[str, Any] = {
            "model": span.span_data.model,
            "model_config": span.span_data.model_config,
        }

        # Extract usage details (Langfuse uses usage_details, not metrics)
        usage = span.span_data.usage or {}
        prompt_tokens = usage.get("prompt_tokens")
        if prompt_tokens is None:
            prompt_tokens = usage.get("input_tokens")
        if prompt_tokens is not None:
            usage_details["prompt_tokens"] = int(prompt_tokens)

        completion_tokens = usage.get("completion_tokens")
        if completion_tokens is None:
            completion_tokens = usage.get("output_tokens")
        if completion_tokens is not None:
            usage_details["completion_tokens"] = int(completion_tokens)

        if "total_tokens" in usage:
            usage_details["total_tokens"] = usage["total_tokens"]
        elif prompt_tokens is not None and completion_tokens is not None:
            usage_details["total_tokens"] = prompt_tokens + completion_tokens

        # Calculate cost if we have tokens and model
        model_name = span.span_data.model
        if model_name and prompt_tokens is not None and completion_tokens is not None:
            cost_cents = calculate_llm_cost_cents(
                model_name=model_name,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
            )
            if cost_cents > 0:
                cost_details["total_cost"] = (
                    cost_cents / 100.0
                )  # Convert cents to dollars

        # Add time_to_first_action to metadata if available
        if span.span_data.time_to_first_action_seconds is not None:
            metadata["time_to_first_action_seconds"] = (
                span.span_data.time_to_first_action_seconds
            )

        result: Dict[str, Any] = {
            "input": span.span_data.input,
            "output": span.span_data.output,
            "metadata": metadata if metadata else None,
        }

        if usage_details:
            result["usage_details"] = usage_details
        if cost_details:
            result["cost_details"] = cost_details

        # Add model and model_parameters if available
        if span.span_data.model:
            result["model"] = span.span_data.model

        if span.span_data.model_config:
            result["model_parameters"] = span.span_data.model_config

        return result

    def _log_data(self, span: Span[Any]) -> Dict[str, Any]:
        """Extract log data from a span based on its type."""
        if isinstance(span.span_data, AgentSpanData):
            return self._agent_log_data(span)
        elif isinstance(span.span_data, FunctionSpanData):
            return self._function_log_data(span)
        elif isinstance(span.span_data, GenerationSpanData):
            return self._generation_log_data(span)
        else:
            return {}

    def on_span_start(self, span: Span[SpanData]) -> None:
        """Called when a span is started.

        Args:
            span: The span that started.
        """
        # Find the parent (either another span or the trace itself)
        parent = None
        if span.parent_id is not None:
            parent = self._spans.get(span.parent_id)
            if parent is None:
                logger.warning(
                    f"Parent span {span.parent_id} not found for span {span.span_id}, "
                    f"trace_id: {span.trace_id}. Available spans: {list(self._spans.keys())}"
                )
                return
        else:
            parent = self._spans.get(span.trace_id)
            if parent is None:
                logger.warning(
                    f"Trace {span.trace_id} not found for span {span.span_id}. "
                    f"Available traces/spans: {list(self._spans.keys())}"
                )
                return

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

        # Build metadata dict for Langfuse
        langfuse_metadata: Dict[str, Any] = {}
        if trace_metadata:
            # Copy metadata, but handle special fields
            for key, value in trace_metadata.items():
                if key not in ["user_id", "chat_session_id"]:
                    langfuse_metadata[key] = value

        # Prepare observation parameters
        # Similar to Braintrust approach - use _span_type and _span_name helper functions
        observation_kwargs: Dict[str, Any] = dict(
            name=span_name,
            as_type=_span_type(span),
            completion_start_time=_timestamp_from_maybe_iso(span.started_at),
        )

        if langfuse_metadata:
            observation_kwargs["metadata"] = langfuse_metadata

        # Create observation using parent's start_observation method
        created_span = parent.start_observation(**observation_kwargs)
        self._spans[span.span_id] = created_span
        self._span_names[span.span_id] = span_name

    def on_span_end(self, span: Span[SpanData]) -> None:
        """Called when a span is finished.

        Args:
            span: The span that finished.
        """
        langfuse_span = self._spans.pop(span.span_id, None)
        self._span_names.pop(span.span_id, None)

        if langfuse_span:
            # Build update data similar to Braintrust's approach
            event = dict(**self._log_data(span))

            # Handle errors - set level and status_message if error exists
            if span.error:
                event["level"] = "ERROR"
                event["status_message"] = span.error.get("message", "Error occurred")
                if span.error.get("data"):
                    # Add error data to metadata
                    if "metadata" not in event:
                        event["metadata"] = {}
                    if not isinstance(event["metadata"], dict):
                        event["metadata"] = {}
                    event["metadata"]["error_data"] = span.error["data"]

            # Update the span with all collected data
            langfuse_span.update(**event)

            # end() accepts end_time in nanoseconds since epoch (int), not float seconds
            end_time_ns = None
            if span.ended_at:
                end_time_seconds = _timestamp_from_maybe_iso(span.ended_at)
                if end_time_seconds is not None:
                    end_time_ns = int(
                        end_time_seconds * 1_000_000_000
                    )  # Convert to nanoseconds

            langfuse_span.end(end_time=end_time_ns)

            input_ = event.get("input")
            output = event.get("output")
            # Store first input and last output per trace_id
            trace_id = span.trace_id
            if trace_id not in self._first_input and input_ is not None:
                self._first_input[trace_id] = input_

            if output is not None:
                self._last_output[trace_id] = output

    def shutdown(self) -> None:
        """Called when the application stops."""
        client = self._get_client()
        client.flush()

    def force_flush(self) -> None:
        """Forces an immediate flush of all queued spans/traces."""
        client = self._get_client()
        client.flush()

    def score_trace(
        self, trace_id: str, score: float, comment: str | None = None
    ) -> None:
        """Score a trace in Langfuse.

        Args:
            trace_id: The trace ID to score
            score: The score value (0.0 to 1.0)
            comment: Optional comment explaining the score
        """
        if not LANGFUSE_SECRET_KEY or not LANGFUSE_PUBLIC_KEY:
            logger.debug("Langfuse credentials not configured, skipping score update")
            return

        try:
            client = self._get_client()

            # Langfuse expects trace_id to be a 32-character hex string (no prefix)
            # Our internal trace_id format is "trace_{32_hex_chars}", so we need to strip the prefix
            langfuse_trace_id = trace_id
            if langfuse_trace_id.startswith("trace_"):
                langfuse_trace_id = langfuse_trace_id[6:]  # Remove "trace_" prefix

            client.create_score(
                trace_id=langfuse_trace_id,
                name="user-feedback",
                value=score,
                comment=comment,
            )
            # Flush to ensure the score is sent to Langfuse
            client.flush()
            logger.info(f"Successfully updated score {score} for trace {trace_id}")
        except ImportError:
            logger.warning("Langfuse client not available for score update")
        except Exception as e:
            logger.error(
                f"Failed to update trace score for trace {trace_id}: {e}", exc_info=True
            )
