"""Unit tests for LangfuseTracingProcessor metadata handling."""

from collections.abc import Mapping
from contextlib import nullcontext
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from onyx.tracing.framework.span_data import GenerationSpanData
from onyx.tracing.langfuse_tracing_processor import LangfuseTracingProcessor


def _make_trace(metadata: Mapping[str, Any]) -> MagicMock:
    trace = MagicMock()
    trace.trace_id = "trace-123"
    trace.name = "run_llm_loop"
    trace.export.return_value = {"metadata": metadata}
    return trace


def _make_client_with_observation() -> tuple[MagicMock, MagicMock]:
    observation = MagicMock()
    observation.trace_id = "lf-trace-1"
    observation.id = "lf-span-1"
    client = MagicMock()
    client.start_observation.return_value = observation
    return client, observation


def _make_span(trace_id: str, span_id: str) -> MagicMock:
    span = MagicMock()
    span.trace_id = trace_id
    span.span_id = span_id
    span.parent_id = None
    span.span_data = GenerationSpanData(model="gpt-4")
    return span


def test_on_trace_start_promotes_user_id_and_session_id() -> None:
    """user_id and chat_session_id must ride on the observation as first-class
    correlating attributes so Langfuse populates the Users and Sessions views.
    """
    client, _ = _make_client_with_observation()
    processor = LangfuseTracingProcessor(client=client)

    metadata = {
        "tenant_id": "tenant-abc",
        "chat_session_id": "session-xyz",
        "user_id": "user-42",
    }
    with patch(
        "onyx.tracing.langfuse_tracing_processor.propagate_attributes"
    ) as propagate:
        propagate.return_value = nullcontext()
        processor.on_trace_start(_make_trace(metadata))

    propagate.assert_called_once()
    kwargs = propagate.call_args.kwargs
    assert kwargs["user_id"] == "user-42"
    assert kwargs["session_id"] == "session-xyz"
    assert kwargs["trace_name"] == "run_llm_loop"
    assert kwargs["metadata"] == metadata


def test_on_trace_start_omits_missing_user_id() -> None:
    """Anonymous / unattributed traces still start, just without a user."""
    client, _ = _make_client_with_observation()
    processor = LangfuseTracingProcessor(client=client)

    metadata = {"tenant_id": "tenant-abc", "chat_session_id": "session-xyz"}
    with patch(
        "onyx.tracing.langfuse_tracing_processor.propagate_attributes"
    ) as propagate:
        propagate.return_value = nullcontext()
        processor.on_trace_start(_make_trace(metadata))

    kwargs = propagate.call_args.kwargs
    assert "user_id" not in kwargs
    assert kwargs["session_id"] == "session-xyz"


def test_on_trace_start_coerces_non_string_user_id() -> None:
    """User ids that arrive as ints (e.g. from User.id) are coerced to strings."""
    client, _ = _make_client_with_observation()
    processor = LangfuseTracingProcessor(client=client)

    metadata = {"chat_session_id": "session-xyz", "user_id": 7}
    with patch(
        "onyx.tracing.langfuse_tracing_processor.propagate_attributes"
    ) as propagate:
        propagate.return_value = nullcontext()
        processor.on_trace_start(_make_trace(metadata))

    assert propagate.call_args.kwargs["user_id"] == "7"


def test_child_spans_repeat_the_trace_attributes() -> None:
    """Correlating attributes only reach observations created inside the
    propagation block, so every child observation must re-apply them.
    """
    client, _ = _make_client_with_observation()
    processor = LangfuseTracingProcessor(client=client)

    metadata = {"chat_session_id": "session-xyz", "user_id": "user-42"}
    with patch(
        "onyx.tracing.langfuse_tracing_processor.propagate_attributes"
    ) as propagate:
        propagate.return_value = nullcontext()
        processor.on_trace_start(_make_trace(metadata))
        processor.on_span_start(_make_span("trace-123", "span-1"))

    assert propagate.call_count == 2
    assert propagate.call_args.kwargs["session_id"] == "session-xyz"
    assert propagate.call_args.kwargs["user_id"] == "user-42"


def test_calculate_cost_prices_cache_creation_at_write_rate() -> None:
    processor = LangfuseTracingProcessor(client=MagicMock())
    data = GenerationSpanData(
        model="claude-sonnet-4-5",
        model_config={"model_provider": "anthropic"},
        usage={
            "input_tokens": 3000,
            "output_tokens": 0,
            "cache_creation_input_tokens": 2000,
        },
    )

    assert processor._calculate_cost(data) == pytest.approx(0.0105)
