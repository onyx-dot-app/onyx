"""Bounded health reads export only structural fields, including failure state."""

import json
from datetime import datetime, timedelta, timezone
from unittest.mock import Mock

import pytest

from onyx.document_index.opensearch import resource_health
from onyx.utils import fleet_telemetry_opensearch as health
from tests.utils.fleet_telemetry import make_sender


@pytest.mark.parametrize("stale", [False, True])
def test_opensearch_allowlist_and_stale_pressure(
    monkeypatch: pytest.MonkeyPatch, stale: bool
) -> None:
    search = Mock()
    search.cluster_health.return_value = {
        "status": "yellow",
        "number_of_nodes": 3,
        "unassigned_shards": 2,
        "cluster_name": "PRIVATE",
        "nodes": {"PRIVATE": {}},
        "timed_out": False,
    }
    factory = Mock()
    factory.return_value.__enter__ = Mock(return_value=search)
    factory.return_value.__exit__ = Mock(return_value=None)
    monkeypatch.setattr(health, "OpenSearchClient", factory)
    cache = Mock()
    cache.get.return_value = json.dumps(
        {
            "checked_at": (
                datetime.now(timezone.utc) - timedelta(hours=1 if stale else 0)
            ).isoformat(),
            "issues": ["disk"],
            "heap_high_nodes": ["PRIVATE"],
            "vector_high_nodes": ["PRIVATE"],
        }
    )
    redis = Mock(return_value=cache)
    monkeypatch.setattr(resource_health, "get_shared_redis_client", redis)
    monkeypatch.setattr(health, "DISABLE_VECTOR_DB", False)
    monkeypatch.setattr(resource_health, "DISABLE_VECTOR_DB", False)
    client = make_sender()
    health.collect_opensearch_health(client)
    event = client._take_batch()[0]
    assert event["data"]["opensearch_status"] == "yellow"
    assert event["data"]["opensearch_disk_pressure"] is True
    assert event["data"]["opensearch_resource_stale"] is stale
    assert "PRIVATE" not in json.dumps(event)
    factory.assert_called_once_with(timeout=2, max_retries=0)
    assert redis.call_args.kwargs["operation_timeout_s"] == 0.2


def test_opensearch_outage_is_unknown_and_disabled_is_no_io(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    search = Mock(side_effect=RuntimeError("PRIVATE"))
    monkeypatch.setattr(health, "OpenSearchClient", search)
    monkeypatch.setattr(
        resource_health,
        "get_shared_redis_client",
        Mock(side_effect=RuntimeError("PRIVATE")),
    )
    monkeypatch.setattr(health, "DISABLE_VECTOR_DB", False)
    monkeypatch.setattr(resource_health, "DISABLE_VECTOR_DB", False)
    client = make_sender()
    health.collect_opensearch_health(client)
    data = client._take_batch()[0]["data"]
    assert data["opensearch_status"] == "unavailable"
    assert data["opensearch_resource_stale"] is True
    assert "PRIVATE" not in json.dumps(data)
    monkeypatch.setattr(health, "DISABLE_VECTOR_DB", True)
    health.collect_opensearch_health(client)
    search.assert_called_once()
    assert not client._take_batch()
