import importlib
from collections.abc import Generator
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock
from uuid import UUID, uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from onyx.auth.users import current_user
from onyx.background.celery.tasks import beat_schedule
from onyx.configs import app_configs
from onyx.configs.constants import OnyxCeleryQueues, OnyxCeleryTask
from onyx.db.enums import Permission
from onyx.db.models import User
from onyx.document_index.opensearch import resource_health as health
from onyx.document_index.opensearch.models import (
    NodesResourceStats,
    ResourceIssue,
    VectorResourceStats,
)
from onyx.error_handling.exceptions import register_onyx_exception_handlers
from onyx.redis.redis_pool import get_redis_client
from onyx.redis.tenant_redis_client import TenantRedisClient
from onyx.server.manage.opensearch_health import api
from shared_configs import configs

NOW = datetime.now(timezone.utc)
ADMIN_IDS = (UUID(int=1), UUID(int=2))
URL = "/manage/admin/opensearch-health"


def node_stats(
    heap: float = 20, free: int = 80, node_id: str = "node-1"
) -> NodesResourceStats:
    return NodesResourceStats.model_validate(
        {
            "_nodes": {"failed": 0},
            "nodes": {
                node_id: {
                    "jvm": {"mem": {"heap_used_percent": heap}},
                    "fs": {
                        "data": [
                            {"total_in_bytes": 100, "available_in_bytes": free},
                            {"total_in_bytes": 10000, "available_in_bytes": 9000},
                        ]
                    },
                }
            },
        }
    )


def vector_stats(usage: float = 20, tripped: bool = False) -> VectorResourceStats:
    return VectorResourceStats.model_validate(
        {
            "_nodes": {"failed": 0},
            "circuit_breaker_triggered": tripped,
            "nodes": {"node-1": {"graph_memory_usage_percentage": usage}},
        }
    )


@pytest.fixture
def redis(monkeypatch: pytest.MonkeyPatch) -> Generator[TenantRedisClient, None, None]:
    client = get_redis_client(tenant_id=f"test_resource_health_{uuid4().hex}")
    monkeypatch.setattr(health, "get_shared_redis_client", lambda **_: client)
    monkeypatch.setattr(api, "get_redis_client", lambda: client)
    monkeypatch.setattr(health, "DISABLE_VECTOR_DB", False)
    yield client
    client.delete(
        health.RESOURCE_SNAPSHOT_KEY,
        health.RESOURCE_CHECK_LEASE_KEY,
        *(f"{api.POPUP_KEY_PREFIX}:{user_id}" for user_id in ADMIN_IDS),
    )


@pytest.mark.parametrize(
    "free,expected", [(16, []), (15, [ResourceIssue.DISK]), (0, [ResourceIssue.DISK])]
)
def test_resource_disk_checks_each_data_path(
    free: int, expected: list[ResourceIssue]
) -> None:
    result = health.evaluate_resource_health(
        node_stats(free=free), vector_stats(), None, NOW
    )
    assert result.issues == expected


def test_resource_memory_requires_repeated_readings_and_recovers() -> None:
    nodes, vectors = node_stats(heap=85), vector_stats(usage=90)
    first = health.evaluate_resource_health(nodes, vectors, None, NOW)
    assert not first.issues
    second = health.evaluate_resource_health(
        nodes, vectors, first, NOW + timedelta(minutes=5)
    )
    assert second.issues == [ResourceIssue.JVM_MEMORY, ResourceIssue.VECTOR_MEMORY]
    still_high = health.evaluate_resource_health(
        nodes, vectors, second, NOW + timedelta(hours=1)
    )
    assert still_high.issues == second.issues
    recovered = health.evaluate_resource_health(
        node_stats(), vector_stats(), second, NOW + timedelta(minutes=10)
    )
    assert not recovered.issues


def test_resource_memory_does_not_join_different_nodes_or_stale_samples() -> None:
    first = health.evaluate_resource_health(
        node_stats(heap=90), vector_stats(), None, NOW
    )
    moved = health.evaluate_resource_health(
        node_stats(heap=90, node_id="node-2"),
        vector_stats(),
        first,
        NOW + timedelta(minutes=5),
    )
    stale = health.evaluate_resource_health(
        node_stats(heap=90), vector_stats(), first, NOW + timedelta(hours=1)
    )
    assert not moved.issues
    assert not stale.issues


def test_resource_vector_breaker_warns_immediately() -> None:
    result = health.evaluate_resource_health(
        node_stats(), vector_stats(tripped=True), None, NOW
    )
    assert result.issues == [ResourceIssue.VECTOR_MEMORY]


def test_resource_partial_response_does_not_report_recovery() -> None:
    nodes = node_stats()
    nodes.failed = 1
    with pytest.raises(ValueError, match="incomplete"):
        health.evaluate_resource_health(nodes, vector_stats(), None, NOW)


