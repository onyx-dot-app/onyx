"""Unit tests for the DB-snapshot connector state metrics collector."""

from contextlib import nullcontext
from datetime import datetime
from datetime import timedelta
from datetime import timezone
from threading import Event
from threading import Thread
from unittest.mock import MagicMock

import pytest
from prometheus_client import CollectorRegistry

import onyx.server.metrics.connector_state_metrics as csm
from onyx.configs.constants import DocumentSource
from onyx.db.connector_credential_pair import ConnectorStateSnapshot
from onyx.db.enums import AccessType
from onyx.db.enums import ConnectorCredentialPairStatus
from onyx.db.enums import IndexingMode
from onyx.server.metrics.connector_state_metrics import _enum_label
from onyx.server.metrics.connector_state_metrics import _to_unix_ts
from onyx.server.metrics.connector_state_metrics import ConnectorStateMetricsCollector


def _snapshot() -> ConnectorStateSnapshot:
    return ConnectorStateSnapshot(
        cc_pair_id=42,
        cc_pair_name="Engineering Drive",
        status=ConnectorCredentialPairStatus.ACTIVE,
        last_successful_index_time=datetime(
            2026,
            7,
            11,
            14,
            tzinfo=timezone(timedelta(hours=2)),
        ),
        last_pruned=None,
        last_time_perm_sync=datetime(2026, 7, 11, 12, tzinfo=timezone.utc),
        last_time_external_group_sync=None,
        total_docs_indexed=17,
        access_type=AccessType.SYNC,
        indexing_trigger=IndexingMode.UPDATE,
        auto_sync_enabled=True,
        in_repeated_error_state=True,
        source=DocumentSource.GOOGLE_DRIVE,
        credential_id=7,
    )


def _sample_value(
    family: csm.Metric,
    labels: dict[str, str],
) -> float:
    return next(sample.value for sample in family.samples if sample.labels == labels)


def test_to_unix_ts() -> None:
    assert _to_unix_ts(None) == 0
    aware = datetime(2026, 7, 11, 12, 0, 0, tzinfo=timezone.utc)
    assert _to_unix_ts(aware) == int(aware.timestamp())
    naive = datetime(2026, 7, 11, 12, 0, 0)
    assert _to_unix_ts(naive) == int(aware.timestamp())  # naive treated as UTC


def test_enum_label_guards_label_cardinality() -> None:
    class _FakeEnum:
        value = "ACTIVE"

    assert _enum_label(_FakeEnum(), ("ACTIVE", "PAUSED")) == "ACTIVE"
    # Unexpected values collapse to UNKNOWN instead of minting new label values.
    assert _enum_label("SOMETHING_NEW", ("ACTIVE", "PAUSED")) == "UNKNOWN"


def test_collect_reports_failure_when_db_unavailable() -> None:
    collector = ConnectorStateMetricsCollector()
    try:
        families = list(collector.collect())
    finally:
        collector._executor.shutdown(wait=True)

    assert [family.name for family in families] == [
        "onyx_connector_state_collection_success"
    ]
    assert families[0].samples[0].value == 0.0


def test_collect_maps_snapshot_to_metrics(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        csm,
        "get_session_with_current_tenant",
        lambda: nullcontext(MagicMock()),
    )
    monkeypatch.setattr(
        csm,
        "get_connector_state_snapshots",
        lambda _db: [_snapshot()],
    )

    collector = ConnectorStateMetricsCollector()
    try:
        families = {family.name: family for family in collector.collect()}
    finally:
        collector._executor.shutdown(wait=True)
    connector_labels = {"source": "google_drive", "cc_pair_id": "42"}

    assert _sample_value(families["onyx_connector_state_collection_success"], {}) == 1.0
    assert (
        _sample_value(
            families["onyx_connector_last_successful_index_timestamp_seconds"],
            connector_labels,
        )
        == datetime(2026, 7, 11, 12, tzinfo=timezone.utc).timestamp()
    )
    assert (
        _sample_value(
            families["onyx_connector_last_pruned_timestamp_seconds"],
            connector_labels,
        )
        == 0.0
    )
    assert (
        _sample_value(
            families["onyx_connector_repeated_error_state"],
            connector_labels,
        )
        == 1.0
    )
    assert (
        _sample_value(
            families["onyx_connector_status"],
            {**connector_labels, "status": "ACTIVE"},
        )
        == 1.0
    )
    assert (
        _sample_value(
            families["onyx_connector_status"],
            {**connector_labels, "status": "UNKNOWN"},
        )
        == 0.0
    )
    assert (
        _sample_value(
            families["onyx_connector_count"],
            {"source": "google_drive", "status": "ACTIVE"},
        )
        == 1.0
    )
    assert (
        _sample_value(
            families["onyx_connector_document_count"],
            {"source": "google_drive"},
        )
        == 17.0
    )

    info_labels = families["onyx_connector"].samples[0].labels
    assert info_labels == {
        "cc_pair_id": "42",
        "connector_name": "Engineering Drive",
        "source": "google_drive",
        "credential_id": "7",
        "status": "ACTIVE",
        "access_type": "sync",
    }


