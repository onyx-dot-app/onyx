"""Exercise distributed turn identities through the pinned tracing SDKs."""

from typing import Any
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest
from braintrust.logger import (
    BraintrustState,
    Logger,
    ObjectMetadata,
    OrgProjectMetadata,
)
from braintrust.util import LazyValue
from langfuse import Langfuse
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from onyx.tracing.braintrust_tracing_processor import BraintrustTracingProcessor
from onyx.tracing.framework.provider import DefaultTraceProvider
from onyx.tracing.langfuse_tracing_processor import LangfuseTracingProcessor


@pytest.mark.parametrize("explicit_logger", [True, False])
def test_braintrust_requests_are_children_of_the_turn_root(
    explicit_logger: bool,
) -> None:
    state = BraintrustState()
    sdk_logger = Logger(
        LazyValue(
            lambda: OrgProjectMetadata(
                org_id=str(uuid4()),
                project=ObjectMetadata(id=str(uuid4()), name="test", full_info={}),
            ),
            use_mutex=False,
        ),
        state=state,
    )
    exported: list[dict[str, Any]] = []
    sink = MagicMock()

    def capture(*items: LazyValue[dict[str, Any]]) -> None:
        exported.extend(item.get() for item in items)

    sink.log.side_effect = capture
    provider = DefaultTraceProvider()
    provider.register_processor(
        BraintrustTracingProcessor(sdk_logger if explicit_logger else None)
    )
    turn_id = uuid4().hex
    root = provider.create_trace(
        "craft_turn",
        metadata={
            "distributed_trace_id": turn_id,
            "distributed_root_span_id": turn_id[:16],
        },
    )
    requests = [
        provider.create_trace(
            "llm_gateway",
            metadata={
                "distributed_trace_id": turn_id,
                "distributed_parent_span_id": turn_id[:16],
            },
        )
        for _ in range(2)
    ]
    with (
        patch.object(state, "global_bg_logger", return_value=sink),
        patch("braintrust.logger.current_logger", return_value=sdk_logger),
        patch("braintrust.current_logger", return_value=sdk_logger),
    ):
        with sdk_logger.start_span(name="unrelated") as ambient:
            root.start()
        for request in requests:
            request.start()
        for request in reversed(requests):
            request.finish()
        root.finish()

    rows = {
        event["span_id"]: event
        for event in exported
        if "span_id" in event and event["span_id"] != ambient.span_id
    }
    assert set(rows) == {turn_id[:16], *(request.trace_id for request in requests)}
    assert {event["root_span_id"] for event in rows.values()} == {turn_id}
    assert not rows[turn_id[:16]].get("span_parents")
    for request in requests:
        assert rows[request.trace_id]["span_parents"] == [turn_id[:16]]


def test_langfuse_requests_export_under_the_same_turn_trace() -> None:
    exporter = InMemorySpanExporter()
    tracer_provider = TracerProvider()
    client = Langfuse(
        public_key=f"test-{uuid4()}",
        secret_key="test",
        tracer_provider=tracer_provider,
        span_exporter=exporter,
    )
    provider = DefaultTraceProvider()
    provider.register_processor(LangfuseTracingProcessor(client=client))
    turn_id = uuid4().hex
    try:
        requests = [
            provider.create_trace(
                "llm_gateway", metadata={"distributed_trace_id": turn_id}
            )
            for _ in range(2)
        ]
        for request in requests:
            request.start()
        for request in reversed(requests):
            request.finish()
        with provider.create_trace("llm_gateway"):
            pass
        client.flush()
        spans = exporter.get_finished_spans()
        assert len(spans) == 3
        contexts = [span.context for span in spans if span.context is not None]
        assert len(contexts) == 3
        assert [context.trace_id for context in contexts[:2]] == [int(turn_id, 16)] * 2
        assert contexts[2].trace_id != int(turn_id, 16)
        assert len({context.span_id for context in contexts}) == 3
    finally:
        client.shutdown()
