"""The isolated collector reads bounded source pages and reports only safe data."""

import json
import time
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from typing import Any
from unittest.mock import Mock

import pytest

from onyx.configs import app_configs
from onyx.db.fleet_telemetry import _schema
from onyx.utils import fleet_telemetry as fleet
from onyx.utils import fleet_telemetry_collector as source
from onyx.utils.fleet_telemetry_collector import (
    FleetCollector,
    classify_local_error,
    safe_attempt_error_data,
    safe_connector_data,
)
from tests.utils.fleet_telemetry import make_sender


@pytest.fixture
def stub_source(monkeypatch: pytest.MonkeyPatch) -> None:
    """An unused engine and one single-tenant schema with no domains or license."""
    monkeypatch.setattr(source, "email_domain_page", Mock(return_value=[]))
    monkeypatch.setattr(
        source,
        "license_snapshot",
        Mock(return_value={"license_present": False, "first_set_at": None}),
    )
    monkeypatch.setattr(source, "collector_engine", Mock(return_value=Mock()))
    monkeypatch.setattr(source, "MULTI_TENANT", False)


def _auto_enrolled_sender() -> fleet.BoundedTelemetry:
    # With no explicit Redis URL, only an automatic identity reads queues.
    sender: fleet.BoundedTelemetry = make_sender()
    sender.config = replace(sender.config, auto_enroll=True)
    return sender


@pytest.mark.parametrize("explicit_url", [False, True])
def test_queue_collection_inherits_tls_without_overriding_explicit_url(
    monkeypatch: pytest.MonkeyPatch, explicit_url: bool
) -> None:
    monkeypatch.setattr(source, "collector_engine", Mock(return_value=Mock()))
    monkeypatch.setattr(app_configs, "USE_REDIS_IAM_AUTH", False)
    monkeypatch.setattr(app_configs, "REDIS_SSL", True)
    monkeypatch.setattr(app_configs, "REDIS_SSL_CERT_REQS", "required")
    monkeypatch.setattr(app_configs, "REDIS_SSL_CHECK_HOSTNAME", True)
    monkeypatch.setattr(app_configs, "REDIS_SSL_CA_CERTS", "/test/redis-ca.crt")
    monkeypatch.setattr(app_configs, "REDIS_SSL_CERTFILE", "/test/redis-client.crt")
    monkeypatch.setattr(app_configs, "REDIS_SSL_KEYFILE", "/test/redis-client.key")
    monkeypatch.setattr(
        source, "_REDIS_URL", "rediss://custom:6380/15" if explicit_url else None
    )
    sender: fleet.BoundedTelemetry = _auto_enrolled_sender()
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


