from datetime import datetime, timezone
from typing import Any

from onyx.configs.app_configs import DISABLE_VECTOR_DB
from onyx.document_index.opensearch.client import OpenSearchClient
from onyx.document_index.opensearch.constants import (
    RESOURCE_CHECK_INTERVAL_SECONDS,
    RESOURCE_CHECK_TIMEOUT_SECONDS,
)
from onyx.document_index.opensearch.models import (
    NodesResourceStats,
    ResourceHealth,
    ResourceIssue,
    ResourceSnapshot,
    VectorResourceStats,
)
from onyx.redis.redis_pool import get_shared_redis_client
from onyx.redis.tenant_redis_client import TenantRedisClient
from onyx.utils.fleet_telemetry import emit_telemetry
from onyx.utils.logger import setup_logger

logger = setup_logger()

RESOURCE_STALE_SECONDS: int = 3 * RESOURCE_CHECK_INTERVAL_SECONDS
DISK_USAGE_THRESHOLD_PERCENT: int = 85
HEAP_USAGE_THRESHOLD_PERCENT: int = 85
VECTOR_USAGE_THRESHOLD_PERCENT: int = 90
RESOURCE_SNAPSHOT_KEY: str = "opensearch_resource_snapshot"
RESOURCE_CHECK_LEASE_KEY: str = "opensearch_resource_check_lease"
# Cluster health counts that fleet telemetry reports.
_CLUSTER_COUNTS: tuple[str, ...] = (
    "number_of_nodes",
    "number_of_data_nodes",
    "active_shards",
    "unassigned_shards",
    "initializing_shards",
    "relocating_shards",
    "number_of_pending_tasks",
)


def evaluate_resource_health(
    nodes: NodesResourceStats,
    vectors: VectorResourceStats,
    previous: ResourceSnapshot | None,
    now: datetime,
) -> ResourceSnapshot:
    if nodes.failed or vectors.failed:
        raise ValueError("OpenSearch resource statistics are incomplete")

    heap_high_nodes: set[str] = {
        node_id
        for node_id, node in nodes.nodes.items()
        if node.heap_used_percent >= HEAP_USAGE_THRESHOLD_PERCENT
    }
    vector_high_nodes: set[str] = {
        node_id
        for node_id, node in vectors.nodes.items()
        if node.graph_memory_usage_percentage >= VECTOR_USAGE_THRESHOLD_PERCENT
    }
    issues: list[ResourceIssue] = []
    if any(
        100 * (disk.total_in_bytes - disk.available_in_bytes)
        >= DISK_USAGE_THRESHOLD_PERCENT * disk.total_in_bytes
        for node in nodes.nodes.values()
        for disk in node.disks
    ):
        issues.append(ResourceIssue.DISK)

    # Require repeated pressure on the same node, separated by a scheduled check.
    previous_is_recent: bool = previous is not None and (
        RESOURCE_CHECK_INTERVAL_SECONDS / 2
        <= (now - previous.checked_at).total_seconds()
        <= RESOURCE_STALE_SECONDS
    )
    if previous is not None:
        if heap_high_nodes & previous.heap_high_nodes and (
            previous_is_recent or ResourceIssue.JVM_MEMORY in previous.issues
        ):
            issues.append(ResourceIssue.JVM_MEMORY)
        if vector_high_nodes & previous.vector_high_nodes and (
            previous_is_recent or ResourceIssue.VECTOR_MEMORY in previous.issues
        ):
            issues.append(ResourceIssue.VECTOR_MEMORY)
    if vectors.circuit_breaker_triggered and ResourceIssue.VECTOR_MEMORY not in issues:
        issues.append(ResourceIssue.VECTOR_MEMORY)

    return ResourceSnapshot(
        checked_at=now,
        issues=issues,
        heap_high_nodes=heap_high_nodes,
        vector_high_nodes=vector_high_nodes,
    )


def get_resource_health() -> ResourceHealth:
    if DISABLE_VECTOR_DB:
        return ResourceHealth()
    raw: bytes | str | None = get_shared_redis_client().get(RESOURCE_SNAPSHOT_KEY)
    if raw is None:
        return ResourceHealth()
    snapshot: ResourceSnapshot = ResourceSnapshot.model_validate_json(raw)
    return ResourceHealth(
        checked_at=snapshot.checked_at,
        issues=snapshot.issues,
        stale=(datetime.now(timezone.utc) - snapshot.checked_at).total_seconds()
        > RESOURCE_STALE_SECONDS,
    )


def _report_to_fleet(
    cluster: dict[str, Any] | None, snapshot: ResourceSnapshot | None
) -> None:
    """Fleet telemetry: cluster status, shard counts, and resource pressure."""
    data: dict[str, Any] = {
        "service_instance_id": "opensearch-health",
        "shared": True,
        "opensearch_status": "unavailable",
        "opensearch_checked_at": datetime.now(timezone.utc).isoformat(),
    }
    status: object = (cluster or {}).get("status")
    if (
        cluster
        and status in {"green", "yellow", "red"}
        and not cluster.get("timed_out")
    ):
        data["opensearch_status"] = status
        for key in _CLUSTER_COUNTS:
            value: object = cluster.get(key)
            if type(value) is int and value >= 0:
                data["opensearch_" + key] = value
    if snapshot is not None:
        data.update(
            opensearch_resource_checked_at=snapshot.checked_at.isoformat(),
            opensearch_resource_stale=False,
            opensearch_disk_pressure=ResourceIssue.DISK in snapshot.issues,
            opensearch_heap_pressure=ResourceIssue.JVM_MEMORY in snapshot.issues,
            opensearch_vector_pressure=ResourceIssue.VECTOR_MEMORY in snapshot.issues,
        )
    emit_telemetry("resource", data, service="opensearch")


def refresh_resource_health() -> None:
    if DISABLE_VECTOR_DB:
        return
    cluster: dict[str, Any] | None = None
    snapshot: ResourceSnapshot | None = None
    try:
        redis: TenantRedisClient = get_shared_redis_client()
        # Retain the lease on failure too, so duplicate tasks cannot hammer an unhealthy cluster.
        if not redis.set(
            RESOURCE_CHECK_LEASE_KEY, "1", nx=True, ex=RESOURCE_CHECK_INTERVAL_SECONDS
        ):
            return
        raw: bytes | str | None = redis.get(RESOURCE_SNAPSHOT_KEY)
        previous: ResourceSnapshot | None = (
            ResourceSnapshot.model_validate_json(raw) if raw else None
        )
        with OpenSearchClient(
            timeout=RESOURCE_CHECK_TIMEOUT_SECONDS, max_retries=0
        ) as client:
            nodes: NodesResourceStats = client.get_node_resource_stats()
            vectors: VectorResourceStats = client.get_vector_resource_stats()
            try:
                cluster = client.cluster_health()
            except Exception:
                # Only fleet telemetry reads the cluster status.
                pass
        snapshot = evaluate_resource_health(
            nodes, vectors, previous, datetime.now(timezone.utc)
        )
        # Keep the last observation on failure; the API marks old observations stale.
        redis.set(RESOURCE_SNAPSHOT_KEY, snapshot.model_dump_json())
    except Exception:
        logger.exception("Unable to refresh OpenSearch resource health")
    _report_to_fleet(cluster, snapshot)