def test_resource_probe_is_cached_and_keeps_warning_on_failure(
    redis: TenantRedisClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    client_factory = MagicMock()
    client = client_factory.return_value.__enter__.return_value
    client.get_node_resource_stats.return_value = node_stats(free=10)
    client.get_vector_resource_stats.return_value = vector_stats()
    monkeypatch.setattr(health, "OpenSearchClient", client_factory)
    health.refresh_resource_health()
    assert health.get_resource_health().issues == [ResourceIssue.DISK]
    health.refresh_resource_health()
    client_factory.assert_called_once_with(timeout=3, max_retries=0)
    client.get_node_resource_stats.assert_called_once()
    redis.delete(health.RESOURCE_CHECK_LEASE_KEY)
    client.get_node_resource_stats.side_effect = TimeoutError()
    health.refresh_resource_health()
    assert health.get_resource_health().issues == [ResourceIssue.DISK]
    health.refresh_resource_health()
    assert client_factory.call_count == 2


def test_resource_admin_popup_is_daily_per_user_and_never_clears_banner(
    redis: TenantRedisClient,
) -> None:
    snapshot = health.evaluate_resource_health(
        node_stats(free=10), vector_stats(), None, NOW
    )
    redis.set(health.RESOURCE_SNAPSHOT_KEY, snapshot.model_dump_json())
    app = FastAPI()
    register_onyx_exception_handlers(app)
    app.include_router(api.router)
    user = User(
        id=ADMIN_IDS[0],
        effective_permissions=[Permission.FULL_ADMIN_PANEL_ACCESS.value],
    )
    app.dependency_overrides[current_user] = lambda: user
    with TestClient(app) as browser, TestClient(app) as other_browser:
        assert browser.post(f"{URL}/popup").json()["show_popup"]
        assert not other_browser.post(f"{URL}/popup").json()["show_popup"]
        assert browser.get(URL).json()["issues"] == ["disk"]
        key = f"{api.POPUP_KEY_PREFIX}:{user.id}"
        assert 86390 <= redis.ttl(key) <= api.POPUP_INTERVAL_SECONDS
        user.id = ADMIN_IDS[1]
        assert other_browser.post(f"{URL}/popup").json()["show_popup"]
        user.id = ADMIN_IDS[0]
        redis.delete(key)
        assert browser.post(f"{URL}/popup").json()["show_popup"]
        user.effective_permissions = []
        assert browser.get(URL).status_code == 403
        assert browser.post(f"{URL}/popup").status_code == 403


def test_resource_stale_warning_is_retained_without_new_popup(
    redis: TenantRedisClient,
) -> None:
    snapshot = health.evaluate_resource_health(
        node_stats(free=10), vector_stats(), None, NOW - timedelta(hours=1)
    )
    redis.set(health.RESOURCE_SNAPSHOT_KEY, snapshot.model_dump_json())
    user = User(id=ADMIN_IDS[0])
    result = api.claim_resource_popup(user)
    assert result.health.stale
    assert result.health.issues == [ResourceIssue.DISK]
    assert not result.show_popup
    assert not redis.exists(f"{api.POPUP_KEY_PREFIX}:{user.id}")


def test_resource_disabled_mode_never_probes(
    redis: TenantRedisClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(health, "DISABLE_VECTOR_DB", True)
    client_factory = MagicMock()
    monkeypatch.setattr(health, "OpenSearchClient", client_factory)
    health.refresh_resource_health()
    client_factory.assert_not_called()
    assert not health.get_resource_health().issues
    assert not redis.exists(health.RESOURCE_CHECK_LEASE_KEY)


@pytest.mark.parametrize("multi_tenant", [False, True])
@pytest.mark.parametrize("disabled", [False, True])
def test_resource_schedule_is_once_per_cluster(
    monkeypatch: pytest.MonkeyPatch, multi_tenant: bool, disabled: bool
) -> None:
    try:
        with monkeypatch.context() as patch:
            patch.setattr(configs, "MULTI_TENANT", multi_tenant)
            patch.setattr(app_configs, "DISABLE_VECTOR_DB", disabled)
            schedule = importlib.reload(beat_schedule)
            tasks = (
                schedule.get_cloud_tasks_to_schedule(8)
                if multi_tenant
                else schedule.get_tasks_to_schedule()
            )
            probes = [
                task
                for task in tasks
                if task["task"] == OnyxCeleryTask.MONITOR_OPENSEARCH_RESOURCES
            ]
            assert len(probes) == (0 if disabled else 1)
            if probes:
                probe = probes[0]
                assert probe["schedule"] == timedelta(minutes=5)
                assert probe["options"]["expires"] == 300
                assert probe["options"]["queue"] == OnyxCeleryQueues.MONITORING
                assert probe["name"].startswith("cloud_") == multi_tenant
    finally:
        importlib.reload(beat_schedule)
