"""Chat queries report the answering model's chat-loop LLM calls up to its first
answer token. The count is recorded when the worker queues that text, and
``first_answer_ms`` when the stream writer reads it, so a lagging writer can
delay the latency but cannot add later cycles to the count."""

from queue import Queue
from unittest.mock import Mock

import pytest

from onyx.chat.emitter import Emitter
from onyx.server.query_and_chat.placement import Placement
from onyx.server.query_and_chat.streaming_models import AgentResponseDelta, Packet
from onyx.utils import fleet_query_telemetry as telemetry
from onyx.utils.fleet_telemetry import sanitize_data


def _answer(model_idx: int = 0) -> Packet:
    return Packet(
        placement=Placement(turn_index=0, model_index=model_idx),
        obj=AgentResponseDelta(content="private answer"),
    )


# The emitter's queue type; the stream writer reads it.
StreamQueue = Queue[tuple[int, Packet | Exception | object]]


def _observe_queued(
    queue: StreamQueue, observation: telemetry.QueryObservation
) -> None:
    while not queue.empty():
        _, packet = queue.get_nowait()
        assert isinstance(packet, Packet)
        observation.observe_packet(packet)


@pytest.fixture
def sink(monkeypatch: pytest.MonkeyPatch) -> Mock:
    sink = Mock()
    monkeypatch.setattr(telemetry, "emit_telemetry", sink)
    return sink


@pytest.mark.parametrize(
    "calls_before_answer,calls_after_answer,expected",
    [
        (1, 0, 1),
        (2, 0, 2),
        (5, 0, 5),
        # Text streamed before a tool call is the first answer.
        (1, 3, 1),
    ],
)
@pytest.mark.parametrize("writer_lags", [False, True])
def test_cycles_stop_at_the_first_answer_token(
    sink: Mock,
    calls_before_answer: int,
    calls_after_answer: int,
    expected: int,
    writer_lags: bool,
) -> None:
    queue: StreamQueue = Queue()
    observation = telemetry.QueryObservation(
        channel="web", mode=telemetry.QueryMode.CHAT
    )
    emitter = Emitter(queue, query_observation=observation)
    for _ in range(calls_before_answer):
        emitter.llm_step_started()
    emitter.emit(_answer())
    if not writer_lags:
        _observe_queued(queue, observation)
    # A lagging writer reads the answer after the worker starts more cycles.
    for _ in range(calls_after_answer):
        emitter.llm_step_started()
    _observe_queued(queue, observation)
    observation.finish()
    event_type, data = sink.call_args.args
    assert data["llm_cycles"] == expected
    assert data["first_answer_ms"] is not None
    assert sanitize_data(event_type, data) is not None
    assert "private" not in str(data)


def test_unanswered_queries_report_every_cycle_until_finish(sink: Mock) -> None:
    observation = telemetry.QueryObservation(
        channel="api", mode=telemetry.QueryMode.CHAT
    )
    emitter = Emitter(Queue(), query_observation=observation)
    for _ in range(3):
        emitter.llm_step_started()
    observation.failed(RuntimeError("private failure"))
    observation.finish()
    # Stop-button completion freezes the count while workers wind down.
    emitter.llm_step_started()
    observation.finish()
    sink.assert_called_once()
    data = sink.call_args.args[1]
    assert (data["outcome"], data["llm_cycles"]) == ("failure", 3)


def test_model_comparisons_report_the_first_answering_model(sink: Mock) -> None:
    queue: StreamQueue = Queue()
    observation = telemetry.QueryObservation(
        channel="web", mode=telemetry.QueryMode.CHAT
    )
    slow, fast = (
        Emitter(queue, model_idx=i, query_observation=observation) for i in range(2)
    )
    for _ in range(4):
        slow.llm_step_started()
    fast.llm_step_started()
    fast.emit(_answer())
    slow.emit(_answer())
    _observe_queued(queue, observation)
    observation.finish()
    assert sink.call_args.args[1]["llm_cycles"] == 1


def test_unanswered_model_comparisons_report_the_deepest_model(sink: Mock) -> None:
    # The models run in parallel, so the wait is the deepest model's cycles, not the sum.
    observation = telemetry.QueryObservation(
        channel="web", mode=telemetry.QueryMode.CHAT
    )
    for model_idx, calls in ((0, 2), (1, 3)):
        for _ in range(calls):
            observation.llm_step_started(model_idx=model_idx)
    observation.outcome = "canceled"
    observation.finish()
    assert sink.call_args.args[1]["llm_cycles"] == 3


def test_an_answer_that_skipped_the_emitter_has_no_cycle_count(sink: Mock) -> None:
    observation = telemetry.QueryObservation(
        channel="web", mode=telemetry.QueryMode.CHAT
    )
    observation.llm_step_started(model_idx=0)
    observation.observe_packet(_answer())
    observation.finish()
    data = sink.call_args.args[1]
    assert data["first_answer_ms"] is not None
    assert data["llm_cycles"] is None


@pytest.mark.parametrize(
    "mode", [telemetry.QueryMode.SEARCH, telemetry.QueryMode.DEEP_RESEARCH]
)
def test_only_chat_reports_cycles(sink: Mock, mode: telemetry.QueryMode) -> None:
    observation = telemetry.QueryObservation(channel="web", mode=mode)
    observation.llm_step_started(model_idx=0)
    observation.finish()
    event_type, data = sink.call_args.args
    assert data["mode"] == mode
    assert data["llm_cycles"] is None
    # Deep research keeps its tool usage; search runs no chat tools.
    assert (data["tool_usage"] is None) == (mode == telemetry.QueryMode.SEARCH)
    assert sanitize_data(event_type, data) is not None
