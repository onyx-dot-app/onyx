"""Unit tests for the DB-snapshot connector state metrics collector."""

from datetime import datetime
from datetime import timezone

import pytest

import onyx.server.metrics.connector_state_metrics as csm
from onyx.server.metrics.connector_state_metrics import _enum_str
from onyx.server.metrics.connector_state_metrics import _to_unix_ts
from onyx.server.metrics.connector_state_metrics import ConnectorStateMetricsCollector


def test_to_unix_ts() -> None:
    assert _to_unix_ts(None) == 0
    aware = datetime(2026, 7, 11, 12, 0, 0, tzinfo=timezone.utc)
    assert _to_unix_ts(aware) == int(aware.timestamp())
    naive = datetime(2026, 7, 11, 12, 0, 0)
    assert _to_unix_ts(naive) == int(aware.timestamp())  # naive treated as UTC


def test_enum_str_guards_label_cardinality() -> None:
    class _FakeEnum:
        value = "ACTIVE"

    assert _enum_str(_FakeEnum(), ("ACTIVE", "PAUSED")) == "ACTIVE"
    # Unexpected values collapse to UNKNOWN instead of minting new label values.
    assert _enum_str("SOMETHING_NEW", ("ACTIVE", "PAUSED")) == "UNKNOWN"


def test_collect_yields_all_families_when_db_unavailable() -> None:
    """A scrape must never crash the /metrics endpoint: with no DB engine the
    collector logs and still yields every (empty) metric family."""
    families = list(ConnectorStateMetricsCollector().collect())
    names = {f.name for f in families}
    assert len(families) == 12
    assert "onyx_connector_seconds_since_last_success" in names
    assert "onyx_connectors_total" in names
    assert all(not f.samples for f in families)


def test_register_skipped_in_multi_tenant(monkeypatch: pytest.MonkeyPatch) -> None:
    registered: list[object] = []
    monkeypatch.setattr(csm, "MULTI_TENANT", True)
    monkeypatch.setattr(csm.REGISTRY, "register", registered.append)

    csm.register_connector_state_metrics()

    assert registered == []


def test_register_in_single_tenant(monkeypatch: pytest.MonkeyPatch) -> None:
    registered: list[object] = []
    monkeypatch.setattr(csm, "MULTI_TENANT", False)
    monkeypatch.setattr(csm.REGISTRY, "register", registered.append)

    csm.register_connector_state_metrics()

    assert len(registered) == 1
    assert isinstance(registered[0], ConnectorStateMetricsCollector)
