"""The sender, its privacy boundary, and the query and indexing hooks."""

import json
import statistics
import time
import uuid
from collections.abc import Generator, Iterator
from datetime import datetime, timezone
from types import SimpleNamespace
from typing import Any
from unittest.mock import Mock

import pytest

from onyx.utils import fleet_query_telemetry as query
from onyx.utils import fleet_telemetry as fleet
from tests.utils.fleet_telemetry import (
    RecordingTransport,
    Response,
    accept_all,
    make_sender,
    posted_events,
)


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
        {"connector_name": "Secret connector"},
        {"error_message": "password=secret"},
        {"connector_type": "customer-private-custom-name"},
        {"metadata": {"batch_size": float("inf")}},
        {"metadata": {"kg_enabled": True}},
        {"metadata": {"kg_coverage_days": 30}},
    ],
)
def test_privacy_boundary_rejects_unreviewed_fields(data: dict[str, Any]) -> None:
    assert not make_sender().emit("connector", data)


def test_queue_copies_safe_data_and_excludes_non_uuid_user() -> None:
    sender = make_sender()
    metadata: dict[str, Any] = {"batch_size": 10}
    data = {"connector_id": 1, "connector_type": "google_drive", "metadata": metadata}
    assert sender.emit("connector", data, user_id="private@example.com")
    metadata["password"] = "hidden"
    event = sender._take_batch()[0]
    assert event["user_id"] is None
    assert event["data"]["metadata"] == {"batch_size": 10}
    assert "hidden" not in json.dumps(event)


def test_partial_ack_retains_only_retry_missing_indices_and_same_ids() -> None:
    sender = make_sender()
    for index in range(4):
        assert sender.emit("heartbeat", {"dropped_events": index})
    captured = []

    def partial(*_args: Any, **kwargs: Any) -> Response:
        captured.append(posted_events(kwargs))
        return Response(
            {
                "results": [
                    {"index": 0, "status": "accepted"},
                    {"index": 1, "status": "retry"},
                    {"index": 2, "status": "rejected"},
                ]
            }
        )

    assert not sender.flush_once(partial)
    assert sender.sent == 1
    assert sender.dropped == 1
    assert [event["event_id"] for event in sender._pending] == [
        captured[0][1]["event_id"],
        captured[0][3]["event_id"],
    ]
    sender._blocked_until = 0

    def accept(*_args: Any, **kwargs: Any) -> Response:
        events = posted_events(kwargs)
        assert events == sender._pending
        return Response(
            {
                "results": [
                    {
                        "index": index,
                        "event_id": event["event_id"],
                        "status": "accepted",
                    }
                    for index, event in enumerate(events)
                ]
            }
        )

    assert sender.flush_once(accept)
    assert sender.sent == 3
    assert not sender._pending


def test_deferred_events_expire_without_holding_back_newer_events() -> None:
    sender = make_sender()
    assert sender.emit("heartbeat", {"dropped_events": 0})
    requests: list[list[dict[str, Any]]] = []

    def defer_first(*_args: Any, **kwargs: Any) -> Response:
        events = posted_events(kwargs)
        requests.append(events)
        return Response(
            {
                "results": [
                    {"index": i, "status": "retry" if i == 0 else "accepted"}
                    for i in range(len(events))
                ]
            }
        )

    for round_number in range(fleet._MAX_EVENT_ATTEMPTS):
        assert sender.emit("heartbeat", {"dropped_events": round_number + 1})
        delivered = sender.flush_once(defer_first)
        assert delivered == (round_number == fleet._MAX_EVENT_ATTEMPTS - 1)
        # Deferral is not an outage: the next wakeup sends again without backoff.
        assert sender._blocked_until == 0
    assert {events[0]["event_id"] for events in requests} == {
        requests[0][0]["event_id"]
    }
    assert [len(events) for events in requests] == [2] * fleet._MAX_EVENT_ATTEMPTS
    assert sender.sent == fleet._MAX_EVENT_ATTEMPTS
    assert sender.expired == sender.dropped == 1
    assert not sender._pending and not sender._attempts


