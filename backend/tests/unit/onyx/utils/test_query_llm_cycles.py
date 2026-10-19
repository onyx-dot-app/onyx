"""Chat queries report the answering model's chat-loop LLM calls up to its first
answer token, so cycle counts match the work that ``first_answer_ms`` measured."""

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
def test_cycles_stop_at_the_first_answer_token(
    sink: Mock, calls_before_answer: int, calls_after_answer: int, expected: int
) -> None:
    observation = telemetry.QueryObservation(
        channel="web", mode=telemetry.QueryMode.CHAT
    )
    emitter = Emitter(Queue(), query_observation=observation)
    for _ in range(calls_before_answer):
        emitter.llm_step_started()
    observation.observe_packet(_answer())
    for _ in range(calls_after_answer):
        emitter.llm_step_started()
    observation.finish()
    event_type, data = sink.call_args.args
    assert data["llm_cycles"] == expected
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
    observation = telemetry.QueryObservation(
        channel="web", mode=telemetry.QueryMode.CHAT
    )
    slow, fast = (
        Emitter(Queue(), model_idx=i, query_observation=observation) for i in range(2)
    )
    for _ in range(4):
        slow.llm_step_started()
    fast.llm_step_started()
    observation.observe_packet(_answer(model_idx=1))
    observation.observe_packet(_answer(model_idx=0))
    observation.finish()
    assert sink.call_args.args[1]["llm_cycles"] == 1


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
