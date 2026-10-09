"""Collector rows become safe events with stable IDs. A failed read never escapes."""

import json
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from typing import Any
from unittest.mock import Mock

import pytest

from onyx.configs.constants import DocumentSource
from onyx.db.enums import ConnectorCredentialPairStatus, IndexingStatus
from onyx.db.index_attempt_metrics_models import IndexAttemptStage
from onyx.utils import fleet_telemetry as fleet
from onyx.utils import fleet_telemetry_collector as collector
from tests.unit.fakes import FakeCache
from tests.utils.fleet_telemetry import make_sender

_NOW: datetime = datetime(2026, 1, 1, 12, tzinfo=timezone.utc)


def _connector_row(**overrides: Any) -> dict[str, Any]:
    row: dict[str, Any] = {
        "cc_pair_id": 3,
        "connector_id": 2,
        "source": DocumentSource.GOOGLE_DRIVE,
        "status": ConnectorCredentialPairStatus.ACTIVE,
        "doc_count": 40,
        "last_success_at": _NOW,
        "refresh_seconds": 1800,
        "prune_seconds": None,
        "auto_sync_enabled": False,
        "permission_sync_enabled": True,
        "config": {
            "include_shared_drives": True,
            "batch_size": 16,
            "folder_paths": ["Private/Finance", "Private/Legal"],
            "shared_folder_urls": "https://drive.example/private",
            "start_date": "2024-01-01",
        },
    }
    row.update(overrides)
    return row


def _attempt_row(**overrides: Any) -> dict[str, Any]:
    row: dict[str, Any] = {
        "attempt_id": 9,
        "cc_pair_id": 3,
        "connector_id": 2,
        "source": DocumentSource.GOOGLE_DRIVE,
        "status": IndexingStatus.IN_PROGRESS,
        "docs_indexed": 12,
        "chunks_indexed": 30,
        "total_batches": 4,
        "completed_batches": 2,
        "started_at": _NOW - timedelta(minutes=3),
        "time_updated": _NOW - timedelta(minutes=1),
        "last_progress_at": _NOW - timedelta(minutes=1),
        "last_heartbeat_at": _NOW,
        "error_sample": None,
        "item_error_type": None,
        "item_error_sample": None,
        "error_count": 0,
    }
    row.update(overrides)
    return row


def _stage_row(**overrides: Any) -> dict[str, Any]:
    row: dict[str, Any] = {
        "attempt_id": 9,
        "stage": IndexAttemptStage.EMBEDDING,
        "event_count": 2,
        "total_duration_ms": 300,
        "min_duration_ms": 100,
        "max_duration_ms": 200,
        "m2_duration_ms": 5000.0,
        "first_event_at": _NOW - timedelta(minutes=2),
        "last_event_at": _NOW - timedelta(minutes=1),
    }
    row.update(overrides)
    return row


def _job_row(**overrides: Any) -> dict[str, Any]:
    row: dict[str, Any] = {
        "job_id": "permission:5",
        "job_type": "permission_sync",
        "state": "in_progress",
        "entity_id": 3,
        "cc_pair_id": 3,
        "started_at": _NOW - timedelta(minutes=4),
        "ended_at": None,
        "revision_at": _NOW - timedelta(minutes=4),
        "docs_processed": 7,
        "users_processed": 0,
        "groups_processed": 0,
        "memberships_synced": 0,
        "error_count": 0,
    }
    row.update(overrides)
    return row


