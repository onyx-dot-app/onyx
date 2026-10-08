import gzip
import io
import json
import statistics
import time
from collections.abc import Generator, Iterator
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import Mock

import pytest

from onyx.utils import fleet_query_telemetry as query
from onyx.utils import fleet_telemetry as fleet
from onyx.utils.fleet_telemetry_collector import (
    FleetCollector,
    classify_local_error,
    safe_attempt_error_data,
    safe_connector_data,
)
from onyx.utils.fleet_telemetry_kubernetes import KubernetesCollector, quantity


def client(capacity: int = 16, report_process: bool = True) -> fleet.BoundedTelemetry:
    return fleet.BoundedTelemetry(
        fleet.TelemetryConfig(
            "http://localhost:8787",
            "test-token",
            "11111111-1111-4111-8111-111111111111",
            "test-deployment",
            b"installation-secret-not-central-token",
            capacity=capacity,
        ),
        report_process=report_process,
    )


class Response:
    def __init__(self, result: Any, status: int = 200) -> None:
        self.ok = 200 <= status < 300
        self.status_code = status
        self.headers: dict[str, str] = {}
        self.raw = io.BytesIO(json.dumps(result).encode())

    def __enter__(self) -> "Response":
        return self

    def __exit__(self, *args: Any) -> None:
        self.raw.close()


def accept_all(*_args: Any, **kwargs: Any) -> Response:
    events = json.loads(gzip.decompress(kwargs["data"]))["events"]
    return Response(
        {"results": [{"index": i, "status": "accepted"} for i in range(len(events))]}
    )


def test_hot_emission_sheds_without_io_threads_or_wait(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sender = client(capacity=2)
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
        {"scope_hashes": ["folder/Private"]},
        {"connector_type": "customer-private-custom-name"},
        {"metadata": {"batch_size": float("inf")}},
        {"metadata": {"kg_enabled": True}},
        {"metadata": {"kg_coverage_days": 30}},
    ],
)
def test_privacy_boundary_rejects_unreviewed_fields(data: dict[str, Any]) -> None:
    assert not client().emit("connector", data)


def test_queue_copies_safe_data_and_excludes_non_uuid_user() -> None:
    sender = client()
    metadata: dict[str, Any] = {"batch_size": 10}
    data = {"connector_id": 1, "connector_type": "google_drive", "metadata": metadata}
    assert sender.emit("connector", data, user_id="private@example.com")
    metadata["password"] = "hidden"
    event = sender._take_batch()[0]
    assert event["user_id"] is None
    assert event["data"]["metadata"] == {"batch_size": 10}
    assert "hidden" not in json.dumps(event)


def test_partial_ack_retains_only_retry_missing_indices_and_same_ids() -> None:
    sender = client()
    for index in range(4):
        assert sender.emit("heartbeat", {"dropped_events": index})
    captured = []

    def partial(*_args: Any, **kwargs: Any) -> Response:
        captured.append(json.loads(gzip.decompress(kwargs["data"]))["events"])
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
        events = json.loads(gzip.decompress(kwargs["data"]))["events"]
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
    sender = client()
    assert sender.emit("heartbeat", {"dropped_events": 0})
    requests: list[list[dict[str, Any]]] = []

    def defer_first(*_args: Any, **kwargs: Any) -> Response:
        events = json.loads(gzip.decompress(kwargs["data"]))["events"]
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
    sender = client()
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
    sender = client()
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
    sender = client()
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
    assert len(sender._queue) == sender.config.capacity
    assert sender.dropped == 5000 - sender.config.capacity
    assert statistics.quantiles(elapsed, n=100)[98] < 1_000_000


@pytest.mark.parametrize(
    "error_counter",
    ["error_count", "fetch_errors", "embed_errors", "write_errors", "write_rejected"],
)
def test_stage_coalescing_preserves_counters_and_bypasses_errors(
    monkeypatch: pytest.MonkeyPatch,
    error_counter: str,
) -> None:
    clock = [100.0]
    monkeypatch.setattr(fleet.time, "monotonic", lambda: clock[0])
    sender = client()
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
    failure: dict[str, Any] = (
        {**data, "error_count": 1}
        if error_counter == "error_count"
        else {**data, "counters": {"embed_chunks": 30, error_counter: 1}}
    )
    assert sender.emit("attempt", failure)
    failed = sender._coalesce_stages(sender._take_batch(), 100)
    assert len(failed) == 1
    errors: dict[str, Any] = (
        failed[0]["data"]
        if error_counter == "error_count"
        else failed[0]["data"]["counters"]
    )
    assert errors[error_counter] == 1
    assert failed[0]["data"]["counters"]["embed_chunks"] == 60
    assert not sender._stage_pending


@pytest.mark.parametrize("status", [410, 500])
def test_kubernetes_expired_page_recovers_but_transient_failure_keeps_cursor(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, status: int
) -> None:
    from onyx.utils import fleet_telemetry_kubernetes as kubernetes

    clock: list[float] = [100.0]
    monkeypatch.setattr(kubernetes, "time", SimpleNamespace(monotonic=lambda: clock[0]))
    sender: fleet.BoundedTelemetry = client()
    watcher: KubernetesCollector = KubernetesCollector(sender)
    watcher.token_path = tmp_path / "token"
    watcher.token_path.write_text("test-token")
    pages: list[dict[str, Any]] = []

    def get(path: str, **kwargs: Any) -> Response:
        if "/apis/metrics" in path:
            return Response({"items": []})
        pages.append(dict(kwargs["params"]))
        if len(pages) == 1:
            return Response({"items": [], "metadata": {"continue": "page-two"}})
        if len(pages) == 2:
            return Response({}, status=status)
        return Response({"items": [], "metadata": {}})

    monkeypatch.setattr("requests.get", get)
    watcher.tick()
    clock[0] += 30
    watcher.tick()
    watcher.tick()
    assert len(pages) == 2  # Keep the bounded cadence after a rejected page.
    clock[0] += 30
    watcher.tick()
    assert pages == [
        {"limit": 25},
        {"limit": 25, "continue": "page-two"},
        {"limit": 25} if status == 410 else {"limit": 25, "continue": "page-two"},
    ]
    assert watcher.errors == 1


