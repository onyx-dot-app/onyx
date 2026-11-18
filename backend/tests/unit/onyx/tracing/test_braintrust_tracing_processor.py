import sys
from unittest.mock import MagicMock, patch

import pytest

from onyx.tracing.framework.span_data import FunctionSpanData, GenerationSpanData

# The connector tests also define a top-level package named braintrust. Stub the
# optional SDK so full-suite collection cannot bind this import to that package.
with patch.dict(sys.modules, {"braintrust": MagicMock()}):
    from onyx.tracing import braintrust_tracing_processor as module
    from onyx.tracing.braintrust_tracing_processor import BraintrustTracingProcessor


def test_generation_cost_prices_cache_creation_at_write_rate() -> None:
    span = MagicMock()
    span.started_at = None
    span.ended_at = None
    span.span_data = GenerationSpanData(
        model="claude-sonnet-4-5",
        model_config={"model_provider": "anthropic"},
        usage={
            "input_tokens": 3000,
            "output_tokens": 0,
            "cache_creation_input_tokens": 2000,
        },
    )

    processor = BraintrustTracingProcessor()
    metrics = processor._generation_log_data(span)["metrics"]

    assert metrics["cost_cents"] == pytest.approx(1.05)


def test_function_spans_log_their_metadata() -> None:
    span = MagicMock()
    span.span_data = FunctionSpanData(
        name="echo",
        input="{}",
        output="ok",
        metadata={"code_mode.call_id": "code:0", "code_mode.index": 0},
    )
    data = BraintrustTracingProcessor()._function_log_data(span)
    assert data["metadata"] == {"code_mode.call_id": "code:0", "code_mode.index": 0}


def test_craft_steps_share_external_trace_and_keep_independent_spans() -> None:
    logger = MagicMock()
    observations = [MagicMock(), MagicMock()]
    logger.start_span.side_effect = observations
    processor = BraintrustTracingProcessor(logger)
    traces = [MagicMock(trace_id=f"request-{i}", name="llm_gateway") for i in range(2)]
    parent = {"traceparent": "00-" + "a" * 32 + "-" + "b" * 16 + "-01"}
    with (
        patch.object(module.braintrust, "current_span", return_value=module.NOOP_SPAN),
        patch.object(
            module.braintrust, "extract_trace_context", return_value=parent
        ) as extract,
    ):
        for trace in traces:
            trace.export.return_value = {
                "metadata": {
                    "distributed_trace_id": "a" * 32,
                    "distributed_parent_span_id": "b" * 16,
                }
            }
            processor.on_trace_start(trace)
    kwargs = [call.kwargs for call in logger.start_span.call_args_list]
    assert [entry["root_span_id"] for entry in kwargs] == ["a" * 32, "a" * 32]
    assert [entry["span_id"] for entry in kwargs] == ["request-0", "request-1"]
    assert all(entry["parent"] == parent for entry in kwargs)
    extract.assert_called_with(parent)
    for trace in reversed(traces):
        processor.on_trace_end(trace)
    for observation in observations:
        observation.end.assert_called_once()


def test_craft_turn_publishes_a_root_for_gateway_request_parents() -> None:
    logger = MagicMock()
    processor = BraintrustTracingProcessor(logger)
    trace = MagicMock(trace_id="local-root", name="craft_turn")
    trace.export.return_value = {
        "metadata": {
            "distributed_trace_id": "a" * 32,
            "distributed_root_span_id": "b" * 16,
        }
    }
    processor.on_trace_start(trace)
    kwargs = logger.start_span.call_args.kwargs
    assert kwargs["span_id"] == "b" * 16
    assert kwargs["root_span_id"] == "a" * 32
    assert kwargs["parent"] is None
    processor.on_trace_end(trace)
