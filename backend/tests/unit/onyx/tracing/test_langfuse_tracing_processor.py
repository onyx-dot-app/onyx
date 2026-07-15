"""Unit tests for LangfuseTracingProcessor trace-attribute propagation.

These run the real Langfuse SDK (v4) with the OTLP exporter patched to capture
spans in-memory, so assertions cover what would actually be exported to
Langfuse — including the propagated trace-level attributes (user, session,
trace name, metadata) that SDK v4 requires on every observation.
"""

import threading
from collections.abc import Iterator
from collections.abc import Mapping
from typing import Any
from unittest.mock import MagicMock
from unittest.mock import patch

import pytest
from langfuse import Langfuse
from langfuse import LangfuseOtelSpanAttributes
from opentelemetry.sdk.trace import ReadableSpan
from opentelemetry.sdk.trace.export import SpanExportResult

from onyx.tracing.framework.span_data import FunctionSpanData
from onyx.tracing.langfuse_tracing_processor import LangfuseTracingProcessor

_USER_ID_ATTR = LangfuseOtelSpanAttributes.TRACE_USER_ID
_SESSION_ID_ATTR = LangfuseOtelSpanAttributes.TRACE_SESSION_ID
_TRACE_NAME_ATTR = LangfuseOtelSpanAttributes.TRACE_NAME
_TRACE_METADATA_PREFIX = f"{LangfuseOtelSpanAttributes.TRACE_METADATA}."

_captured_spans: list[ReadableSpan] = []


@pytest.fixture(scope="module")
def langfuse_client() -> Iterator[Langfuse]:
    """A real Langfuse client whose OTLP export is captured in-memory."""

    def _capture(
        _self: Any, spans: list[ReadableSpan], **_kwargs: Any
    ) -> SpanExportResult:
        _captured_spans.extend(spans)
        return SpanExportResult.SUCCESS

    with patch(
        "opentelemetry.exporter.otlp.proto.http.trace_exporter.OTLPSpanExporter.export",
        _capture,
    ):
        client = Langfuse(
            public_key="pk-lf-unit-test",
            secret_key="sk-lf-unit-test",
            host="http://localhost:9",
            tracing_enabled=True,
        )
        yield client
        client.shutdown()


@pytest.fixture
def exported_spans() -> list[ReadableSpan]:
    _captured_spans.clear()
    return _captured_spans


def _make_trace(trace_id: str, name: str, metadata: Mapping[str, Any]) -> MagicMock:
    trace = MagicMock()
    trace.trace_id = trace_id
    trace.name = name
    trace.export.return_value = {"metadata": dict(metadata)}
    return trace


def _make_span(trace_id: str, span_id: str, name: str) -> MagicMock:
    span = MagicMock()
    span.trace_id = trace_id
    span.span_id = span_id
    span.parent_id = None
    span.error = None
    span.span_data = FunctionSpanData(name=name, input=None, output=None)
    return span


def _attrs(span: ReadableSpan) -> dict[str, Any]:
    return dict(span.attributes or {})


def _span_by_name(spans: list[ReadableSpan], name: str) -> ReadableSpan:
    matches = [s for s in spans if s.name == name]
    assert len(matches) == 1, f"expected exactly one span named {name!r}"
    return matches[0]


def test_root_observation_carries_promoted_trace_attributes(
    langfuse_client: Langfuse, exported_spans: list[ReadableSpan]
) -> None:
    """user_id / chat_session_id in trace metadata must be promoted to the
    first-class user/session attributes (plus trace name and metadata) on the
    root observation so Langfuse populates the Users and Sessions views.
    """
    processor = LangfuseTracingProcessor(client=langfuse_client)

    metadata = {
        "tenant_id": "tenant-abc",
        "chat_session_id": "session-xyz",
        "user_id": "user-42",
    }
    trace = _make_trace("trace-root-attrs", "run_llm_loop", metadata)
    processor.on_trace_start(trace)
    processor.on_trace_end(trace)
    processor.force_flush()

    root = _span_by_name(exported_spans, "run_llm_loop")
    attrs = _attrs(root)
    assert attrs[_USER_ID_ATTR] == "user-42"
    assert attrs[_SESSION_ID_ATTR] == "session-xyz"
    assert attrs[_TRACE_NAME_ATTR] == "run_llm_loop"
    for key, value in metadata.items():
        assert attrs[f"{_TRACE_METADATA_PREFIX}{key}"] == value