def test_collect_does_not_start_overlapping_reads(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    started = Event()
    release = Event()
    calls = 0
    collector = ConnectorStateMetricsCollector(timeout=2.0)

    def _slow_collect() -> list[csm.Metric]:
        nonlocal calls
        calls += 1
        started.set()
        release.wait()
        return []

    first_result: list[csm.Metric] = []
    monkeypatch.setattr(collector, "_collect_fresh", _slow_collect)
    first_scrape = Thread(target=lambda: first_result.extend(collector.collect()))
    first_scrape.start()
    try:
        assert started.wait(timeout=1.0)
        second = list(collector.collect())
        assert first_scrape.is_alive()
    finally:
        release.set()
        first_scrape.join()
        collector._executor.shutdown(wait=True)

    assert calls == 1
    assert first_result[0].samples[0].value == 1.0
    assert second[0].samples[0].value == 0.0


def test_describe_does_not_query_database(monkeypatch: pytest.MonkeyPatch) -> None:
    collector = ConnectorStateMetricsCollector()
    collect_fresh = MagicMock(
        side_effect=AssertionError("describe queried the database")
    )
    monkeypatch.setattr(
        collector,
        "_collect_fresh",
        collect_fresh,
    )
    try:
        families = list(collector.describe())
    finally:
        collector._executor.shutdown(wait=True)

    assert len(families) == 13
    assert families[0].name == "onyx_connector_state_collection_success"
    collect_fresh.assert_not_called()


def test_register_skipped_in_multi_tenant(monkeypatch: pytest.MonkeyPatch) -> None:
    registered: list[object] = []
    monkeypatch.setattr(csm, "MULTI_TENANT", True)
    monkeypatch.setattr(csm.REGISTRY, "register", registered.append)

    csm.register_connector_state_metrics()

    assert registered == []


def test_register_in_single_tenant(monkeypatch: pytest.MonkeyPatch) -> None:
    registered: list[object] = []
    monkeypatch.setattr(csm, "MULTI_TENANT", False)
    monkeypatch.setattr(csm, "_CONNECTOR_STATE_COLLECTOR_REGISTERED", False)
    monkeypatch.setattr(csm.REGISTRY, "register", registered.append)

    csm.register_connector_state_metrics()
    csm.register_connector_state_metrics()

    assert len(registered) == 1
    assert isinstance(registered[0], ConnectorStateMetricsCollector)


def test_registration_does_not_collect(monkeypatch: pytest.MonkeyPatch) -> None:
    collect_fresh = MagicMock(side_effect=AssertionError("registration queried the DB"))
    monkeypatch.setattr(csm, "MULTI_TENANT", False)
    monkeypatch.setattr(csm, "_CONNECTOR_STATE_COLLECTOR_REGISTERED", False)
    monkeypatch.setattr(csm, "REGISTRY", CollectorRegistry(auto_describe=True))
    monkeypatch.setattr(
        csm._CONNECTOR_STATE_COLLECTOR,
        "_collect_fresh",
        collect_fresh,
    )

    csm.register_connector_state_metrics()

    collect_fresh.assert_not_called()