def test_outage_keeps_batch_without_spending_event_attempts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clock = [0.0]
    monkeypatch.setattr(fleet.time, "monotonic", lambda: clock[0])
    sender = make_sender()
    assert sender.emit("heartbeat", {"dropped_events": 0})
    broken = Mock(side_effect=ConnectionError("PRIVATE endpoint"))
    for _ in range(2 * fleet._MAX_EVENT_ATTEMPTS):
        clock[0] += 301
        assert not sender.flush_once(broken)
    assert broken.call_count == 2 * fleet._MAX_EVENT_ATTEMPTS
    assert len(sender._pending) == 1 and not sender._attempts
    assert sender.expired == sender.dropped == 0
    clock[0] += 301
    assert sender.flush_once(accept_all)
    assert sender.sent == 1 and sender.failures == 0


def test_outage_breaker_bounds_attempts_and_shutdown_does_not_join() -> None:
    sender = make_sender()
    sender.emit("heartbeat", {"dropped_events": 0})
    broken = Mock(side_effect=TimeoutError("secret endpoint text"))
    assert not sender.flush_once(broken)
    first_id = sender._pending[0]["event_id"]
    for _ in range(20):
        assert not sender.flush_once(broken)
    broken.assert_called_once()
    assert sender._pending[0]["event_id"] == first_id
    sender._thread = Mock()
    sender.close()
    sender._thread.join.assert_not_called()
    assert not sender.emit("heartbeat", {"dropped_events": 1})


def test_emit_latency_and_bounded_memory_under_overload() -> None:
    sender = make_sender()
    elapsed = []
    for _ in range(5000):
        started = time.perf_counter_ns()
        sender.emit(
            "attempt",
            {
                "attempt_id": 1,
                "stage": "embed",
                "counter_mode": "delta",
                "counters": {"embed_chunks": 30},
                "duration_ms": 5,
            },
        )
        elapsed.append(time.perf_counter_ns() - started)
    assert len(sender._queue) == sender.capacity
    assert sender.dropped == 5000 - sender.capacity
    assert statistics.quantiles(elapsed, n=100)[98] < 1_000_000


@pytest.mark.parametrize("error_counter", fleet._ERROR_COUNTERS)
def test_stage_coalescing_preserves_counters_and_bypasses_errors(
    monkeypatch: pytest.MonkeyPatch,
    error_counter: str,
) -> None:
    clock = [100.0]
    monkeypatch.setattr(fleet.time, "monotonic", lambda: clock[0])
    sender = make_sender()
    data = {
        "attempt_id": 1,
        "stage": "embed",
        "counter_mode": "delta",
        "counters": {"embed_chunks": 30},
        "duration_ms": 5,
    }
    for _ in range(3):
        assert sender.emit("attempt", data)
    assert sender._coalesce_stages(sender._take_batch(), 100) == []
    clock[0] += 30
    combined = sender._coalesce_stages([], 100)
    assert len(combined) == 1
    assert combined[0]["data"]["counters"]["embed_chunks"] == 90
    assert combined[0]["data"]["duration_ms"] == 15
    assert sender.emit("attempt", data)
    assert sender._coalesce_stages(sender._take_batch(), 100) == []
    failure: dict[str, Any] = {
        **data,
        "counters": {"embed_chunks": 30, error_counter: 1},
    }
    assert sender.emit("attempt", failure)
    failed = sender._coalesce_stages(sender._take_batch(), 100)
    assert len(failed) == 1
    assert failed[0]["data"]["counters"][error_counter] == 1
    assert failed[0]["data"]["counters"]["embed_chunks"] == 60
    assert not sender._stage_pending


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


