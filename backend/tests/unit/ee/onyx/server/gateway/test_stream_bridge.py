import queue
import threading
from collections.abc import Callable, Iterator
from contextlib import nullcontext
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from ee.onyx.server.gateway import api, stream_bridge
from onyx.llm.model_response import Delta, ModelResponseStream, StreamingChoice
from onyx.llm.models import ReasoningEffort, Usage
from onyx.tracing.flows import LLMFlow


def _chunk(usage: Usage | None = None) -> ModelResponseStream:
    return ModelResponseStream(
        id="chunk",
        created="0",
        choice=StreamingChoice(delta=Delta(content="text")),
        usage=usage,
    )


@pytest.mark.parametrize(
    "worker,extra",
    [
        (api._stream_worker, {"structured_response_format": None}),
        (api._responses_stream_worker, {"response_id": "response", "created_at": 0}),
        (api._anthropic_stream_worker, {"message_id": "message"}),
    ],
)
@pytest.mark.parametrize("cancel_on_usage", [False, True])
def test_disconnect_records_trailing_usage(
    worker: Callable[..., None], extra: dict[str, Any], cancel_on_usage: bool
) -> None:
    cancelled = threading.Event()
    closed = threading.Event()
    usage = Usage(
        prompt_tokens=2,
        completion_tokens=3,
        total_tokens=5,
        cache_creation_input_tokens=0,
        cache_read_input_tokens=0,
    )

    def chunks() -> Iterator[ModelResponseStream]:
        try:
            if not cancel_on_usage:
                cancelled.set()
                yield _chunk()
            cancelled.set()
            yield _chunk(usage)
        finally:
            closed.set()

    llm = MagicMock()
    llm.stream.return_value = chunks()
    span = MagicMock()
    with (
        patch.object(api, "_gateway_trace", return_value=nullcontext()),
        patch.object(api, "llm_generation_span", return_value=nullcontext(span)),
        patch.object(stream_bridge, "record_llm_span_output") as record,
    ):
        worker(
            llm=llm,
            flow=LLMFlow.CRAFT_LLM_GENERATION,
            messages=[],
            tools=None,
            tool_choice=None,
            max_tokens=100,
            reasoning_effort=ReasoningEffort.AUTO,
            model="test",
            out=queue.Queue(),
            cancelled=cancelled,
            **extra,
        )

    record.assert_called_once()
    assert record.call_args.kwargs["usage"] == usage
    assert closed.is_set()


@pytest.mark.parametrize("limit", ["chunks", "time"])
def test_usage_drain_stops_at_limit(limit: str) -> None:
    closed = threading.Event()
    state = stream_bridge._StreamAccumulator()

    def chunks() -> Iterator[ModelResponseStream]:
        try:
            while True:
                yield _chunk()
        finally:
            closed.set()

    state.upstream = chunks()
    cancelled = threading.Event()
    cancelled.set()
    with (
        patch.object(stream_bridge, "_USAGE_DRAIN_MAX_CHUNKS", 2, create=True),
        patch.object(
            stream_bridge,
            "_USAGE_DRAIN_MAX_SECONDS",
            0 if limit == "time" else 10,
            create=True,
        ),
        stream_bridge._stream_worker_guard(
            None,
            "test",
            state,
            label="test",
            emit_error=MagicMock(),
            out=queue.Queue(),
            cancelled=cancelled,
        ),
    ):
        pass

    assert len(state.content) == (1 if limit == "time" else 2)
    assert closed.is_set()
