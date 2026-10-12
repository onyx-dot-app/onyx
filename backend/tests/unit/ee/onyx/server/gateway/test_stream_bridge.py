import queue
import threading
from collections.abc import Callable, Iterator
from contextlib import nullcontext
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from ee.onyx.server.gateway import api, stream_bridge
from ee.onyx.server.gateway.stream_bridge import (
    finalize_tool_calls,
    merge_tool_call_delta,
)
from onyx.llm.model_response import (
    ChatCompletionDeltaToolCall,
    Delta,
    ModelResponseStream,
    ResponseFunctionCall,
    StreamingChoice,
)
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
    llm.stream_raw.return_value = chunks()
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


def _delta(
    index: int,
    *,
    id: str | None = None,
    name: str | None = None,
    arguments: str | None = None,
) -> ChatCompletionDeltaToolCall:
    fn = (
        ResponseFunctionCall(name=name, arguments=arguments)
        if (name is not None or arguments is not None)
        else None
    )
    return ChatCompletionDeltaToolCall(id=id, index=index, type="function", function=fn)


def testmerge_tool_call_delta_single_call_across_chunks() -> None:
    buf: dict[int, ChatCompletionDeltaToolCall] = {}
    # Chunk 1: id + name + arg fragment 1
    merge_tool_call_delta(
        buf, _delta(0, id="call_1", name="search", arguments='{"q":"')
    )
    # Chunk 2: arg fragment 2
    merge_tool_call_delta(buf, _delta(0, arguments="hello"))
    # Chunk 3: arg fragment 3
    merge_tool_call_delta(buf, _delta(0, arguments='"}'))

    finalized = finalize_tool_calls(buf)
    assert finalized is not None
    assert len(finalized) == 1
    tc = finalized[0]
    assert tc.id == "call_1"
    assert tc.function.name == "search"
    assert tc.function.arguments == '{"q":"hello"}'


def testmerge_tool_call_delta_multiple_calls_by_index() -> None:
    buf: dict[int, ChatCompletionDeltaToolCall] = {}
    # Interleaved deltas across two tool calls (indices 0 and 1)
    merge_tool_call_delta(buf, _delta(0, id="call_a", name="fn_a", arguments='{"x":'))
    merge_tool_call_delta(buf, _delta(1, id="call_b", name="fn_b", arguments='{"y":'))
    merge_tool_call_delta(buf, _delta(0, arguments="1}"))
    merge_tool_call_delta(buf, _delta(1, arguments="2}"))

    finalized = finalize_tool_calls(buf)
    assert finalized is not None
    assert len(finalized) == 2
    # Sorted by index
    assert finalized[0].id == "call_a"
    assert finalized[0].function.name == "fn_a"
    assert finalized[0].function.arguments == '{"x":1}'
    assert finalized[1].id == "call_b"
    assert finalized[1].function.name == "fn_b"
    assert finalized[1].function.arguments == '{"y":2}'


def testmerge_tool_call_delta_does_not_overwrite_first_id_or_name() -> None:
    buf: dict[int, ChatCompletionDeltaToolCall] = {}
    merge_tool_call_delta(
        buf, _delta(0, id="call_real", name="real_fn", arguments="{}")
    )
    # A later delta that (incorrectly) supplies a different id/name must not
    # clobber the first-seen values.
    merge_tool_call_delta(
        buf, _delta(0, id="call_ignored", name="ignored_fn", arguments="")
    )
    finalized = finalize_tool_calls(buf)
    assert finalized is not None
    assert finalized[0].id == "call_real"
    assert finalized[0].function.name == "real_fn"


def testfinalize_tool_calls_skips_entries_missing_required_fields() -> None:
    buf: dict[int, ChatCompletionDeltaToolCall] = {}
    # Complete entry
    merge_tool_call_delta(buf, _delta(0, id="call_ok", name="fn_ok", arguments="{}"))
    # Incomplete entry — never got an id or name
    merge_tool_call_delta(buf, _delta(1, arguments='{"partial":true}'))
    finalized = finalize_tool_calls(buf)
    assert finalized is not None
    assert len(finalized) == 1
    assert finalized[0].id == "call_ok"


def testfinalize_tool_calls_returns_none_for_empty_buffer() -> None:
    assert finalize_tool_calls({}) is None