def test_close_delivers_coalesced_counters_within_a_bounded_wait(
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
    assert not sender._queue and not sender._pending and not sender._stage_pending


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
    flushed = Mock(return_value=True)
    monkeypatch.setattr(sender, "flush_once", flushed)
    monkeypatch.setattr(sender._stop, "wait", Mock(side_effect=sender._stop.set))
    sender._run()
    resource.assert_not_called()
    assert not sender._take_batch()


def test_first_real_answer_ignores_reasoning_tool_and_empty_delta(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from onyx.server.query_and_chat.placement import Placement
    from onyx.server.query_and_chat.streaming_models import (
        AgentResponseDelta,
        Packet,
        ReasoningDelta,
        SearchToolStart,
    )

    sink = Mock()
    monkeypatch.setattr(query, "emit_query", sink)
    ticks = iter([10.0, 10.2, 11.0])
    monkeypatch.setattr(query.time, "monotonic", lambda: next(ticks))
    placement = Placement(turn_index=0)
    packets = [
        Packet(placement=placement, obj=ReasoningDelta(reasoning="private")),
        Packet(placement=placement, obj=SearchToolStart()),
        Packet(placement=placement, obj=AgentResponseDelta(content="")),
        Packet(placement=placement, obj=AgentResponseDelta(content="private answer")),
    ]
    assert list(query.observe_chat_packets(iter(packets), channel="slack")) == packets
    event = sink.call_args.args[0]
    assert event["first_answer_ms"] == pytest.approx(200)
    assert event["total_ms"] == pytest.approx(1000)
    assert event["request_count"] == 1
    assert "private" not in json.dumps(event)


def test_query_failure_and_disconnect_do_not_replace_application_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sink = Mock()
    monkeypatch.setattr(query, "emit_query", sink)
    error = TimeoutError("token=private")

    def fail() -> Iterator[Any]:
        yield "setup"
        raise error

    with pytest.raises(TimeoutError) as raised:
        list(query.observe_chat_packets(fail(), channel="discord"))
    assert raised.value is error
    assert sink.call_args.args[0]["error_code"] == "timeout"
    assert "private" not in json.dumps(sink.call_args.args[0])
    stream = query.observe_chat_packets(iter(["setup", "answer"]), channel="web")
    next(stream)
    assert isinstance(stream, Generator)
    stream.close()
    assert sink.call_args.args[0]["outcome"] == "disconnected"


def test_stop_button_and_api_origin_map_to_reported_outcome_and_channel(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from onyx.server.query_and_chat.models import MessageOrigin
    from onyx.server.query_and_chat.placement import Placement
    from onyx.server.query_and_chat.streaming_models import OverallStop, Packet

    sink = Mock()
    monkeypatch.setattr(query, "emit_query", sink)
    stopped = Packet(
        placement=Placement(turn_index=0),
        obj=OverallStop(type="stop", stop_reason="user_cancelled"),
    )
    assert list(query.observe_chat_packets(iter([stopped]), channel="web")) == [stopped]
    assert sink.call_args.args[0]["outcome"] == "canceled"
    for origin, channel in (
        (MessageOrigin.API, "api"),
        (MessageOrigin.SLACKBOT, "slack"),
        (MessageOrigin.DISCORDBOT, "discord"),
        (MessageOrigin.WEBAPP, "web"),
        (MessageOrigin.WIDGET, "web"),
    ):
        request = SimpleNamespace(origin=origin)
        assert query._channel({"new_msg_req": request}) == channel


def test_opensearch_bulk_counts_item_acknowledgments_even_when_helper_raises(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from opensearchpy.helpers import bulk
    from opensearchpy.helpers.errors import BulkIndexError
    from opensearchpy.serializer import JSONSerializer

    from onyx.document_index.opensearch import client as opensearch
    from shared_configs.contextvars import INDEX_ATTEMPT_INFO_CONTEXTVAR

    sink = Mock()
    monkeypatch.setattr(opensearch, "emit_stage_counter", sink)
    original = Mock()
    original.transport.serializer = JSONSerializer()
    original.bulk.return_value = {
        "items": [
            {"create": {"status": 201}},
            {"create": {"status": 429, "error": {"reason": "PRIVATE"}}},
            {"create": {"status": 201}},
        ]
    }
    token = INDEX_ATTEMPT_INFO_CONTEXTVAR.set((2, 1))
    try:
        with pytest.raises(BulkIndexError):
            bulk(
                opensearch._MeasuredBulkClient(original),
                [
                    {"_index": "PRIVATE", "_id": index, "_source": {"text": "PRIVATE"}}
                    for index in range(3)
                ],
            )
    finally:
        INDEX_ATTEMPT_INFO_CONTEXTVAR.reset(token)
    assert sink.call_args.args == (
        1,
        "write",
        {"write_chunks": 2, "write_errors": 1, "write_rejected": 1},
    )
    assert "PRIVATE" not in str(sink.call_args)


def test_create_only_bulk_conflicts_are_not_write_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from opensearchpy.helpers import bulk
    from opensearchpy.serializer import JSONSerializer

    from onyx.document_index.opensearch import client as opensearch
    from shared_configs.contextvars import INDEX_ATTEMPT_INFO_CONTEXTVAR

    sink = Mock()
    monkeypatch.setattr(opensearch, "emit_stage_counter", sink)
    original = Mock()
    original.transport.serializer = JSONSerializer()
    original.bulk.return_value = {
        "items": [
            {"create": {"status": 201}},
            {
                "create": {
                    "status": 409,
                    "error": {"type": "version_conflict_engine_exception"},
                }
            },
        ]
    }
    token = INDEX_ATTEMPT_INFO_CONTEXTVAR.set((2, 1))
    try:
        bulk(
            opensearch._MeasuredBulkClient(original, benign_conflicts=True),
            [{"_op_type": "create", "_index": "i", "_id": i} for i in range(2)],
            raise_on_error=False,
        )
    finally:
        INDEX_ATTEMPT_INFO_CONTEXTVAR.reset(token)
    assert sink.call_args.args[2] == {
        "write_chunks": 1,
        "write_errors": 0,
        "write_rejected": 0,
    }


def test_generic_fetch_yields_and_failures_pass_through_without_metadata_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from onyx.background.indexing import run_docfetching as fetch

    monkeypatch.setattr(fetch, "StageEventBuffer", Mock(return_value=Mock(count=0)))
    sink = Mock()
    monkeypatch.setattr(fleet, "emit_stage_counter", sink)

    class OddDocument:
        def __len__(self) -> int:
            raise RuntimeError("PRIVATE metadata failure")

        def __bool__(self) -> bool:
            raise RuntimeError("PRIVATE metadata failure")

    unusual = OddDocument()
    values = [unusual, (unusual, None, None, None), object()]
    assert list(fetch._timed_connector_runs(values, 1)) == values
    sink.assert_not_called()
    # Even a failing telemetry callback cannot alter the actual connector tuple.
    actual = ([unusual, unusual], None, None, None)
    assert list(fetch._timed_connector_runs([actual], 1)) == [actual]
    assert sink.call_args.args == (1, "fetch", {"fetch_docs": 2, "fetch_errors": 0})
    sink.side_effect = RuntimeError("PRIVATE sender failure")
    assert list(fetch._timed_connector_runs([actual], 1)) == [actual]
    original = TimeoutError("PRIVATE connector failure")

    def broken() -> Iterator[object]:
        yield unusual
        raise original

    with pytest.raises(TimeoutError) as raised:
        list(fetch._timed_connector_runs(broken(), 1))
    assert raised.value is original


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
    assert not make_sender().emit("version", {"version": version})


@pytest.mark.parametrize("uptime", [0.0, 1.0])
def test_sender_only_emits_and_samples_resources_at_low_host_uptime(
    monkeypatch: pytest.MonkeyPatch, uptime: float
) -> None:
    monkeypatch.setattr(
        fleet,
        "time",
        SimpleNamespace(monotonic=lambda: uptime, time=time.time, time_ns=time.time_ns),
    )
    monkeypatch.setattr("onyx.__version__", "Development")
    monkeypatch.setattr(fleet, "_BUILD_SHA", "a" * 40)
    sender = make_sender()
    remote_get = Mock(side_effect=AssertionError("No telemetry configuration reads"))
    resource = Mock()
    monkeypatch.setattr("requests.get", remote_get)
    monkeypatch.setattr(
        "onyx.utils.fleet_telemetry_resources.collect_process_resource", resource
    )
    flushed = Mock(
        side_effect=lambda: sender.close() if flushed.call_count == 2 else None
    )
    monkeypatch.setattr(sender, "flush_once", flushed)
    monkeypatch.setattr(sender._stop, "wait", Mock())
    sender._run()
    remote_get.assert_not_called()
    resource.assert_called_once_with(sender)
    events = sender._take_batch()
    assert next(event for event in events if event["event_type"] == "version")[
        "data"
    ] == {"version": "dev", "commit_sha": "a" * 40}
    heartbeat = [event for event in events if event["event_type"] == "heartbeat"]
    # Two loop iterations, then one final delivery attempt after close.
    assert len(heartbeat) == 1 and flushed.call_count == 3


def test_delivery_health_retains_recent_loss_for_overlapping_producers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    now = [0.0]
    monkeypatch.setattr(fleet.time, "monotonic", lambda: now[0])
    sender = make_sender()
    assert not sender.emit("connector", {"name": "private"})
    first = sender.delivery_health()
    assert first["invalid_events"] == first["recent_dropped_events"] == 1
    assert sender.delivery_health()["recent_dropped_events"] == 1
    now[0] = 61.0
    later = sender.delivery_health()
    assert later["recent_dropped_events"] == 0 and later["dropped_events"] == 1


def test_metadata_repair_revision_and_build_sha_are_bounded() -> None:
    sender = make_sender()
    assert sender.emit(
        "version", {"version": "dev", "commit_sha": "a" * 40}, revision=1
    )
    event = sender._take_batch()[0]
    assert event["revision"] == 1
    assert not sender.emit("version", {"version": "dev", "commit_sha": "private/repo"})
    assert not sender.emit("heartbeat", {}, revision=-1)
    assert not sender.emit("heartbeat", {}, revision=True)


def test_query_ids_come_from_the_running_sender(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(fleet, "_client", None)
    assert not fleet.emit_query({"channel": "web"})
    sender = make_sender()
    monkeypatch.setattr(fleet, "_client", sender)
    assert fleet.emit_query({"channel": "web"})
    assert fleet.emit_query({"channel": "web"})
    ids = [uuid.UUID(event["data"]["query_id"]) for event in sender._take_batch()]
    assert len(set(ids)) == 2
    # Other processes have their own random high bits.
    other = make_sender()
    assert uuid.UUID(other.query_id()).int >> 64 != ids[0].int >> 64
    assert {query_id.int >> 64 for query_id in ids} == {sender._query_prefix >> 64}


@pytest.mark.parametrize(
    "email, expected",
    [
        ("PRIVATE FIRST@Onyx.App", "onyx.app"),
        ("PRIVATE@bücher.example", "xn--bcher-kva.example"),
        ("PRIVATE@http://onyx.app", None),
        ("PRIVATE@127.0.0.1", None),
        ("PRIVATE@localhost", None),
        ("PRIVATE@onyx.app@other.app", None),
    ],
)
def test_signup_only_queues_normalized_domain(
    email: str, expected: str | None, monkeypatch: pytest.MonkeyPatch
) -> None:
    sender = make_sender()
    monkeypatch.setattr(fleet, "_client", sender)
    fleet.emit_signup_domain(email, datetime.now(timezone.utc))
    records = sender._take_batch()
    assert [r["data"]["domain"] for r in records] == ([expected] if expected else [])
    assert "PRIVATE" not in str(records)
    assert "@" not in str(records)


def test_signup_survives_telemetry_queue_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(fleet, "_client", make_sender())
    monkeypatch.setattr(
        fleet, "emit_telemetry", Mock(side_effect=RuntimeError("unavailable"))
    )
    fleet.emit_signup_domain("PRIVATE@onyx.app", datetime.now(timezone.utc))


def test_license_telemetry_excludes_credentials_and_fails_open(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sender = make_sender()
    monkeypatch.setattr(fleet, "_client", sender)
    fleet.emit_license_state(True, "set")
    assert sender._take_batch()[0]["data"]["license_present"] is True
    assert (
        fleet.sanitize_data(
            "license",
            {"license_present": True, "action": "set", "license_key": "PRIVATE"},
        )
        is None
    )
    monkeypatch.setattr(sender, "emit", Mock(side_effect=RuntimeError("unavailable")))
    fleet.emit_license_state(False, "removed")


def test_delivery_receipts_only_settle_events() -> None:
    sender = make_sender()
    sender.emit("heartbeat", {"dropped_events": 0})
    # The service cannot switch off delivery through a receipt.
    response = Response(
        {"results": [{"index": 0, "status": "accepted"}], "enabled": False}
    )
    assert sender.flush_once(lambda *_args, **_kwargs: response)
    assert sender.sent == 1
    assert sender.emit("heartbeat", {"dropped_events": 0})


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
