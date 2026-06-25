"""Guards that stop a degenerate LLM stream from wedging an api-server worker.

A stream that emits empty packets (no content, reasoning, or tool calls)
indefinitely holds a worker thread blocked on the socket. These tests assert the
consumer aborts such a stream instead of looping forever, while leaving healthy
streams (including ones that interleave sparse empties with real content) intact.
"""

from collections.abc import Iterator
from typing import Any
from unittest.mock import MagicMock
from unittest.mock import patch

import pytest

from onyx.chat import llm_step as llm_step_module
from onyx.chat.llm_step import run_llm_step_pkt_generator
from onyx.llm.interfaces import ToolChoiceOptions
from onyx.llm.model_response import Delta
from onyx.llm.model_response import ModelResponseStream
from onyx.llm.model_response import StreamingChoice
from onyx.llm.multi_llm import LLMStreamError
from onyx.server.query_and_chat.placement import Placement


def _chunk(delta: Delta) -> ModelResponseStream:
    return ModelResponseStream(id="c", created="0", choice=StreamingChoice(delta=delta))


def _empty_chunk() -> ModelResponseStream:
    # No content, no reasoning, no tool calls -> hits the empty-packet branch.
    return _chunk(Delta())


def _make_llm(stream: Iterator[ModelResponseStream]) -> MagicMock:
    llm = MagicMock()
    llm.config.model_name = "test-model"
    llm.config.model_provider = "openai"
    llm.config.api_base = None
    llm.stream.return_value = stream
    return llm


def _drive(llm: MagicMock) -> tuple[list[Any], Any]:
    """Run the streaming step to completion; return (emitted_packets, result)."""
    gen = run_llm_step_pkt_generator(
        history=[],
        tool_definitions=[],
        tool_choice=ToolChoiceOptions.AUTO,
        llm=llm,
        placement=Placement(turn_index=1, tab_index=0),
        state_container=None,
        citation_processor=None,
    )
    packets: list[Any] = []
    result: Any = None
    try:
        while True:
            packets.append(next(gen))
    except StopIteration as stop:
        result, _has_reasoned = stop.value
    return packets, result


@patch("onyx.chat.llm_step.translate_history_to_llm_format", return_value=[])
def test_unbounded_empty_packets_abort_instead_of_hanging(
    _translate: MagicMock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cap = 50
    monkeypatch.setattr(
        llm_step_module, "LLM_STREAM_MAX_CONSECUTIVE_EMPTY_PACKETS", cap
    )

    consumed = 0

    def _runaway_empty_stream() -> Iterator[ModelResponseStream]:
        nonlocal consumed
        # Far more than the cap; if the guard fails this would still terminate
        # (so the test can't hang), but the assertion below pins the cap.
        for _ in range(cap * 10):
            consumed += 1
            yield _empty_chunk()

    with pytest.raises(LLMStreamError):
        _drive(_make_llm(_runaway_empty_stream()))

    # Aborted promptly at the cap, not after draining the whole stream.
    assert consumed == cap


@patch("onyx.chat.llm_step.translate_history_to_llm_format", return_value=[])
def test_sparse_empties_interleaved_with_content_do_not_abort(
    _translate: MagicMock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cap = 5
    monkeypatch.setattr(
        llm_step_module, "LLM_STREAM_MAX_CONSECUTIVE_EMPTY_PACKETS", cap
    )

    def _bursty_stream() -> Iterator[ModelResponseStream]:
        # Each burst stays one short of the cap, then a real packet resets it.
        for _ in range(10):
            for _ in range(cap - 1):
                yield _empty_chunk()
            yield _chunk(Delta(content="hello "))

    # Must complete cleanly; counter resets on every content packet.
    packets, result = _drive(_make_llm(_bursty_stream()))
    assert result is not None
    assert result.answer is not None and "hello" in result.answer


@patch("onyx.chat.llm_step.translate_history_to_llm_format", return_value=[])
def test_duration_backstop_aborts_runaway_stream(
    _translate: MagicMock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Disable the empty-packet cap so the duration backstop is what fires.
    monkeypatch.setattr(llm_step_module, "LLM_STREAM_MAX_CONSECUTIVE_EMPTY_PACKETS", 0)
    monkeypatch.setattr(llm_step_module, "LLM_STREAM_MAX_DURATION_SECONDS", 10)

    # tick 0 -> stream_start_time; tick 1 trips the cap on the first iteration.
    ticks = iter([0.0, 1000.0, 1001.0, 1002.0])
    monkeypatch.setattr(llm_step_module.time, "monotonic", lambda: next(ticks, 2000.0))

    def _slow_stream() -> Iterator[ModelResponseStream]:
        for _ in range(100):
            yield _empty_chunk()

    with pytest.raises(LLMStreamError):
        _drive(_make_llm(_slow_stream()))
