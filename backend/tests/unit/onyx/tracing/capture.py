from typing import Any

from onyx.tracing.framework.processor_interface import TracingProcessor
from onyx.tracing.framework.spans import Span
from onyx.tracing.framework.traces import Trace


class CaptureProcessor(TracingProcessor):
    """Records the traces and spans that a test produces."""

    def __init__(self) -> None:
        self.started_traces: list[Trace] = []
        self.ended_traces: list[Trace] = []
        self.ended_spans: list[Span[Any]] = []

    def on_trace_start(self, trace: Trace) -> None:
        self.started_traces.append(trace)

    def on_trace_end(self, trace: Trace) -> None:
        self.ended_traces.append(trace)

    def on_span_start(self, span: Span[Any]) -> None:
        pass

    def on_span_end(self, span: Span[Any]) -> None:
        self.ended_spans.append(span)

    def shutdown(self) -> None:
        pass

    def force_flush(self) -> None:
        pass