def test_no_vector_db_deployments_do_not_read_queues(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Lite deployments replace Celery with an in-process runner and have no broker.
    monkeypatch.setattr(source, "collector_engine", Mock(return_value=Mock()))
    monkeypatch.setattr(source, "DISABLE_VECTOR_DB", True)
    monkeypatch.setattr(source, "_REDIS_URL", "redis://localhost:1/0")
    factory: Mock = Mock(side_effect=AssertionError("read a missing broker"))
    monkeypatch.setattr("redis.Redis.from_url", factory)
    sender: fleet.BoundedTelemetry = _auto_enrolled_sender()
    collector: FleetCollector = FleetCollector(sender, "postgresql://test", ["public"])
    collector.collect_queues()
    factory.assert_not_called()
    assert collector.queue_errors == 0
    assert not sender._take_batch()


def test_unchanged_metadata_reconciles_after_loss_and_six_hours(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clock = [100.0]
    monkeypatch.setattr(source.time, "monotonic", lambda: clock[0])
    monkeypatch.setattr(source, "collector_engine", Mock(return_value=Mock()))
    sender = make_sender()
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


def test_source_configuration_returns_only_structural_metadata() -> None:
    sender = make_sender()
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
    assert make_sender().fingerprint("same") == sender.fingerprint("same")
    other = fleet.BoundedTelemetry(
        replace(sender.config, privacy_key=b"another-installation-private-secret")
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


def test_schema_names_allow_real_cloud_hyphens_and_reject_sql() -> None:
    assert _schema("tenant_i-123-456") == '"tenant_i-123-456"'
    for unsafe in [
        'tenant"; DROP SCHEMA public; --',
        "tenant.public",
        "tenant/private",
    ]:
        with pytest.raises(ValueError):
            _schema(unsafe)


@pytest.mark.usefixtures("stub_source")
def test_collector_failures_are_visible_without_exposing_source_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sender = make_sender()
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


@pytest.mark.usefixtures("stub_source")
def test_job_progress_identity_changes_with_counts_but_terminal_identity_is_stable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(source, "connector_page", Mock(return_value=[]))
    monkeypatch.setattr(source, "attempt_page", Mock(return_value=[]))
    sender = make_sender()
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
    monkeypatch.setattr(source, "job_page", lambda *_: [dict(row)])
    monkeypatch.setattr(source, "active_job_page", Mock(return_value=[]))

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


@pytest.mark.usefixtures("stub_source")
@pytest.mark.parametrize("uptime", [0.0, 1.0])
def test_repair_cadence_avoids_idle_reads_and_still_polls_old_active_jobs(
    monkeypatch: pytest.MonkeyPatch,
    uptime: float,
) -> None:
    monkeypatch.setattr(
        source, "time", SimpleNamespace(monotonic=lambda: uptime, time=time.time)
    )
    connectors = Mock(return_value=[])
    attempts = Mock(return_value=[])
    monkeypatch.setattr(source, "connector_page", connectors)
    monkeypatch.setattr(source, "attempt_page", attempts)
    sender = make_sender()
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
    history = Mock(return_value=[])
    active = Mock(side_effect=lambda *_: [dict(row)])
    monkeypatch.setattr(source, "job_page", history)
    monkeypatch.setattr(source, "active_job_page", active)
    assert collector.collect_one_schema()
    initial = [event for event in sender._take_batch() if event["event_type"] == "job"]
    assert initial[0]["data"]["memberships_synced"] == 3
    assert datetime.fromisoformat(initial[0]["occurred_at"]) > old
    assert not collector.collect_one_schema()
    connectors.assert_called_once()
    attempts.assert_called_once()
    history.assert_called_once()
    active.assert_called_once()
    collector._last_active_jobs.clear()
    row["memberships_synced"] = 4
    assert collector.collect_one_schema()
    assert sender._take_batch()[0]["event_id"] != initial[0]["event_id"]
    history.assert_called_once()
    assert active.call_count == 2


@pytest.mark.usefixtures("stub_source")
def test_live_edge_rereads_a_short_overlap_and_sweeps_after_expiry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clock = [1000.0]
    monkeypatch.setattr(
        source, "time", SimpleNamespace(monotonic=lambda: clock[0], time=time.time)
    )
    monkeypatch.setattr(source, "connector_page", Mock(return_value=[]))
    monkeypatch.setattr(source, "job_page", Mock(return_value=[]))
    monkeypatch.setattr(source, "active_job_page", Mock(return_value=[]))
    source_time = datetime.now(timezone.utc) - timedelta(minutes=3)
    row = {
        "attempt_id": 3,
        "connector_id": 1,
        "cc_pair_id": 2,
        "connector_type": "file",
        "state": "success",
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
    sender = make_sender(capacity=64)
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


@pytest.mark.usefixtures("stub_source")
@pytest.mark.parametrize("uptime", [0.0, 1.0])
def test_failed_queue_reads_wait_for_configured_poll_interval(
    monkeypatch: pytest.MonkeyPatch,
    uptime: float,
) -> None:
    monkeypatch.setattr(
        source, "time", SimpleNamespace(monotonic=lambda: uptime, time=time.time)
    )
    monkeypatch.setattr(source, "_REDIS_URL", "redis://localhost:1/0")
    unavailable = Mock(side_effect=TimeoutError("PRIVATE unavailable Redis"))
    monkeypatch.setattr("redis.Redis.from_url", unavailable)
    sender = make_sender()
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


@pytest.mark.usefixtures("stub_source")
@pytest.mark.parametrize("uptime", [0.0, 1.0])
def test_initial_discovery_aws_and_health_run_once_then_follow_intervals(
    monkeypatch: pytest.MonkeyPatch, uptime: float
) -> None:
    clock = [uptime]
    monkeypatch.setattr(
        source, "time", SimpleNamespace(monotonic=lambda: clock[0], time=time.time)
    )
    discovery = Mock(return_value=["public"])
    monkeypatch.setattr(source, "tenant_schemas", discovery)
    opensearch = Mock()
    monkeypatch.setattr(
        "onyx.utils.fleet_telemetry_opensearch.collect_opensearch_health", opensearch
    )
    managed = Mock(return_value=False)
    monkeypatch.setattr("onyx.utils.fleet_telemetry_aws.collect_aws_resources", managed)
    sender = make_sender()
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
        make_sender(),
    )
    assert data["error_count"] == 1
    assert data.get("stage") == stage
    assert "PRIVATE" not in json.dumps(data)


@pytest.mark.parametrize("once", [False, True])
def test_disabled_collector_does_not_start_or_open_sources(
    monkeypatch: pytest.MonkeyPatch, once: bool
) -> None:
    monkeypatch.setattr(source, "DISABLE_TELEMETRY", True)
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
