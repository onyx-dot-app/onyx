"""Incognito turns must leave no content in Langfuse: the processor drops the
whole trace, spans included, keyed on membership recorded at trace start."""

from collections.abc import Generator
from unittest.mock import MagicMock

import pytest

from onyx.tracing.langfuse_tracing_processor import LangfuseTracingProcessor
from shared_configs.contextvars import CURRENT_INCOGNITO_RECORD_MODE_CONTEXTVAR


@pytest.fixture
def incognito_context() -> Generator[None, None, None]:
    token = CURRENT_INCOGNITO_RECORD_MODE_CONTEXTVAR.set("usage_only")
    yield
    CURRENT_INCOGNITO_RECORD_MODE_CONTEXTVAR.reset(token)


def _fake_trace(trace_id: str) -> MagicMock:
    trace = MagicMock()
    trace.trace_id = trace_id
    trace.name = "run_llm_loop"
    trace.export.return_value = {}
    return trace


def _fake_span(trace_id: str, span_id: str) -> MagicMock:
    span = MagicMock()
    span.trace_id = trace_id
    span.span_id = span_id
    span.parent_id = None
    return span


def test_incognito_trace_is_fully_suppressed(
    incognito_context: None,  # noqa: ARG001 (requested for the flag side-effect)
) -> None:
    client = MagicMock()
    processor = LangfuseTracingProcessor(client=client)
    trace = _fake_trace("t1")
    span = _fake_span("t1", "s1")

    processor.on_trace_start(trace)
    processor.on_span_start(span)
    processor.on_span_end(span)
    processor.on_trace_end(trace)

    client.start_observation.assert_not_called()
    assert processor._suppressed_traces == set()


def test_ordinary_trace_still_exports() -> None:
    client = MagicMock()
    processor = LangfuseTracingProcessor(client=client)
    trace = _fake_trace("t2")

    processor.on_trace_start(trace)

    client.start_observation.assert_called_once()
