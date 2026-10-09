"""The sender, its privacy boundary, and the query and indexing hooks."""

import json
import statistics
import time
import uuid
from collections.abc import Generator, Iterator
from types import SimpleNamespace
from typing import Any
from unittest.mock import Mock

import pytest

from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.utils import fleet_query_telemetry as query
from onyx.utils import fleet_telemetry as fleet
from shared_configs.contextvars import INDEX_ATTEMPT_INFO_CONTEXTVAR
from tests.utils.fleet_telemetry import (
    RecordingTransport,
    Response,
    accept_all,
    make_sender,
)

_DELTA: dict[str, Any] = {
    "attempt_id": 1,
    "stage": "embed",
    "counter_mode": "delta",
    "counters": {"embed_chunks": 30},
    "duration_ms": 5,
}


@pytest.fixture
def clock(monkeypatch: pytest.MonkeyPatch) -> list[float]:
    """A monotonic clock that the test moves by hand."""
    now: list[float] = [100.0]
    monkeypatch.setattr(
        fleet, "time", SimpleNamespace(monotonic=lambda: now[0], time=time.time)
    )
    return now


@pytest.fixture
def query_sink(monkeypatch: pytest.MonkeyPatch) -> Mock:
    sink: Mock = Mock(return_value=True)
    monkeypatch.setattr(query, "emit_telemetry", sink)
    return sink


def _query_record(sink: Mock) -> dict[str, Any]:
    assert sink.call_count == 1
    event_type, data = sink.call_args.args
    assert event_type == "query"
    return data