@pytest.mark.parametrize("explicit_url", [False, True])
def test_queue_collection_inherits_tls_without_overriding_explicit_url(
    monkeypatch: pytest.MonkeyPatch, explicit_url: bool
) -> None:
    from dataclasses import replace

    from onyx.configs import app_configs
    from onyx.utils import fleet_telemetry_collector as source

    monkeypatch.setattr(source, "collector_engine", Mock(return_value=Mock()))
    monkeypatch.setattr(app_configs, "USE_REDIS_IAM_AUTH", False)
    monkeypatch.setattr(app_configs, "REDIS_SSL", True)
    monkeypatch.setattr(app_configs, "REDIS_SSL_CERT_REQS", "required")
    monkeypatch.setattr(app_configs, "REDIS_SSL_CHECK_HOSTNAME", True)
    monkeypatch.setattr(app_configs, "REDIS_SSL_CA_CERTS", "/test/redis-ca.crt")
    monkeypatch.setattr(app_configs, "REDIS_SSL_CERTFILE", "/test/redis-client.crt")
    monkeypatch.setattr(app_configs, "REDIS_SSL_KEYFILE", "/test/redis-client.key")
    if explicit_url:
        monkeypatch.setenv("ONYX_TELEMETRY_REDIS_URL", "rediss://custom:6380/15")
    else:
        monkeypatch.delenv("ONYX_TELEMETRY_REDIS_URL", raising=False)
    sender: fleet.BoundedTelemetry = client()
    sender.config = replace(sender.config, auto_enroll=True)
    collector: FleetCollector = FleetCollector(sender, "postgresql://test", ["public"])
    factory: Mock = Mock(side_effect=RuntimeError("connection intercepted"))
    monkeypatch.setattr("redis.Redis.from_url", factory)
    with pytest.raises(RuntimeError, match="connection intercepted"):
        collector.collect_queues()
    options: dict[str, Any] = dict(factory.call_args.kwargs)
    assert factory.call_args.args[0].startswith("rediss://")
    assert options["socket_timeout"] == options["socket_connect_timeout"] == 0.2
    assert options["max_connections"] == 1
    if explicit_url:
        assert not any(key.startswith("ssl") for key in options)
    else:
        assert options["ssl_cert_reqs"] == "required"
        assert options["ssl_check_hostname"] is True
        assert options["ssl_ca_certs"] == "/test/redis-ca.crt"
        assert options["ssl_certfile"] == "/test/redis-client.crt"
        assert options["ssl_keyfile"] == "/test/redis-client.key"