def test_missing_user_id_still_traces(
    langfuse_client: Langfuse, exported_spans: list[ReadableSpan]
) -> None:
    """Anonymous / unattributed traces still export, just without a user."""
    processor = LangfuseTracingProcessor(client=langfuse_client)

    metadata = {"tenant_id": "tenant-abc", "chat_session_id": "session-xyz"}
    trace = _make_trace("trace-no-user", "anon_loop", metadata)
    processor.on_trace_start(trace)
    processor.on_trace_end(trace)
    processor.force_flush()

    attrs = _attrs(_span_by_name(exported_spans, "anon_loop"))
    assert _USER_ID_ATTR not in attrs
    assert attrs[_SESSION_ID_ATTR] == "session-xyz"


def test_non_string_user_id_coerced(
    langfuse_client: Langfuse, exported_spans: list[ReadableSpan]
) -> None:
    """User ids that arrive as ints (e.g. from User.id) are coerced to strings;
    v4 drops non-string propagated values outright, so coercion is required."""
    processor = LangfuseTracingProcessor(client=langfuse_client)

    trace = _make_trace(
        "trace-int-user", "int_user_loop", {"chat_session_id": "s", "user_id": 7}
    )
    processor.on_trace_start(trace)
    processor.on_trace_end(trace)
    processor.force_flush()

    attrs = _attrs(_span_by_name(exported_spans, "int_user_loop"))
    assert attrs[_USER_ID_ATTR] == "7"


def test_threaded_children_carry_user_and_session(
    langfuse_client: Langfuse, exported_spans: list[ReadableSpan]
) -> None:
    """Regression test for the SDK v4 migration: propagate_attributes() lives in
    thread-local OTel context, but Onyx creates child observations from parallel
    threads. Every child must still carry the trace's user/session/name
    attributes and parent-link to the root observation.
    """
    processor = LangfuseTracingProcessor(client=langfuse_client)

    metadata = {
        "tenant_id": "tenant-abc",
        "chat_session_id": "session-threaded",
        "user_id": "user-99",
    }
    trace = _make_trace("trace-threaded", "threaded_loop", metadata)
    processor.on_trace_start(trace)

    num_children = 8
    barrier = threading.Barrier(num_children)

    def run_child(i: int) -> None:
        span = _make_span("trace-threaded", f"span-{i}", f"tool-{i}")
        barrier.wait()  # maximize overlap between threads
        processor.on_span_start(span)
        processor.on_span_end(span)

    threads = [
        threading.Thread(target=run_child, args=(i,)) for i in range(num_children)
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    processor.on_trace_end(trace)
    processor.force_flush()

    root = _span_by_name(exported_spans, "threaded_loop")
    root_trace_id = root.context.trace_id
    root_span_id = root.context.span_id

    for i in range(num_children):
        child = _span_by_name(exported_spans, f"tool-{i}")
        attrs = _attrs(child)
        assert attrs[_USER_ID_ATTR] == "user-99"
        assert attrs[_SESSION_ID_ATTR] == "session-threaded"
        assert attrs[_TRACE_NAME_ATTR] == "threaded_loop"
        assert attrs[f"{_TRACE_METADATA_PREFIX}tenant_id"] == "tenant-abc"
        # Children created from worker threads must still land in the same
        # Langfuse trace, parented to the root observation.
        assert child.context.trace_id == root_trace_id
        assert child.parent is not None
        assert child.parent.span_id == root_span_id