class _Source:
    """The database reads that `collect_snapshots` makes, served from lists."""

    def __init__(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self.connectors: list[dict[str, Any]] = [_connector_row()]
        self.domains: list[dict[str, Any]] = [
            {"domain": "Example.COM", "first_signup_at": _NOW - timedelta(days=9)},
            {"domain": "localhost", "first_signup_at": _NOW},
        ]
        self.license: dict[str, Any] = {"license_present": False, "first_set_at": None}
        self.attempts: list[dict[str, Any]] = [_attempt_row()]
        self.stages: list[dict[str, Any]] = [_stage_row()]
        self.jobs: list[dict[str, Any]] = [_job_row()]
        self.since: list[datetime] = []
        self.cache: FakeCache = FakeCache()

        @contextmanager
        def session(tenant_id: str) -> Iterator[Mock]:
            assert tenant_id == "public"
            yield Mock()

        def attempts(_session: Any, since: datetime) -> list[dict[str, Any]]:
            self.since.append(since)
            return self.attempts

        monkeypatch.setattr(collector, "get_session_with_tenant", session)
        monkeypatch.setattr(collector, "limit_statement_time", Mock())
        monkeypatch.setattr(
            collector, "connector_rows", lambda _session: self.connectors
        )
        monkeypatch.setattr(
            collector, "email_domain_rows", lambda _session: self.domains
        )
        monkeypatch.setattr(collector, "license_row", lambda _session: self.license)
        monkeypatch.setattr(collector, "attempt_rows", attempts)
        monkeypatch.setattr(
            collector, "stage_rows", lambda _session, _ids, _since: self.stages
        )
        monkeypatch.setattr(collector, "job_rows", lambda _session, _since: self.jobs)
        monkeypatch.setattr(
            collector, "get_cache_backend", Mock(return_value=self.cache)
        )


@pytest.fixture
def source(monkeypatch: pytest.MonkeyPatch) -> _Source:
    return _Source(monkeypatch)


@pytest.fixture
def sender(monkeypatch: pytest.MonkeyPatch) -> fleet.BoundedTelemetry:
    enrolled: fleet.BoundedTelemetry = make_sender(capacity=256)
    monkeypatch.setattr(collector, "get_sender", lambda: enrolled)
    return enrolled


def _event_ids(sender: fleet.BoundedTelemetry) -> dict[str, str]:
    return {event["event_type"]: event["event_id"] for event in sender._take_batch()}


def test_connector_data_keeps_reviewed_settings_and_counts_only() -> None:
    data: dict[str, Any] = collector.connector_data(_connector_row())
    assert data["connector_type"] == "google_drive" and data["state"] == "active"
    assert data["metadata"] == {
        "include_shared_drives": True,
        "batch_size": 16,
        "selection_count": 2,
        "has_time_filter": True,
        "refresh_seconds": 1800,
        "auto_sync_enabled": False,
        "permission_sync_enabled": True,
    }
    assert "Private" not in json.dumps(data) and "drive.example" not in json.dumps(data)
    assert fleet.sanitize_data("connector", data) == data
    # The hash follows the reported settings.
    changed: dict[str, Any] = collector.connector_data(
        _connector_row(refresh_seconds=3600)
    )
    assert changed["config_hash"] != data["config_hash"]


def test_attempt_data_reports_an_error_category_but_no_error_text() -> None:
    running: dict[str, Any] = collector.attempt_data(_attempt_row())
    assert running["state"] == "in_progress" and "ended_at" not in running
    assert "error_code" not in running
    failed: dict[str, Any] = collector.attempt_data(
        _attempt_row(
            status=IndexingStatus.FAILED,
            error_sample="Embedding request for PRIVATE-DOC failed",
        )
    )
    assert failed["ended_at"] == (_NOW - timedelta(minutes=1)).isoformat()
    assert failed["error_code"] == "embedding" and failed["stage"] == "embed"
    assert failed["error_count"] == 1
    assert "PRIVATE" not in json.dumps(failed)
    for data in (running, failed):
        assert fleet.sanitize_data("attempt", data) == data


def test_job_data_reports_duration_and_failure() -> None:
    finished: dict[str, Any] = collector.job_data(
        _job_row(state="failed", ended_at=_NOW, revision_at=_NOW)
    )
    assert finished["duration_ms"] == 240_000
    assert finished["error_count"] == 1
    assert "revision_at" not in finished
    assert fleet.sanitize_data("job", finished) == finished
    unlinked: dict[str, Any] = collector.job_data(
        _job_row(job_id="sync:1", job_type="pruning", cc_pair_id=None)
    )
    assert "cc_pair_id" not in unlinked


@pytest.mark.parametrize(
    "samples, category",
    [
        (("HTTP 401 Unauthorized for PRIVATE",), "auth"),
        (("403 Forbidden",), "permission"),
        (("Too many requests",), "rate_limit"),
        (("ReadTimeout while fetching",), "timeout"),
        (("BulkIndexError: 2 document(s) failed",), "index_write"),
        (("Could not parse the file",), "parse"),
        (("Connection refused",), "source_unavailable"),
        (("Something else",), "internal"),
        ((None, 42), "internal"),
    ],
)
def test_local_error_text_maps_to_a_fixed_category(
    samples: tuple[object, ...], category: str
) -> None:
    assert collector.classify_local_error(*samples) == category


@pytest.mark.parametrize(
    "domain, expected",
    [
        ("Onyx.App", "onyx.app"),
        ("bücher.example", "xn--bcher-kva.example"),
        ("http://onyx.app", None),
        ("127.0.0.1", None),
        ("localhost", None),
        ("onyx.app@other.app", None),
    ],
)
def test_signup_domains_are_normalized_or_dropped(
    domain: str, expected: str | None
) -> None:
    assert collector.normalize_email_domain(domain) == expected


def test_collection_waits_for_enrollment(
    monkeypatch: pytest.MonkeyPatch, source: _Source
) -> None:
    monkeypatch.setattr(collector, "get_sender", lambda: None)
    collector.collect_snapshots("public")
    monkeypatch.setattr(
        collector, "get_sender", lambda: fleet.BoundedTelemetry("worker")
    )
    collector.collect_snapshots("public")
    assert source.since == [] and source.cache.store == {}


def test_first_run_sends_inventory_work_and_cursor(
    source: _Source, sender: fleet.BoundedTelemetry
) -> None:
    collector.collect_snapshots("public")
    events: list[dict[str, Any]] = sender._take_batch()
    assert [event["event_type"] for event in events] == [
        "connector",
        "tenant_domain",
        "license",
        "attempt",
        "stage",
        "job",
    ]
    assert events[1]["data"]["domain"] == "example.com"
    stage: dict[str, Any] = events[4]
    # The service requires a stage event at the time of its last update.
    assert stage["occurred_at"] == (_NOW - timedelta(minutes=1)).isoformat()
    assert stage["data"]["stage_name"] == "EMBEDDING"
    assert stage["data"]["connector_type"] == "google_drive"
    cursor: bytes | None = source.cache.get(collector._LAST_RUN_KEY)
    assert cursor is not None
    started: datetime = datetime.fromisoformat(cursor.decode())
    assert started - source.since[0] == collector._FIRST_WINDOW
    assert sender.health["source_consecutive_errors"] == 0
    assert sender.health["last_source_success_at"] == started.isoformat()


def test_repeated_runs_repeat_event_ids_and_skip_unchanged_inventory(
    source: _Source, sender: fleet.BoundedTelemetry
) -> None:
    collector.collect_snapshots("public")
    first: dict[str, str] = _event_ids(sender)
    collector.collect_snapshots("public")
    # Unchanged rows repeat their event IDs, so the service drops the copies.
    assert _event_ids(sender) == {
        key: first[key] for key in ("attempt", "stage", "job")
    }
    # The overlap reads the end of the previous window again.
    assert source.since[1] < source.since[0] + collector._FIRST_WINDOW
    source.jobs = [_job_row(docs_processed=8)]
    source.connectors = [_connector_row(doc_count=41)]
    collector.collect_snapshots("public")
    third: dict[str, str] = _event_ids(sender)
    # A running job's progress and a changed inventory go out again.
    assert third["job"] != first["job"] and third["attempt"] == first["attempt"]
    assert {"connector", "tenant_domain", "license"} <= third.keys()


def test_a_failed_read_counts_a_source_error_and_keeps_the_cursor(
    monkeypatch: pytest.MonkeyPatch, source: _Source, sender: fleet.BoundedTelemetry
) -> None:
    monkeypatch.setattr(
        collector, "job_rows", Mock(side_effect=RuntimeError("PRIVATE SQL"))
    )
    for _ in range(2):
        collector.collect_snapshots("public")
    assert sender.health["source_errors"] == 2
    assert sender.health["source_consecutive_errors"] == 2
    assert collector._LAST_RUN_KEY not in source.cache.store
    assert not sender._take_batch()
