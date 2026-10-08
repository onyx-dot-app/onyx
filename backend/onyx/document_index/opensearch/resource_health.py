from datetime import datetime, timezone

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
from onyx.utils.logger import setup_logger

logger = setup_logger()

RESOURCE_STALE_SECONDS: int = 3 * RESOURCE_CHECK_INTERVAL_SECONDS
DISK_USAGE_THRESHOLD_PERCENT: int = 85
HEAP_USAGE_THRESHOLD_PERCENT: int = 85
VECTOR_USAGE_THRESHOLD_PERCENT: int = 90
RESOURCE_SNAPSHOT_KEY: str = "opensearch_resource_snapshot"
RESOURCE_CHECK_LEASE_KEY: str = "opensearch_resource_check_lease"


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


def get_resource_health(*, operation_timeout_s: float | None = None) -> ResourceHealth:
    """`operation_timeout_s` bounds the read for background callers."""
    if DISABLE_VECTOR_DB:
        return ResourceHealth()
    redis: TenantRedisClient = get_shared_redis_client(
        operation_timeout_s=operation_timeout_s
    )
    raw: bytes | str | None = redis.get(RESOURCE_SNAPSHOT_KEY)
    if raw is None:
        return ResourceHealth()
    snapshot: ResourceSnapshot = ResourceSnapshot.model_validate_json(raw)
    return ResourceHealth(
        checked_at=snapshot.checked_at,
        issues=snapshot.issues,
        stale=(datetime.now(timezone.utc) - snapshot.checked_at).total_seconds()
        > RESOURCE_STALE_SECONDS,
    )


def refresh_resource_health() -> None:
    if DISABLE_VECTOR_DB:
        return
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
        snapshot: ResourceSnapshot = evaluate_resource_health(
            nodes, vectors, previous, datetime.now(timezone.utc)
        )
        # Keep the last observation on failure; the API marks old observations stale.
        redis.set(RESOURCE_SNAPSHOT_KEY, snapshot.model_dump_json())
    except Exception:
        logger.exception("Unable to refresh OpenSearch resource health")