def test_unchanged_metadata_reconciles_after_loss_and_six_hours(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from onyx.utils import fleet_telemetry_collector as source

    clock = [100.0]
    monkeypatch.setattr(source.time, "monotonic", lambda: clock[0])
    monkeypatch.setattr(source, "collector_engine", Mock(return_value=Mock()))
    sender = client()
    collector = FleetCollector(sender, "postgresql://unused", ["public"])
    data = {"license_present": True, "action": "snapshot"}
    at = datetime.now(timezone.utc)
    assert collector._event("license", data, "public", at, "license", durable_id=False)
    assert len(sender._take_batch()) == 1
    clock[0] += 300
    assert collector._event("license", data, "public", at, "license", durable_id=False)
    assert sender._take_batch() == []
    sender.dropped += 1
    assert collector._event("license", data, "public", at, "license", durable_id=False)
    assert len(sender._take_batch()) == 1
    clock[0] += 21600
    assert collector._event("license", data, "public", at, "license", durable_id=False)
    assert len(sender._take_batch()) == 1
    assert collector._event(
        "license",
        {**data, "license_present": False},
        "public",
        at,
        "license",
        durable_id=False,
    )
    assert len(sender._take_batch()) == 1


def test_sender_reuses_http_session_and_compresses_in_background(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def accept(*_args: Any, **kwargs: Any) -> Response:
        assert kwargs["headers"]["Content-Encoding"] == "gzip"
        events = json.loads(gzip.decompress(kwargs["data"]))["events"]
        return Response(
            {
                "results": [
                    {"index": i, "status": "accepted"} for i in range(len(events))
                ]
            }
        )

    session = Mock()
    session.post.side_effect = accept
    factory = Mock(return_value=session)
    monkeypatch.setattr(fleet.requests, "Session", factory)
    sender = client()
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
    sender = client(capacity=1000, report_process=False)
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
    delivered: list[dict[str, Any]] = []

    def accept(*args: Any, **kwargs: Any) -> Response:
        delivered.extend(json.loads(gzip.decompress(kwargs["data"]))["events"])
        return accept_all(*args, **kwargs)

    session = Mock()
    session.post.side_effect = accept
    monkeypatch.setattr(fleet.requests, "Session", Mock(return_value=session))
    sender = client(report_process=False)
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
    assert len(delivered) == 1
    assert delivered[0]["data"]["counters"] == {"fetch_docs": 6}
    assert not sender.emit("heartbeat", {"dropped_events": 0})


def test_final_flush_sends_every_batch_of_stage_counters(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    delivered: list[dict[str, Any]] = []

    def accept(*args: Any, **kwargs: Any) -> Response:
        delivered.extend(json.loads(gzip.decompress(kwargs["data"]))["events"])
        return accept_all(*args, **kwargs)

    session = Mock()
    session.post.side_effect = accept
    monkeypatch.setattr(fleet.requests, "Session", Mock(return_value=session))
    sender = client(capacity=512, report_process=False)
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
    for event in delivered:
        stage = event["data"]["stage"]
        totals[stage] = totals.get(stage, 0) + event["data"]["counters"][stages[stage]]
    assert totals == {"fetch": 125, "embed": 125}
    assert not sender._queue and not sender._pending and not sender._stage_pending


def test_close_waits_for_nothing_during_an_outage() -> None:
    sender = client(report_process=False)
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
    sender = client(report_process=False)
    flushed = Mock(return_value=True)
    monkeypatch.setattr(sender, "flush_once", flushed)
    monkeypatch.setattr(sender._stop, "wait", Mock(side_effect=sender._stop.set))
    sender._run()
    resource.assert_not_called()
    assert not sender._take_batch()


def test_source_configuration_returns_only_structural_metadata() -> None:
    sender = client()
    data = safe_connector_data(
        {
            "connector_id": 1,
            "cc_pair_id": 2,
            "connector_type": "google_drive",
            "state": "active",
            "metadata": {
                "batch_size": 16,
                "folder_names": ["secret"],
                "credential": "secret",
                "include_shared_drives": True,
            },
            "connector_name": "secret",
            "refresh_seconds": 60,
        },
        sender,
    )
    assert sender.emit("connector", data)
    assert "secret" not in json.dumps(data)
    assert data["metadata"] == {
        "batch_size": 16,
        "include_shared_drives": True,
        "refresh_seconds": 60,
    }
    assert client().fingerprint("same") == sender.fingerprint("same")
    other = fleet.BoundedTelemetry(
        fleet.TelemetryConfig(
            "http://localhost",
            "same-token",
            sender.config.customer_uuid,
            "test",
            b"another-installation-private-secret",
        )
    )
    assert other.fingerprint("same") != sender.fingerprint("same")


@pytest.mark.parametrize(
    ("sample", "expected"),
    [
        ("401 expired token abc-secret", "auth"),
        ("403 permission denied for Private folder", "permission"),
        ("HTTP429 too many requests", "rate_limit"),
        ("ReadTimeout with password", "timeout"),
        ("embedding failed on private-document", "embedding"),
        ("BulkIndexError index name private", "index_write"),
        ("parser malformed secret", "parse"),
        ("source connection unavailable", "source_unavailable"),
    ],
)
def test_errors_become_fixed_categories(sample: str, expected: str) -> None:
    assert classify_local_error(sample) == expected


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
    monkeypatch.setattr(query, "emit_telemetry", sink)
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
    event = sink.call_args.args[1]
    assert event["first_answer_ms"] == pytest.approx(200)
    assert event["total_ms"] == pytest.approx(1000)
    assert event["request_count"] == 1
    assert "private" not in json.dumps(event)


def test_query_failure_and_disconnect_do_not_replace_application_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sink = Mock()
    monkeypatch.setattr(query, "emit_telemetry", sink)
    error = TimeoutError("token=private")

    def fail() -> Iterator[Any]:
        yield "setup"
        raise error

    with pytest.raises(TimeoutError) as raised:
        list(query.observe_chat_packets(fail(), channel="discord"))
    assert raised.value is error
    assert sink.call_args.args[1]["error_code"] == "timeout"
    assert "private" not in json.dumps(sink.call_args.args[1])
    stream = query.observe_chat_packets(iter(["setup", "answer"]), channel="web")
    next(stream)
    assert isinstance(stream, Generator)
    stream.close()
    assert sink.call_args.args[1]["outcome"] == "disconnected"


def test_stop_button_and_api_origin_map_to_reported_outcome_and_channel(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from onyx.server.query_and_chat.models import MessageOrigin
    from onyx.server.query_and_chat.placement import Placement
    from onyx.server.query_and_chat.streaming_models import OverallStop, Packet

    sink = Mock()
    monkeypatch.setattr(query, "emit_telemetry", sink)
    stopped = Packet(
        placement=Placement(turn_index=0),
        obj=OverallStop(type="stop", stop_reason="user_cancelled"),
    )
    assert list(query.observe_chat_packets(iter([stopped]), channel="web")) == [stopped]
    assert sink.call_args.args[1]["outcome"] == "canceled"
    for origin, channel in (
        (MessageOrigin.API, "api"),
        (MessageOrigin.SLACKBOT, "slack"),
        (MessageOrigin.DISCORDBOT, "discord"),
        (MessageOrigin.WEBAPP, "web"),
        (MessageOrigin.WIDGET, "web"),
    ):
        request = SimpleNamespace(origin=origin)
        assert query._channel({"new_msg_req": request}) == channel


def test_kubernetes_events_have_opaque_ids_actual_limits_and_no_names() -> None:
    sender = client()
    kubernetes = KubernetesCollector(sender)
    pods = {
        "items": [
            {
                "metadata": {
                    "uid": "private-pod-id",
                    "name": "private-pod",
                    "labels": {"app": "api-server", "customer": "private"},
                },
                "spec": {
                    "containers": [
                        {
                            "name": "private-container",
                            "resources": {"limits": {"memory": "1Gi", "cpu": "500m"}},
                        }
                    ]
                },
                "status": {
                    "containerStatuses": [
                        {
                            "name": "private-container",
                            "restartCount": 2,
                            "ready": False,
                            "state": {
                                "terminated": {
                                    "reason": "OOMKilled",
                                    "exitCode": 137,
                                    "message": "password=private",
                                }
                            },
                        }
                    ]
                },
            }
        ]
    }
    kubernetes.observe_pods(pods)
    kubernetes.observe_metrics(
        {
            "items": [
                {
                    "metadata": {"name": "private-pod"},
                    "containers": [
                        {
                            "name": "private-container",
                            "usage": {"memory": "512Mi", "cpu": "250m"},
                        }
                    ],
                }
            ]
        }
    )
    events = sender._take_batch()
    assert "private" not in json.dumps(events)
    assert events[0]["data"]["reason"] == "oom"
    assert events[0]["service"] == "api"
    assert events[0]["data"]["shared"] is True
    assert events[1]["data"]["memory_limit_bytes"] == 1024**3
    assert events[1]["data"]["cpu_limit_cores"] == 0.5
    assert quantity("max", cpu=True) is None


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


def test_kubernetes_large_environment_never_enters_telemetry() -> None:
    sender = client()
    watcher = KubernetesCollector(sender)
    pod = {
        "metadata": {
            "name": "PRIVATE",
            "uid": "opaque-uid",
            "labels": {"app": "api-server"},
        },
        "spec": {
            "containers": [
                {
                    "name": "PRIVATE",
                    "env": [{"name": "SECRET", "value": "PRIVATE" * 8000}],
                    "resources": {},
                }
            ]
        },
        "status": {
            "containerStatuses": [{"name": "PRIVATE", "restartCount": 0, "ready": True}]
        },
    }
    watcher.observe_pods({"items": [pod]})
    assert len(sender._queue) == 1
    assert "PRIVATE" not in json.dumps(sender._take_batch())


def test_kubernetes_cloud_service_roles_are_fixed_and_other_labels_ignored() -> None:
    sender = client()
    watcher = KubernetesCollector(sender)
    known = {
        "web-server": "web",
        "celery-worker-scheduled-tasks": "worker",
        "pgbouncer": "postgres",
        "mcp-server": "api",
        "telemetry-collector-canary": "collector",
    }
    pods = [
        {
            "metadata": {
                "name": "PRIVATE",
                "uid": str(index),
                "labels": {"app": name, "customer": "PRIVATE"},
            },
            "spec": {"containers": []},
            "status": {
                "containerStatuses": [
                    {"name": "PRIVATE", "restartCount": 0, "ready": True}
                ]
            },
        }
        for index, (name, _) in enumerate(known.items())
    ]
    watcher.observe_pods({"items": pods})
    events = sender._take_batch()
    assert [event["service"] for event in events] == list(known.values())
    assert "PRIVATE" not in json.dumps(events)


def test_kubernetes_initial_ready_history_is_not_a_fresh_failure() -> None:
    sender = client()
    watcher = KubernetesCollector(sender)
    status = {
        "name": "PRIVATE",
        "restartCount": 9,
        "ready": True,
        "state": {"running": {}},
        "lastState": {"terminated": {"reason": "OOMKilled", "exitCode": 137}},
    }
    pod = {
        "metadata": {
            "name": "PRIVATE",
            "uid": "opaque",
            "labels": {"app": "api-server"},
        },
        "spec": {"containers": []},
        "status": {"containerStatuses": [status]},
    }
    watcher.observe_pods({"items": [pod]})
    initial = sender._take_batch()[0]["data"]
    assert (
        initial["reason"] == "started"
        and initial["restart_count"] == 9
        and initial["restart_delta"] == 0
    )
    assert "exit_code" not in initial
    watcher.observe_pods({"items": [pod]})
    assert not sender._queue
    status["restartCount"] = 12
    watcher.observe_pods({"items": [pod]})
    increased = sender._take_batch()[0]["data"]
    assert increased["reason"] == "oom" and increased["restart_delta"] == 3
    assert increased["shared"] is True
    watcher.observe_pods({"items": [pod]})
    assert not sender._queue
    status["ready"] = False
    status["state"] = {"waiting": {"reason": "PRIVATE"}}
    watcher.observe_pods({"items": [pod]})
    assert sender._take_batch()[0]["data"]["reason"] == "unready"
    status["state"] = {"terminated": {"reason": "OOMKilled", "exitCode": 137}}
    watcher.observe_pods({"items": [pod]})
    assert sender._take_batch()[0]["data"]["reason"] == "oom"


def test_kubernetes_version_reports_only_safe_tag_digest_once_and_on_change() -> None:
    sender = client()
    watcher = KubernetesCollector(sender)
    container = {"name": "PRIVATE", "image": "PRIVATE.registry/PRIVATE:v1.2.3"}
    status = {
        "name": "PRIVATE",
        "imageID": "docker-pullable://PRIVATE/PRIVATE@sha256:" + "a" * 64,
        "restartCount": 0,
        "ready": True,
    }
    pod = {
        "metadata": {
            "name": "PRIVATE",
            "uid": "opaque-uid",
            "labels": {"app": "api-server"},
        },
        "spec": {"containers": [container]},
        "status": {"containerStatuses": [status]},
    }
    watcher.observe_pods({"items": [pod]})
    events = sender._take_batch()
    versions = [event for event in events if event["event_type"] == "version"]
    assert versions[0]["data"] == {
        "version": "v1.2.3",
        "image_digest": "sha256:" + "a" * 64,
        "shared": True,
    }
    assert versions[0]["service"] == "api"
    assert "PRIVATE" not in json.dumps(events)
    watcher.observe_pods({"items": [pod]})
    assert not sender._queue
    container["image"] = "PRIVATE.registry/PRIVATE:PRIVATE-customer-tag"
    watcher.observe_pods({"items": [pod]})
    assert sender._take_batch()[0]["data"]["version"] == "unknown"
    container["image"] = "PRIVATE.registry/PRIVATE:v1.2.4"
    watcher.observe_pods({"items": [pod]})
    assert sender._take_batch()[0]["data"]["version"] == "v1.2.4"


def test_kubernetes_ipv6_service_host_forms_a_valid_url(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from urllib.parse import urlsplit

    monkeypatch.setenv("KUBERNETES_SERVICE_HOST", "fd00:10:96::1")
    monkeypatch.setenv("KUBERNETES_SERVICE_PORT_HTTPS", "443")
    monkeypatch.delenv("ONYX_TELEMETRY_KUBERNETES_API_URL", raising=False)
    watcher = KubernetesCollector(client())
    assert watcher.base == "https://[fd00:10:96::1]:443"
    assert urlsplit(watcher.base).port == 443


def test_memory_quantities_are_whole_bytes() -> None:
    assert quantity("1.1Ki") == 1126 and type(quantity("1.1Ki")) is int
    assert quantity("250m", cpu=True) == pytest.approx(0.25)


def test_collector_schema_partition_covers_large_fleet_without_truncation() -> None:
    schemas = [f"tenant_i-{index}" for index in range(7696)]
    seen: list[str] = []
    for shard in range(10):
        collector = object.__new__(FleetCollector)
        collector.shard_count = 10
        collector.shard_index = shard
        seen.extend(collector._partition(schemas))
    assert len(seen) == len(set(seen)) == len(schemas)
    assert set(seen) == set(schemas)


def test_measurement_initialization_failure_preserves_application_results(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        query,
        "QueryObservation",
        Mock(side_effect=RuntimeError("PRIVATE telemetry failure")),
    )
    packets = [object(), object()]
    assert list(query.observe_chat_packets(iter(packets), channel="web")) == packets

    @query.telemetry_query(mode="search")
    def search() -> str:
        return "application result"

    assert search() == "application result"


def test_schema_names_allow_real_cloud_hyphens_and_reject_sql() -> None:
    from onyx.db.fleet_telemetry import _schema

    assert _schema("tenant_i-123-456") == '"tenant_i-123-456"'
    for unsafe in [
        'tenant"; DROP SCHEMA public; --',
        "tenant.public",
        "tenant/private",
    ]:
        with pytest.raises(ValueError):
            _schema(unsafe)


def test_instance_domain_is_startup_hmac_of_canonical_host_only(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DISABLE_TELEMETRY", "false")
    monkeypatch.setenv("ONYX_TELEMETRY_ENDPOINT", "http://localhost:8787")
    monkeypatch.setenv(
        "ONYX_TELEMETRY_CUSTOMER_UUID", "11111111-1111-4111-8111-111111111111"
    )
    monkeypatch.setenv("ONYX_TELEMETRY_DEPLOYMENT_ID", "test")
    monkeypatch.setenv("ONYX_TELEMETRY_TOKEN", "test-token")
    monkeypatch.setenv(
        "ONYX_TELEMETRY_PRIVACY_KEY", "installation-secret-not-central-token"
    )
    monkeypatch.setenv(
        "ONYX_TELEMETRY_INSTANCE_DOMAIN",
        "https://PRIVATE.Example/private-folder?private-token=yes",
    )
    config = fleet.TelemetryConfig.from_env("api")
    assert config is not None
    sender = fleet.BoundedTelemetry(config)
    assert config.instance_domain_hash == sender.fingerprint("private.example")
    sender.emit("heartbeat", {"collector_enabled": True})
    event = sender._take_batch()[0]
    assert event["instance_domain"] == config.instance_domain_hash
    assert "PRIVATE" not in json.dumps(event) and "private-folder" not in json.dumps(
        event
    )
    monkeypatch.setenv(
        "ONYX_TELEMETRY_INSTANCE_DOMAIN", "https://private-password@private.example"
    )
    invalid = fleet.TelemetryConfig.from_env("api")
    assert invalid is not None and invalid.instance_domain_hash is None


def test_collector_failures_are_visible_without_exposing_source_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from onyx.utils import fleet_telemetry_collector as source

    monkeypatch.setattr(source, "email_domain_page", Mock(return_value=[]))
    monkeypatch.setattr(
        source,
        "license_snapshot",
        Mock(return_value={"license_present": False, "first_set_at": None}),
    )
    monkeypatch.setattr(source, "collector_engine", Mock(return_value=Mock()))
    monkeypatch.setattr(source, "MULTI_TENANT", False)
    sender = client()
    collector = FleetCollector(sender, "postgresql://unused", ["public"])
    monkeypatch.setattr(
        collector,
        "collect_one_schema",
        Mock(side_effect=TimeoutError("PRIVATE source URL")),
    )
    monkeypatch.setattr(collector, "collect_queues", Mock())
    collector._last_aws = time.monotonic()
    for _ in range(3):
        if "public" in collector._failed_schema:
            _, failures = collector._failed_schema["public"]
            collector._failed_schema["public"] = (0, failures)
        collector.tick()
    assert sender.health["source_errors"] == 3
    assert sender.health["source_consecutive_errors"] == 3
    assert sender.health["last_source_success_at"] is None
    assert sender.health["schema_count"] == 1
    events = sender._take_batch()
    assert events[-1]["data"]["source_consecutive_errors"] == 3
    assert "PRIVATE" not in json.dumps(events)


def test_job_progress_identity_changes_with_counts_but_terminal_identity_is_stable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from onyx.utils import fleet_telemetry_collector as source

    monkeypatch.setattr(source, "email_domain_page", Mock(return_value=[]))
    monkeypatch.setattr(
        source,
        "license_snapshot",
        Mock(return_value={"license_present": False, "first_set_at": None}),
    )
    monkeypatch.setattr(source, "collector_engine", Mock(return_value=Mock()))
    monkeypatch.setattr(source, "MULTI_TENANT", False)
    monkeypatch.setattr(source, "connector_page", Mock(return_value=[]))
    monkeypatch.setattr(source, "attempt_page", Mock(return_value=[]))
    sender = client()
    collector = FleetCollector(sender, "postgresql://unused", ["public"])
    started = datetime.now(timezone.utc) - timedelta(minutes=10)
    row = {
        "id": "permission:1",
        "entity_id": 1,
        "job_type": "permission_sync",
        "state": "in_progress",
        "docs_processed": 2,
        "users_processed": 0,
        "groups_processed": 0,
        "memberships_synced": 0,
        "started_at": started,
        "ended_at": None,
        "error_count": 0,
        "revision_at": started,
    }
    monkeypatch.setattr(
        source,
        "job_page",
        lambda *_, **kwargs: [] if kwargs.get("active_only") else [dict(row)],
    )

    def poll() -> None:
        collector._last_jobs.clear()
        collector._last_active_jobs.clear()
        collector.collect_one_schema()

    poll()
    poll()
    row["docs_processed"] = 3
    poll()
    active = [event for event in sender._take_batch() if event["event_type"] == "job"]
    assert active[0]["event_id"] == active[1]["event_id"]
    assert active[2]["event_id"] != active[1]["event_id"]
    assert datetime.fromisoformat(active[2]["occurred_at"]) > started
    ended = datetime.now(timezone.utc)
    row.update(state="success", ended_at=ended, revision_at=ended)
    poll()
    poll()
    terminal = [event for event in sender._take_batch() if event["event_type"] == "job"]
    assert terminal[0]["event_id"] == terminal[1]["event_id"]
    assert datetime.fromisoformat(terminal[0]["occurred_at"]) == ended


@pytest.mark.parametrize("uptime", [0.0, 1.0])
def test_repair_cadence_avoids_idle_reads_and_still_polls_old_active_jobs(
    monkeypatch: pytest.MonkeyPatch,
    uptime: float,
) -> None:
    from onyx.utils import fleet_telemetry_collector as source

    monkeypatch.setattr(source, "email_domain_page", Mock(return_value=[]))
    monkeypatch.setattr(
        source,
        "license_snapshot",
        Mock(return_value={"license_present": False, "first_set_at": None}),
    )
    monkeypatch.setattr(source, "collector_engine", Mock(return_value=Mock()))
    monkeypatch.setattr(source, "MULTI_TENANT", False)
    monkeypatch.setattr(
        source, "time", SimpleNamespace(monotonic=lambda: uptime, time=time.time)
    )
    connectors = Mock(return_value=[])
    attempts = Mock(return_value=[])
    monkeypatch.setattr(source, "connector_page", connectors)
    monkeypatch.setattr(source, "attempt_page", attempts)
    sender = client()
    collector = FleetCollector(sender, "postgresql://unused", ["public"])
    old = datetime.now(timezone.utc) - timedelta(days=90)
    row = {
        "id": "group:1",
        "entity_id": 1,
        "job_type": "group_sync",
        "state": "in_progress",
        "docs_processed": 0,
        "users_processed": 2,
        "groups_processed": 1,
        "memberships_synced": 3,
        "started_at": old,
        "ended_at": None,
        "error_count": 0,
        "revision_at": old,
    }
    jobs = Mock(
        side_effect=lambda *_, **kwargs: (
            [dict(row)] if kwargs.get("active_only") else []
        )
    )
    monkeypatch.setattr(source, "job_page", jobs)
    assert collector.collect_one_schema()
    initial = [event for event in sender._take_batch() if event["event_type"] == "job"]
    assert initial[0]["data"]["memberships_synced"] == 3
    assert datetime.fromisoformat(initial[0]["occurred_at"]) > old
    assert not collector.collect_one_schema()
    connectors.assert_called_once()
    attempts.assert_called_once()
    assert jobs.call_count == 2
    collector._last_active_jobs.clear()
    row["memberships_synced"] = 4
    assert collector.collect_one_schema()
    assert sender._take_batch()[0]["event_id"] != initial[0]["event_id"]
    assert jobs.call_count == 3


def test_live_edge_rereads_a_short_overlap_and_sweeps_after_expiry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from onyx.utils import fleet_telemetry_collector as source

    clock = [1000.0]
    monkeypatch.setattr(
        source, "time", SimpleNamespace(monotonic=lambda: clock[0], time=time.time)
    )
    monkeypatch.setattr(source, "email_domain_page", Mock(return_value=[]))
    monkeypatch.setattr(
        source,
        "license_snapshot",
        Mock(return_value={"license_present": False, "first_set_at": None}),
    )
    monkeypatch.setattr(source, "collector_engine", Mock(return_value=Mock()))
    monkeypatch.setattr(source, "MULTI_TENANT", False)
    monkeypatch.setattr(source, "connector_page", Mock(return_value=[]))
    monkeypatch.setattr(source, "job_page", Mock(return_value=[]))
    source_time = datetime.now(timezone.utc) - timedelta(minutes=3)
    row = {
        "attempt_id": 3,
        "connector_id": 1,
        "cc_pair_id": 2,
        "connector_type": "file",
        "state": "success",
        "docs_processed": 1,
        "docs_indexed": 1,
        "chunks_indexed": 1,
        "total_batches": 1,
        "completed_batches": 1,
        "error_count": 0,
        "has_error": False,
        "time_updated": source_time - timedelta(hours=2),
        "source_time": source_time,
    }
    attempts = Mock(return_value=[row])
    monkeypatch.setattr(source, "attempt_page", attempts)
    sender = client(capacity=64)
    collector = FleetCollector(sender, "postgresql://unused", ["public"])

    def poll() -> datetime:
        clock[0] += fleet.CONNECTOR_INTERVAL_SECONDS
        collector.collect_one_schema()
        return collector._attempt_cursor["public"][0]

    overlap = source_time - timedelta(minutes=10)
    assert poll() == overlap
    assert attempts.call_args.args[2] < datetime.now(timezone.utc) - timedelta(days=183)
    attempts.return_value = []
    # Idle reads keep the overlap anchored to the last source read; it never drifts.
    assert poll() == overlap and poll() == overlap
    assert attempts.call_args.args[2] == overlap
    assert len([e for e in sender._take_batch() if e["event_type"] == "attempt"]) == 1
    sender.expired += 1
    swept = poll()
    assert abs(datetime.now(timezone.utc) - timedelta(hours=24) - swept) < timedelta(
        minutes=1
    )
    assert poll() == overlap
    clock[0] += 6 * 3600
    assert poll() < overlap - timedelta(hours=12)


def test_unexpected_compression_fails_closed_with_bounded_retry(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    sender = client()
    watcher = KubernetesCollector(sender)
    watcher.token_path = tmp_path / "token"
    watcher.token_path.write_text("test-token")

    def compressed(*_args: Any, **_kwargs: Any) -> Response:
        response = Response(
            {
                "items": [],
                "results": [{"index": 0, "status": "accepted"}],
                "config_revision": 99,
            }
        )
        response.headers["Content-Encoding"] = "gzip"
        response.raw = io.BytesIO(gzip.compress(response.raw.read()))
        return response

    monkeypatch.setattr("requests.get", compressed)
    assert watcher._get("/api/v1/namespaces/default/pods") is None
    assert watcher.errors == 1 and sender.health["kubernetes_errors"] == 1
    sender.emit("heartbeat", {"collector_enabled": True})
    assert not sender.flush_once(compressed)
    assert sender.failures == 1 and len(sender._pending) == 1
    assert sender.sent == 0


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


@pytest.mark.parametrize("uptime", [0.0, 1.0])
def test_failed_queue_reads_wait_for_configured_poll_interval(
    monkeypatch: pytest.MonkeyPatch,
    uptime: float,
) -> None:
    from onyx.utils import fleet_telemetry_collector as source

    monkeypatch.setattr(source, "email_domain_page", Mock(return_value=[]))
    monkeypatch.setattr(
        source,
        "license_snapshot",
        Mock(return_value={"license_present": False, "first_set_at": None}),
    )
    monkeypatch.setattr(source, "collector_engine", Mock(return_value=Mock()))
    monkeypatch.setattr(source, "MULTI_TENANT", False)
    monkeypatch.setattr(
        source, "time", SimpleNamespace(monotonic=lambda: uptime, time=time.time)
    )
    monkeypatch.setenv("ONYX_TELEMETRY_REDIS_URL", "redis://localhost:1/0")
    unavailable = Mock(side_effect=TimeoutError("PRIVATE unavailable Redis"))
    monkeypatch.setattr("redis.Redis.from_url", unavailable)
    sender = client()
    collector = FleetCollector(sender, "postgresql://unused", ["public"])
    collector._last_aws = uptime
    monkeypatch.setattr(collector, "collect_one_schema", Mock(return_value=False))
    for _ in range(20):
        collector.tick()
    unavailable.assert_called_once()
    assert collector.queue_errors == 1 and sender.health["queue_errors"] == 1
    collector._last_queues = uptime - fleet.QUEUE_INTERVAL_SECONDS - 1
    collector.tick()
    assert unavailable.call_count == 2 and collector.queue_errors == 2


@pytest.mark.parametrize(
    "version", ["v4.9.0-cloud.0-dev", "1.2.3-cloud.42-rc.1-dev", "1.2.3-beta"]
)
def test_version_accepts_only_bounded_approved_suffix_chains(version: str) -> None:
    assert client().emit("version", {"version": version})


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
    assert not client().emit("version", {"version": version})


@pytest.mark.parametrize("uptime", [0.0, 1.0])
def test_initial_discovery_aws_and_health_run_once_then_follow_intervals(
    monkeypatch: pytest.MonkeyPatch, uptime: float
) -> None:
    from onyx.utils import fleet_telemetry_collector as source

    clock = [uptime]
    monkeypatch.setattr(
        source, "time", SimpleNamespace(monotonic=lambda: clock[0], time=time.time)
    )
    monkeypatch.setattr(source, "email_domain_page", Mock(return_value=[]))
    monkeypatch.setattr(
        source,
        "license_snapshot",
        Mock(return_value={"license_present": False, "first_set_at": None}),
    )
    monkeypatch.setattr(source, "collector_engine", Mock(return_value=Mock()))
    discovery = Mock(return_value=["public"])
    monkeypatch.setattr(source, "tenant_schemas", discovery)
    opensearch = Mock()
    monkeypatch.setattr(
        "onyx.utils.fleet_telemetry_opensearch.collect_opensearch_health", opensearch
    )
    managed = Mock(return_value=False)
    monkeypatch.setattr("onyx.utils.fleet_telemetry_aws.collect_aws_resources", managed)
    sender = client()
    collector = FleetCollector(sender, "postgresql://unused", ["public"])
    collector._discover = True
    monkeypatch.setattr(collector, "collect_one_schema", Mock(return_value=False))
    monkeypatch.setattr(collector, "collect_queues", Mock())
    collector.tick()
    # The sender thread reports collector health on its own resource cadence.
    assert not sender._take_batch()
    assert sender.health["aws_consecutive_errors"] == 1
    collector.tick()
    discovery.assert_called_once()
    managed.assert_called_once()
    opensearch.assert_called_once()
    assert not sender._take_batch()
    clock[0] += 60
    collector.tick()
    assert discovery.call_count == 2 and managed.call_count == 1
    assert not sender._take_batch()
    clock[0] += 240
    collector.tick()
    assert managed.call_count == 2 and collector.aws_consecutive_errors == 2
    assert opensearch.call_count == 2


@pytest.mark.parametrize("uptime", [0.0, 1.0])
def test_initial_kubernetes_reads_run_once_and_failed_reads_keep_cadence(
    monkeypatch: pytest.MonkeyPatch, uptime: float
) -> None:
    from onyx.utils import fleet_telemetry_kubernetes as kubernetes

    clock = [uptime]
    monkeypatch.setattr(kubernetes, "time", SimpleNamespace(monotonic=lambda: clock[0]))
    watcher = KubernetesCollector(client())
    failed = Mock(return_value=None)
    monkeypatch.setattr(watcher, "_get", failed)
    watcher.tick()
    assert failed.call_count == 2
    assert failed.call_args_list[0].args[1] == {"limit": 25}
    watcher.tick()
    assert failed.call_count == 2
    clock[0] += 30
    watcher.tick()
    assert failed.call_count == 3
    clock[0] += 270
    watcher.tick()
    assert failed.call_count == 5


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
    monkeypatch.setenv("ONYX_BUILD_SHA", "a" * 40)
    sender = client()
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
    sender = client()
    assert not sender.emit("connector", {"name": "private"})
    first = sender.delivery_health()
    assert first["invalid_events"] == first["recent_dropped_events"] == 1
    assert sender.delivery_health()["recent_dropped_events"] == 1
    now[0] = 61.0
    later = sender.delivery_health()
    assert later["recent_dropped_events"] == 0 and later["dropped_events"] == 1


def test_metadata_repair_revision_and_build_sha_are_bounded() -> None:
    sender = client()
    assert sender.emit(
        "version", {"version": "dev", "commit_sha": "a" * 40}, revision=1
    )
    event = sender._take_batch()[0]
    assert event["revision"] == 1
    assert not sender.emit("version", {"version": "dev", "commit_sha": "private/repo"})
    assert not sender.emit("heartbeat", {}, revision=-1)
    assert not sender.emit("heartbeat", {}, revision=True)


@pytest.mark.parametrize(
    "sample,stage",
    [
        ("embedding failure PRIVATE TOKEN", "embed"),
        ("opensearch rejected PRIVATE URL", "write"),
        ("parser failed PRIVATE PATH", "prepare"),
        ("401 unauthorized PRIVATE TOKEN", None),
    ],
)
def test_safe_attempt_error_data_counts_fatal_errors_and_only_known_stages(
    sample: str, stage: str | None
) -> None:
    data = safe_attempt_error_data(
        {
            "local_error_sample": sample,
            "has_error": True,
            "error_count": 0,
            "connector_type": "file",
        },
        client(),
    )
    assert data["error_count"] == 1
    assert data.get("stage") == stage
    assert "PRIVATE" not in json.dumps(data)


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
    sender = client()
    monkeypatch.setattr(fleet, "_client", sender)
    fleet.emit_signup_domain(email, datetime.now(timezone.utc))
    records = sender._take_batch()
    assert [r["data"]["domain"] for r in records] == ([expected] if expected else [])
    assert "PRIVATE" not in str(records)
    assert "@" not in str(records)


def test_signup_survives_telemetry_queue_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(fleet, "_client", client())
    monkeypatch.setattr(
        fleet, "emit_telemetry", Mock(side_effect=RuntimeError("unavailable"))
    )
    fleet.emit_signup_domain("PRIVATE@onyx.app", datetime.now(timezone.utc))


def test_license_telemetry_excludes_credentials_and_fails_open(monkeypatch) -> None:
    import onyx.utils.fleet_telemetry as telemetry

    sender = client()
    monkeypatch.setattr(telemetry, "_client", sender)
    telemetry.emit_license_state(True, "set", datetime.now(timezone.utc))
    assert sender._take_batch()[0]["data"]["license_present"] is True
    assert (
        telemetry.sanitize_data(
            "license",
            {"license_present": True, "action": "set", "license_key": "PRIVATE"},
        )
        is None
    )
    monkeypatch.setattr(sender, "emit", Mock(side_effect=RuntimeError("unavailable")))
    telemetry.emit_license_state(False, "removed")


def test_delivery_receipts_only_settle_events() -> None:
    sender = client()
    sender.emit("heartbeat", {"collector_enabled": True})
    response = Response(
        {
            "results": [{"index": 0, "status": "accepted"}],
            "enabled": False,
            "connector_interval_seconds": 60,
            "config_revision": 99,
            "config": {"enabled": False},
        }
    )
    assert sender.flush_once(lambda *_args, **_kwargs: response)
    assert sender.sent == 1
    assert fleet.CONNECTOR_INTERVAL_SECONDS == 300
    assert sender.emit("heartbeat", {"collector_enabled": True})


@pytest.mark.parametrize(
    "service", ["api", "collector", "docfetching", "docprocessing", "slack", "discord"]
)
@pytest.mark.parametrize("value", ["true", "TRUE"])
def test_deployment_kill_switch_prevents_sender_startup(
    monkeypatch: pytest.MonkeyPatch, service: str, value: str
) -> None:
    monkeypatch.setenv("DISABLE_TELEMETRY", value)
    monkeypatch.setenv("ONYX_TELEMETRY_ENDPOINT", "https://telemetry.onyx.app")
    monkeypatch.setenv("ONYX_TELEMETRY_TOKEN", "test-token")
    monkeypatch.setenv(
        "ONYX_TELEMETRY_CUSTOMER_UUID", "11111111-1111-4111-8111-111111111111"
    )
    monkeypatch.setenv("ONYX_TELEMETRY_DEPLOYMENT_ID", "test")
    monkeypatch.setenv(
        "ONYX_TELEMETRY_PRIVACY_KEY", "installation-secret-not-central-token"
    )
    monkeypatch.setattr(fleet, "_client", None)
    sender = Mock(
        side_effect=AssertionError("Disabled telemetry must not create a sender")
    )
    monkeypatch.setattr(fleet, "BoundedTelemetry", sender)
    assert fleet.TelemetryConfig.from_env(service) is None
    assert fleet.start_telemetry(service) is None
    assert not fleet.emit_telemetry("heartbeat", {})
    sender.assert_not_called()


@pytest.mark.parametrize("once", [False, True])
def test_disabled_collector_does_not_start_or_open_sources(
    monkeypatch: pytest.MonkeyPatch, once: bool
) -> None:
    from onyx.utils import fleet_telemetry_collector as source

    monkeypatch.setenv("DISABLE_TELEMETRY", "true")
    monkeypatch.setattr("sys.argv", ["collector"] + (["--once"] if once else []))
    blocked = Mock(
        side_effect=AssertionError("Disabled collector must do no collection")
    )
    monkeypatch.setattr(source, "start_telemetry", blocked)
    monkeypatch.setattr(source, "FleetCollector", blocked)
    monkeypatch.setattr(source.signal, "signal", Mock())
    stopped = Mock()
    monkeypatch.setattr(source.threading, "Event", Mock(return_value=stopped))
    source.main()
    blocked.assert_not_called()
    assert stopped.wait.call_count == (0 if once else 1)
