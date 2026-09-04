"""Metadata-only traces retain metering data without capturing model content."""

from typing import Any

from onyx.tracing.flows import LLMFlow
from onyx.tracing.framework.processor_interface import TracingProcessor
from onyx.tracing.framework.provider import DefaultTraceProvider
from onyx.tracing.framework.setup import get_trace_provider, set_trace_provider
from onyx.tracing.framework.span_data import GenerationSpanData
from onyx.tracing.framework.spans import NoOpSpan, Span
from onyx.tracing.framework.traces import Trace, TraceContentMode
from onyx.tracing.llm_utils import record_llm_span_output, traced_llm_call


class _CaptureProcessor(TracingProcessor):
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


def test_metadata_only_trace_removes_generation_content() -> None:
    provider = DefaultTraceProvider()
    processor = _CaptureProcessor()
    provider.register_processor(processor)

    with provider.create_trace(
        "background_llm_call", content_mode=TraceContentMode.METADATA_ONLY
    ) as trace:
        span = provider.create_span(
            GenerationSpanData(
                input=[{"role": "user", "content": "private document"}],
                output=[{"role": "assistant", "content": "private response"}],
                reasoning="private reasoning",
                model="claude-sonnet",
                tools=[{"name": "private_tool"}],
                request_params={"private": "parameter"},
            )
        )
        with span:
            span.span_data.output = [
                {"role": "assistant", "content": "late private response"}
            ]
            span.span_data.usage = {"input_tokens": 5, "output_tokens": 2}

    assert processor.started_traces == [trace]
    assert processor.ended_traces == [trace]
    assert processor.ended_spans == [span]
    assert span.trace_id == trace.trace_id
    assert span.content_mode == TraceContentMode.METADATA_ONLY
    assert span.span_data.input is None
    assert span.span_data.output is None
    assert span.span_data.reasoning is None
    assert span.span_data.tools is None
    assert span.span_data.request_params is None
    assert span.span_data.usage == {"input_tokens": 5, "output_tokens": 2}


def test_span_without_trace_remains_noop() -> None:
    provider = DefaultTraceProvider()
    processor = _CaptureProcessor()
    provider.register_processor(processor)

    span = provider.create_span(GenerationSpanData(model="claude-sonnet"))
    with span:
        span.span_data.usage = {"input_tokens": 5, "output_tokens": 2}

    assert isinstance(span, NoOpSpan)
    assert processor.ended_spans == []


def test_llm_helper_does_not_create_workflow_trace() -> None:
    original_provider = get_trace_provider()
    provider = DefaultTraceProvider()
    processor = _CaptureProcessor()
    provider.register_processor(processor)
    set_trace_provider(provider)

    try:
        with traced_llm_call(
            flow=LLMFlow.IMAGE_SUMMARIZATION,
            model="claude-sonnet",
            provider="anthropic",
            input_messages=[{"role": "user", "content": "private document"}],
        ) as span:
            record_llm_span_output(
                span,
                output="private response",
                reasoning="private reasoning",
                usage={"input_tokens": 5, "output_tokens": 2},
            )
    finally:
        set_trace_provider(original_provider)

    assert isinstance(span, NoOpSpan)
    assert processor.started_traces == []
    assert processor.ended_traces == []
    assert processor.ended_spans == []
    assert span.span_data.usage == {"input_tokens": 5, "output_tokens": 2}
