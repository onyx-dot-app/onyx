import abc
from typing import Any
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .spans import Span
    from .traces import Trace


class TracingProcessor(abc.ABC):
    """Interface for processing and monitoring traces and spans in the OpenAI Agents system.

    This abstract class defines the interface that all tracing processors must implement.
    Processors receive notifications when traces and spans start and end, allowing them
    to collect, process, and export tracing data.

    Example:
        ```python
        class CustomProcessor(TracingProcessor):
            def __init__(self):
                self.active_traces = {}
                self.active_spans = {}

            def on_trace_start(self, trace):
                self.active_traces[trace.trace_id] = trace

            def on_trace_end(self, trace):
                # Process completed trace
                del self.active_traces[trace.trace_id]

            def on_span_start(self, span):
                self.active_spans[span.span_id] = span

            def on_span_end(self, span):
                # Process completed span
                del self.active_spans[span.span_id]

            def shutdown(self):
                # Clean up resources
                self.active_traces.clear()
                self.active_spans.clear()

            def force_flush(self):
                # Force processing of any queued items
                pass
        ```

    Notes:
        - All methods should be thread-safe
        - Methods should not block for long periods
        - Handle errors gracefully to prevent disrupting agent execution
    """

    @abc.abstractmethod
    def on_trace_start(self, trace: "Trace") -> None:
        """Called when a new trace begins execution.

        Args:
            trace: The trace that started. Contains workflow name and metadata.

        Notes:
            - Called synchronously on trace start
            - Should return quickly to avoid blocking execution
            - Any errors should be caught and handled internally
        """

    @abc.abstractmethod
    def on_trace_end(self, trace: "Trace") -> None:
        """Called when a trace completes execution.

        Args:
            trace: The completed trace containing all spans and results.

        Notes:
            - Called synchronously when trace finishes
            - Good time to export/process the complete trace
            - Should handle cleanup of any trace-specific resources
        """

    @abc.abstractmethod
    def on_span_start(self, span: "Span[Any]") -> None:
        """Called when a new span begins execution.

        Args:
            span: The span that started. Contains operation details and context.

        Notes:
            - Called synchronously on span start
            - Should return quickly to avoid blocking execution
            - Spans are automatically nested under current trace/span
        """

    @abc.abstractmethod
    def on_span_end(self, span: "Span[Any]") -> None:
        """Called when a span completes execution.

        Args:
            span: The completed span containing execution results.

        Notes:
            - Called synchronously when span finishes
            - Should not block or raise exceptions
            - Good time to export/process the individual span
        """

    @abc.abstractmethod
    def shutdown(self) -> None:
        """Called when the application stops to clean up resources.

        Should perform any necessary cleanup like:
        - Flushing queued traces/spans
        - Closing connections
        - Releasing resources
        """

    @abc.abstractmethod
    def force_flush(self) -> None:
        """Forces immediate processing of any queued traces/spans.

        Notes:
            - Should process all queued items before returning
            - Useful before shutdown or when immediate processing is needed
            - May block while processing completes
        """


class TracingExporter(abc.ABC):
    """Exports traces and spans. For example, could log them or send them to a backend."""

    @abc.abstractmethod
    def export(self, items: list["Trace | Span[Any]"]) -> None:
        """Exports a list of traces and spans.

        Args:
            items: The items to export.
        """
