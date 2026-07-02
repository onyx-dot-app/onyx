"""Unit tests for the live-reload behavior of DynamicTracingProcessor."""

from typing import Any
from typing import cast
from unittest.mock import patch

from onyx.tracing.dynamic_processor import DynamicTracingProcessor
from onyx.tracing.framework.processor_interface import TracingProcessor
from onyx.tracing.framework.spans import Span
from onyx.tracing.framework.traces import Trace
from onyx.tracing.provider_config import BraintrustConfig
from onyx.tracing.provider_config import EffectiveTracingConfig

RESOLVE = "onyx.tracing.dynamic_processor.resolve_effective_tracing_config"
BUILD = "onyx.tracing.dynamic_processor.build_delegates"


class _RecordingProcessor(TracingProcessor):
    def __init__(self) -> None:
        self.calls: list[str] = []

    def on_trace_start(self, trace: Any) -> None:  # noqa: ARG002
        self.calls.append("on_trace_start")

    def on_trace_end(self, trace: Any) -> None:  # noqa: ARG002
        self.calls.append("on_trace_end")

    def on_span_start(self, span: Any) -> None:  # noqa: ARG002
        self.calls.append("on_span_start")

    def on_span_end(self, span: Any) -> None:  # noqa: ARG002
        self.calls.append("on_span_end")

    def shutdown(self) -> None:
        self.calls.append("shutdown")

    def force_flush(self) -> None:
        self.calls.append("force_flush")


class _FakeTrace:
    def __init__(self, trace_id: str) -> None:
        self.trace_id = trace_id


class _FakeSpan:
    def __init__(self, trace_id: str) -> None:
        self.trace_id = trace_id


def _trace(trace_id: str) -> Trace:
    return cast(Trace, _FakeTrace(trace_id))


def _span(trace_id: str) -> Span[Any]:
    return cast(Span[Any], _FakeSpan(trace_id))


def _braintrust_config(key: str) -> EffectiveTracingConfig:
    return EffectiveTracingConfig(braintrust=BraintrustConfig(api_key=key, project="p"))


def test_reconcile_builds_delegates() -> None:
    rec = _RecordingProcessor()
    with (
        patch(RESOLVE, return_value=_braintrust_config("k1")),
        patch(BUILD, return_value=[rec]) as mock_build,
    ):
        proc = DynamicTracingProcessor(ttl_seconds=1000)
        proc.reconcile(force=True)
        assert proc._delegates == [rec]
        mock_build.assert_called_once()


def test_ttl_throttles_repeated_reconcile() -> None:
    with (
        patch(RESOLVE, return_value=_braintrust_config("k1")) as mock_resolve,
        patch(BUILD, return_value=[_RecordingProcessor()]),
    ):
        proc = DynamicTracingProcessor(ttl_seconds=1000)
        proc.reconcile(force=True)
        # Within the TTL and not forced -> no re-read of config.
        proc.reconcile()
        proc.reconcile()
        assert mock_resolve.call_count == 1


def test_no_op_when_no_providers_enabled() -> None:
    with (
        patch(RESOLVE, return_value=EffectiveTracingConfig()),
        patch(BUILD, return_value=[]) as mock_build,
    ):
        proc = DynamicTracingProcessor(ttl_seconds=1000)
        proc.reconcile(force=True)
        assert proc._delegates == []
        mock_build.assert_called_once()
        # Forwarding to an empty delegate set must not raise.
        proc.on_trace_start(_trace("t1"))
        proc.on_span_end(_span("t1"))
        proc.on_trace_end(_trace("t1"))


def test_config_change_retires_and_shuts_down_old_delegates() -> None:
    old, new = _RecordingProcessor(), _RecordingProcessor()
    with (
        patch(
            RESOLVE, side_effect=[_braintrust_config("k1"), _braintrust_config("k2")]
        ),
        patch(BUILD, side_effect=[[old], [new]]),
    ):
        proc = DynamicTracingProcessor(ttl_seconds=1000)
        proc.reconcile(force=True)
        proc.reconcile(force=True)

        assert proc._delegates == [new]
        # No in-flight traces, so the old set is shut down immediately.
        assert "shutdown" in old.calls


def test_in_flight_trace_keeps_its_original_delegates() -> None:
    old, new = _RecordingProcessor(), _RecordingProcessor()
    with (
        patch(
            RESOLVE, side_effect=[_braintrust_config("k1"), _braintrust_config("k2")]
        ),
        patch(BUILD, side_effect=[[old], [new]]),
    ):
        proc = DynamicTracingProcessor(ttl_seconds=1000)
        proc.reconcile(force=True)  # `old` active

        trace = _trace("t1")
        proc.on_trace_start(trace)  # pins `old` to t1 (inner reconcile() is throttled)

        proc.reconcile(
            force=True
        )  # swap to `new`; `old` retired but t1 still in flight
        assert "shutdown" not in old.calls

        proc.on_span_end(_span("t1"))  # routed to the pinned `old`
        assert old.calls.count("on_span_end") == 1
        assert "on_span_end" not in new.calls

        proc.on_trace_end(trace)  # routed to `old`; then `old` drains and shuts down
        assert "on_trace_end" in old.calls
        assert "shutdown" in old.calls

        # A brand-new trace uses the current (`new`) delegates.
        proc.on_trace_start(_trace("t2"))
        assert "on_trace_start" in new.calls