def test_hot_emission_sheds_without_io_threads_or_wait(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sender = make_sender(capacity=2)
    fail = Mock(side_effect=AssertionError("hot path performed I/O"))
    monkeypatch.setattr("builtins.open", fail)
    monkeypatch.setattr("requests.post", fail)
    monkeypatch.setattr("threading.Thread.start", fail)
    assert sender.emit("heartbeat", {"dropped_events": 0})
    assert sender.emit("heartbeat", {"dropped_events": 1})
    started = time.perf_counter()
    assert not sender.emit("heartbeat", {"dropped_events": 2})
    assert time.perf_counter() - started < 0.01
    assert len(sender._queue) == 2
    assert sender.dropped == 1
    fail.assert_not_called()


@pytest.mark.parametrize(
    "data",
    [
        {"metadata": {"folder_names": ["Private project"]}},
        {"metadata": {"batch_size": "secret"}},
        {"metadata": {"batch_size": float("inf")}},
        {"metadata": {"kg_enabled": True}},
        {"connector_name": "Secret connector"},
        {"error_message": "password=secret"},
        {"connector_type": "Private name"},
        {"connector_type": "owner@example.com"},
        {"connector_type": "https://example.com/private"},
    ],
)
def test_privacy_boundary_rejects_unreviewed_fields_and_free_text(
    data: dict[str, Any],
) -> None:
    sender = make_sender()
    assert not sender.emit("connector", data)
    assert sender.invalid == sender.dropped == 1


def test_queue_keeps_a_copy_of_the_safe_data() -> None:
    sender = make_sender()
    metadata: dict[str, Any] = {"batch_size": 10}
    data = {"connector_id": 1, "connector_type": "google_drive", "metadata": metadata}
    assert sender.emit("connector", data)
    metadata["password"] = "hidden"
    event = sender._take_batch()[0]
    assert event["data"]["metadata"] == {"batch_size": 10}
    assert "hidden" not in json.dumps(event)


def test_outage_keeps_the_batch_and_backs_off(clock: list[float]) -> None:
    sender = make_sender()
    assert sender.emit("heartbeat", {"dropped_events": 0})
    broken = Mock(side_effect=ConnectionError("PRIVATE endpoint"))
    assert not sender.flush_once(broken)
    event_id: str = sender._pending[0]["event_id"]
    # During the backoff, the sender does not call the endpoint.
    assert not sender.flush_once(broken)
    assert broken.call_count == 1
    for _ in range(10):
        clock[0] += 301
        assert not sender.flush_once(broken)
    assert broken.call_count == 11 and sender.dropped == 0
    clock[0] += 301
    transport = RecordingTransport()
    assert sender.flush_once(transport)
    assert [event["event_id"] for event in transport.events] == [event_id]
    assert sender.sent == 1 and sender.failures == 0 and not sender._pending


def test_rejected_batch_is_dropped_and_not_sent_again() -> None:
    sender = make_sender()
    assert sender.emit("heartbeat", {"dropped_events": 0})
    assert not sender.flush_once(Mock(return_value=Response({}, status=422)))
    assert not sender._pending
    assert sender.rejected == sender.dropped == 1


def test_reply_totals_settle_the_whole_batch() -> None:
    sender = make_sender()
    for index in range(3):
        assert sender.emit("heartbeat", {"dropped_events": index})
    # One event accepted, one rejected, one deferred. The sender sends none again.
    reply = Response({"accepted": 1, "rejected": 1})
    assert sender.flush_once(lambda *_args, **_kwargs: reply)
    assert (sender.sent, sender.rejected, sender.dropped) == (1, 1, 2)
    assert not sender._pending


def test_emit_latency_and_bounded_memory_under_overload() -> None:
    sender = make_sender()
    elapsed = []
    for _ in range(5000):
        started = time.perf_counter_ns()
        sender.emit("attempt", _DELTA)
        elapsed.append(time.perf_counter_ns() - started)
    assert len(sender._queue) == sender.capacity
    assert sender.dropped == 5000 - sender.capacity
    assert statistics.quantiles(elapsed, n=100)[98] < 1_000_000


def test_stage_counters_are_summed_per_window(clock: list[float]) -> None:
    sender = make_sender()
    for _ in range(3):
        assert sender.emit("attempt", _DELTA)
    failed: dict[str, Any] = {
        **_DELTA,
        "counters": {"embed_chunks": 30, "embed_errors": 1},
    }
    assert sender.emit("attempt", failed)
    # The sums wait for the end of the window.
    assert sender._sum_stages(sender._take_batch()) == []
    clock[0] += fleet._STAGE_WINDOW_SECONDS
    summed = sender._sum_stages([])
    assert len(summed) == 1
    assert summed[0]["data"]["counters"] == {"embed_chunks": 120, "embed_errors": 1}
    assert summed[0]["data"]["duration_ms"] == 20
    assert not sender._stage_sums


def test_sender_reuses_http_session_and_compresses_in_background(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def accept(*args: Any, **kwargs: Any) -> Response:
        assert kwargs["headers"]["Content-Encoding"] == "gzip"
        return accept_all(*args, **kwargs)

    session = Mock()
    session.post.side_effect = accept
    factory = Mock(return_value=session)
    monkeypatch.setattr(fleet.requests, "Session", factory)
    sender = make_sender()
    for _ in range(2):
        assert sender.emit("heartbeat", {"dropped_events": 0})
        assert sender.flush_once()
    factory.assert_called_once()
    assert session.post.call_count == 2 and sender.sent == 2


def test_backlog_drains_in_consecutive_batches_per_wakeup(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = Mock()
    session.post.side_effect = accept_all
    monkeypatch.setattr(fleet.requests, "Session", Mock(return_value=session))
    sender = make_sender(capacity=1000, report_process=False)
    for index in range(800):
        assert sender.emit("heartbeat", {"dropped_events": index})
    posts_at_first_wakeup: list[int] = []

    def wait(*_args: Any) -> bool:
        posts_at_first_wakeup.append(session.post.call_count)
        sender._stop.set()
        return True

    monkeypatch.setattr(sender._stop, "wait", wait)
    sender._run()
    assert posts_at_first_wakeup == [fleet._MAX_BATCHES_PER_WAKEUP]
    # The final flush after close delivers the remainder.
    assert sender.sent == 800 and session.post.call_count == 8


def test_close_delivers_summed_counters_within_a_bounded_wait(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    transport = RecordingTransport()
    session = Mock()
    session.post.side_effect = transport
    monkeypatch.setattr(fleet.requests, "Session", Mock(return_value=session))
    sender = make_sender(report_process=False)
    sender.start()
    for _ in range(3):
        assert sender.emit(
            "attempt",
            {
                "attempt_id": 7,
                "stage": "fetch",
                "counter_mode": "delta",
                "counters": {"fetch_docs": 2},
                "duration_ms": 4,
            },
        )
    started = time.monotonic()
    sender.close(flush_timeout=2.0)
    assert time.monotonic() - started < 2.0
    assert sender._thread is not None and not sender._thread.is_alive()
    assert len(transport.events) == 1
    assert transport.events[0]["data"]["counters"] == {"fetch_docs": 6}
    assert not sender.emit("heartbeat", {"dropped_events": 0})


def test_final_flush_sends_every_batch_of_stage_counters(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    transport = RecordingTransport()
    session = Mock()
    session.post.side_effect = transport
    monkeypatch.setattr(fleet.requests, "Session", Mock(return_value=session))
    sender = make_sender(capacity=512, report_process=False)
    stages: dict[str, str] = {"fetch": "fetch_docs", "embed": "embed_chunks"}
    for index in range(250):
        stage: str = ("fetch", "embed")[index % 2]
        assert sender.emit(
            "attempt",
            {
                "attempt_id": 7,
                "stage": stage,
                "counter_mode": "delta",
                "counters": {stages[stage]: 1},
            },
        )
    # Three batches are queued when the sender stops.
    sender.close()
    started = time.monotonic()
    sender._run()
    assert time.monotonic() - started < 1.0
    totals: dict[str, int] = {}
    for event in transport.events:
        stage = event["data"]["stage"]
        totals[stage] = totals.get(stage, 0) + event["data"]["counters"][stages[stage]]
    assert totals == {"fetch": 125, "embed": 125}
    assert not sender._queue and not sender._pending and not sender._stage_sums


def test_close_waits_for_nothing_during_an_outage() -> None:
    sender = make_sender(report_process=False)
    sender.emit("heartbeat", {"dropped_events": 0})
    sender._blocked_until = time.monotonic() + 300
    sender.start()
    started = time.monotonic()
    sender.close(flush_timeout=2.0)
    assert time.monotonic() - started < 0.5
    assert len(sender._queue) == 1


def test_short_lived_sender_only_delivers_hook_events(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    resource = Mock()
    monkeypatch.setattr(
        "onyx.utils.fleet_telemetry_resources.collect_process_resource", resource
    )
    sender = make_sender(report_process=False)
    monkeypatch.setattr(sender, "flush_once", Mock(return_value=True))
    monkeypatch.setattr(sender._stop, "wait", Mock(side_effect=sender._stop.set))
    sender._run()
    resource.assert_not_called()
    assert not sender._take_batch()


@pytest.mark.parametrize("uptime", [0.0, 1.0])
def test_sender_reports_the_process_at_low_host_uptime(
    monkeypatch: pytest.MonkeyPatch, uptime: float
) -> None:
    monkeypatch.setattr(
        fleet, "time", SimpleNamespace(monotonic=lambda: uptime, time=time.time)
    )
    monkeypatch.setattr("onyx.__version__", "Development")
    sender = make_sender()
    resource = Mock()
    monkeypatch.setattr(
        "onyx.utils.fleet_telemetry_resources.collect_process_resource", resource
    )
    flushed = Mock(
        side_effect=lambda: sender.close() if flushed.call_count == 2 else None
    )
    monkeypatch.setattr(sender, "flush_once", flushed)
    monkeypatch.setattr(sender._stop, "wait", Mock())
    sender._run()
    resource.assert_called_once_with(sender)
    events = sender._take_batch()
    assert [event["event_type"] for event in events] == [
        "runtime",
        "version",
        "heartbeat",
    ]
    assert events[0]["data"] == {
        "service_instance_id": sender.instance_id,
        "reason": "started",
    }
    assert events[1]["data"] == {"version": "dev"}
    # Two loop iterations, then one final delivery attempt after close.
    assert flushed.call_count == 3


def test_delivery_health_reports_loss_since_the_previous_heartbeat() -> None:
    sender = make_sender()
    assert not sender.emit("connector", {"name": "private"})
    first = sender.delivery_health()
    assert first["invalid_events"] == first["recent_dropped_events"] == 1
    later = sender.delivery_health()
    assert later["recent_dropped_events"] == 0 and later["dropped_events"] == 1


@pytest.mark.parametrize(
    "version", ["v4.9.0-cloud.0-dev", "1.2.3-cloud.42-rc.1-dev", "1.2.3-beta"]
)
def test_version_accepts_only_bounded_approved_suffix_chains(version: str) -> None:
    assert make_sender().emit("version", {"version": version})


@pytest.mark.parametrize(
    "version",
    [
        "v4.9.0-PRIVATE",
        "1.2.3-cloud.0-private-folder",
        "1.2.3-dev-dev-dev-dev",
        "1.2.3-cloud.123456789",
    ],
)
def test_version_rejects_private_or_unbounded_suffixes(version: str) -> None:
    assert not fleet.is_valid_version(version)


def test_deployment_kill_switch_prevents_sender_startup(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(fleet, "DISABLE_TELEMETRY", True)
    monkeypatch.setattr(fleet, "_client", None)
    sender = Mock(
        side_effect=AssertionError("Disabled telemetry must not create a sender")
    )
    monkeypatch.setattr(fleet, "BoundedTelemetry", sender)
    assert fleet.start_telemetry("api") is None
    assert not fleet.emit_telemetry("heartbeat", {})
    sender.assert_not_called()


def test_first_real_answer_ignores_reasoning_tool_and_empty_delta(
    monkeypatch: pytest.MonkeyPatch, query_sink: Mock
) -> None:
    from onyx.server.query_and_chat.placement import Placement
    from onyx.server.query_and_chat.streaming_models import (
        AgentResponseDelta,
        Packet,
        ReasoningDelta,
        SearchToolStart,
    )

    ticks = iter([10.0, 10.2])
    monkeypatch.setattr(query, "time", SimpleNamespace(monotonic=lambda: next(ticks)))
    placement = Placement(turn_index=0)
    packets = [
        Packet(placement=placement, obj=ReasoningDelta(reasoning="private")),
        Packet(placement=placement, obj=SearchToolStart()),
        Packet(placement=placement, obj=AgentResponseDelta(content="")),
        Packet(placement=placement, obj=AgentResponseDelta(content="private answer")),
    ]
    assert list(query.observe_chat_packets(iter(packets), channel="slack")) == packets
    record = _query_record(query_sink)
    assert record["first_answer_ms"] == pytest.approx(200)
    assert record["outcome"] == "success" and record["channel"] == "slack"
    assert "private" not in json.dumps(record)


def test_failed_tool_call_does_not_fail_the_query(query_sink: Mock) -> None:
    from onyx.server.query_and_chat.placement import Placement
    from onyx.server.query_and_chat.streaming_models import (
        AgentResponseDelta,
        Packet,
        PacketException,
    )

    placement = Placement(turn_index=0)
    packets = [
        Packet(
            placement=placement,
            obj=PacketException(exception=RuntimeError("PRIVATE tool failure")),
        ),
        Packet(placement=placement, obj=AgentResponseDelta(content="answer")),
    ]
    assert list(query.observe_chat_packets(iter(packets), channel="web")) == packets
    assert _query_record(query_sink)["outcome"] == "success"


@pytest.mark.parametrize(
    "code, reported", [("QUERY_REJECTED", False), ("STREAM_WRITER_ERROR", True)]
)
def test_a_chat_that_a_hook_rejects_is_not_a_failed_query(
    query_sink: Mock, code: str, reported: bool
) -> None:
    from onyx.chat.models import StreamingError

    packets = [StreamingError(error="PRIVATE reason", error_code=code)]
    assert list(query.observe_chat_packets(iter(packets), channel="web")) == packets
    assert query_sink.called is reported
    if reported:
        record = _query_record(query_sink)
        assert record["outcome"] == "failure"
        assert "PRIVATE" not in json.dumps(record)


def test_query_failure_and_disconnect_do_not_replace_application_errors(
    query_sink: Mock,
) -> None:
    error = TimeoutError("token=private")

    def fail() -> Iterator[Any]:
        yield "setup"
        raise error

    with pytest.raises(TimeoutError) as raised:
        list(query.observe_chat_packets(fail(), channel="discord"))
    assert raised.value is error
    record = _query_record(query_sink)
    assert record["outcome"] == "failure" and record["error_code"] == "timeout"
    assert "private" not in json.dumps(record)
    query_sink.reset_mock()
    stream = query.observe_chat_packets(iter(["setup", "answer"]), channel="web")
    next(stream)
    assert isinstance(stream, Generator)
    stream.close()
    assert _query_record(query_sink)["outcome"] == "disconnected"


@pytest.mark.parametrize(
    "code, reported",
    [(OnyxErrorCode.INVALID_INPUT, False), (OnyxErrorCode.BAD_GATEWAY, True)],
)
def test_rejected_requests_are_not_failed_queries(
    query_sink: Mock, code: OnyxErrorCode, reported: bool
) -> None:
    @query.telemetry_query(mode="search")
    def search() -> None:
        raise OnyxError(code)

    with pytest.raises(OnyxError):
        search()
    assert query_sink.called is reported


def test_search_stream_times_the_first_results(
    monkeypatch: pytest.MonkeyPatch, query_sink: Mock
) -> None:
    class SearchDocsPacket:
        pass

    ticks = iter([1.0, 1.5])
    monkeypatch.setattr(query, "time", SimpleNamespace(monotonic=lambda: next(ticks)))

    @query.telemetry_query(mode="search")
    def stream() -> Iterator[object]:
        yield object()
        yield SearchDocsPacket()

    assert len(list(stream())) == 2
    record = _query_record(query_sink)
    assert record["time_to_results_ms"] == pytest.approx(500)
    assert (record["channel"], record["mode"]) == ("web", "search")


def test_stop_button_and_api_origin_map_to_reported_outcome_and_channel(
    query_sink: Mock,
) -> None:
    from onyx.server.query_and_chat.models import MessageOrigin
    from onyx.server.query_and_chat.placement import Placement
    from onyx.server.query_and_chat.streaming_models import OverallStop, Packet

    stopped = Packet(
        placement=Placement(turn_index=0),
        obj=OverallStop(type="stop", stop_reason="user_cancelled"),
    )
    assert list(query.observe_chat_packets(iter([stopped]), channel="web")) == [stopped]
    assert _query_record(query_sink)["outcome"] == "canceled"
    for origin, channel in (
        (MessageOrigin.API, "api"),
        (MessageOrigin.SLACKBOT, "slack"),
        (MessageOrigin.DISCORDBOT, "discord"),
        (MessageOrigin.WEBAPP, "web"),
        (MessageOrigin.WIDGET, "web"),
    ):
        request = SimpleNamespace(origin=origin)
        assert query._channel({"new_msg_req": request}) == channel


def test_each_query_has_its_own_id(query_sink: Mock) -> None:
    for _ in range(2):
        query.QueryObservation(channel="web", mode="chat").finish()
    ids = {uuid.UUID(call.args[1]["query_id"]) for call in query_sink.call_args_list}
    assert len(ids) == 2


def test_bulk_write_reports_chunks_only_for_an_index_attempt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from onyx.document_index.opensearch import client as opensearch

    sink = Mock()
    monkeypatch.setattr(opensearch, "emit_stage_counter", sink)
    opensearch._report_written_chunks(3, 1, time.monotonic())
    sink.assert_not_called()
    token = INDEX_ATTEMPT_INFO_CONTEXTVAR.set((2, 7))
    try:
        opensearch._report_written_chunks(3, 1, time.monotonic())
    finally:
        INDEX_ATTEMPT_INFO_CONTEXTVAR.reset(token)
    assert sink.call_args.args == (7, "write", {"write_chunks": 3, "write_errors": 1})


def test_fetch_counts_connector_batches_and_passes_every_yield_through(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from onyx.background.indexing import run_docfetching as fetch

    monkeypatch.setattr(fetch, "StageEventBuffer", Mock(return_value=Mock(count=0)))
    sink = Mock()
    monkeypatch.setattr(fetch, "emit_stage_counter", sink)
    other: list[object] = [object(), ("not", "a", "batch")]
    assert list(fetch._timed_connector_runs(other, 1)) == other
    sink.assert_not_called()
    batch = ([object(), object()], None, None, None)
    assert list(fetch._timed_connector_runs([batch], 1)) == [batch]
    assert sink.call_args.args == (1, "fetch", {"fetch_docs": 2, "fetch_errors": 0})
    error = TimeoutError("PRIVATE connector failure")

    def broken() -> Iterator[object]:
        yield batch
        raise error

    with pytest.raises(TimeoutError) as raised:
        list(fetch._timed_connector_runs(broken(), 1))
    assert raised.value is error
    assert sink.call_args.args == (1, "fetch", {"fetch_errors": 1})
