"""The OpenSearch cluster status that the admin Service Status page shows."""

from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel

from onyx.db.enums import VectorQuantization
from onyx.document_index.opensearch.client import (
    OpenSearchClient,
    vector_usage_percent,
)
from onyx.document_index.opensearch.constants import RESOURCE_CHECK_TIMEOUT_SECONDS
from onyx.document_index.opensearch.models import (
    ClusterIndexStatus,
    ClusterIssue,
    ClusterIssueKind,
    ClusterIssueSeverity,
    ClusterNodeStatus,
    ClusterStatus,
    NodeMemoryStats,
    NodeVectorBytes,
    UsageThresholds,
)
from onyx.document_index.opensearch.resource_health import (
    DISK_USAGE_THRESHOLD_PERCENT,
    HEAP_USAGE_THRESHOLD_PERCENT,
    VECTOR_USAGE_THRESHOLD_PERCENT,
)

# A reindex builds a second index next to the current one, so it needs free
# disk well below the point where OpenSearch stops placing shards.
DISK_WARNING_PERCENT: int = 75
# Above 100% the vectors that search reads no longer fit in the file cache.
VECTOR_CRITICAL_PERCENT: int = 100


class OnyxIndexRef(BaseModel):
    index_name: str
    is_current: bool
    model_name: str
    model_dim: int
    vector_quantization: VectorQuantization


def _int(row: dict[str, str], key: str) -> int:
    value: str | None = row.get(key)
    return int(value) if value and value.isdigit() else 0


def _disk_used_percent(node: ClusterNodeStatus) -> float:
    if node.disk_total_bytes <= 0:
        return 0.0
    return 100 * node.disk_used_bytes / node.disk_total_bytes


def _heap_used_percent(node: ClusterNodeStatus) -> float:
    if node.heap_max_bytes <= 0:
        return 0.0
    return 100 * node.heap_used_bytes / node.heap_max_bytes


def _node_issue(
    kind: ClusterIssueKind,
    severity: ClusterIssueSeverity,
    usage: dict[str, float],
) -> ClusterIssue | None:
    if not usage:
        return None
    return ClusterIssue(
        kind=kind,
        severity=severity,
        node_names=[
            name for name, _ in sorted(usage.items(), key=lambda item: -item[1])
        ],
        value=round(max(usage.values()), 1),
    )


def evaluate_cluster_issues(
    health: str, unassigned_shards: int, nodes: list[ClusterNodeStatus]
) -> list[ClusterIssue]:
    """Returns the cluster's issues, critical ones first."""
    issues: list[ClusterIssue | None] = []
    if health == "red":
        issues.append(
            ClusterIssue(
                kind=ClusterIssueKind.CLUSTER_RED,
                severity=ClusterIssueSeverity.CRITICAL,
                value=unassigned_shards,
            )
        )
    elif unassigned_shards > 0:
        issues.append(
            ClusterIssue(
                kind=ClusterIssueKind.UNASSIGNED_SHARDS,
                severity=ClusterIssueSeverity.WARNING,
                value=unassigned_shards,
            )
        )

    disk: dict[str, float] = {node.name: _disk_used_percent(node) for node in nodes}
    vector: dict[str, float] = {
        node.name: vector_usage_percent(node.vector_bytes, node.file_cache_bytes)
        for node in nodes
    }
    heap: dict[str, float] = {node.name: _heap_used_percent(node) for node in nodes}
    for kind, usage, warning, critical in (
        (
            ClusterIssueKind.DISK,
            disk,
            DISK_WARNING_PERCENT,
            DISK_USAGE_THRESHOLD_PERCENT,
        ),
        (
            ClusterIssueKind.VECTOR_MEMORY,
            vector,
            VECTOR_USAGE_THRESHOLD_PERCENT,
            VECTOR_CRITICAL_PERCENT,
        ),
        (ClusterIssueKind.JVM_MEMORY, heap, HEAP_USAGE_THRESHOLD_PERCENT, None),
    ):
        critical_usage: dict[str, float] = (
            {name: value for name, value in usage.items() if value >= critical}
            if critical is not None
            else {}
        )
        warning_usage: dict[str, float] = {
            name: value
            for name, value in usage.items()
            if warning <= value and name not in critical_usage
        }
        issues.append(_node_issue(kind, ClusterIssueSeverity.CRITICAL, critical_usage))
        issues.append(_node_issue(kind, ClusterIssueSeverity.WARNING, warning_usage))

    found: list[ClusterIssue] = [issue for issue in issues if issue is not None]
    return sorted(
        found, key=lambda issue: issue.severity != ClusterIssueSeverity.CRITICAL
    )


def collect_cluster_status(indexes: list[OnyxIndexRef]) -> ClusterStatus:
    """Reads the cluster's nodes, Onyx indexes and issues from OpenSearch."""
    with OpenSearchClient(
        timeout=RESOURCE_CHECK_TIMEOUT_SECONDS, max_retries=0
    ) as client:
        cluster: dict[str, Any] = client.cluster_health()
        memory: dict[str, NodeMemoryStats] = client.get_node_memory_stats().nodes
        vectors: dict[str, NodeVectorBytes] = client.get_node_vector_bytes()
        summaries: dict[str, dict[str, str]] = client.get_index_summaries(
            [index.index_name for index in indexes]
        )
        version: tuple[int, int] | None = client.get_opensearch_version()

    nodes: list[ClusterNodeStatus] = sorted(
        (
            ClusterNodeStatus(
                node_id=node_id,
                name=node.name,
                shard_count=vectors.get(node_id, NodeVectorBytes()).shard_count,
                memory_bytes=node.memory_bytes,
                file_cache_bytes=node.file_cache_bytes,
                vector_bytes=vectors.get(node_id, NodeVectorBytes()).vector_bytes,
                heap_max_bytes=node.heap_max_bytes,
                heap_used_bytes=node.heap_used_bytes,
                disk_total_bytes=node.disk_total_bytes,
                disk_used_bytes=node.disk_total_bytes - node.disk_available_bytes,
                cpu_percent=node.cpu_percent,
                load_average_1m=node.load_average_1m,
                search_queue=node.search_queue,
                search_rejected=node.search_rejected,
            )
            for node_id, node in memory.items()
        ),
        key=lambda node: node.name,
    )
    index_statuses: list[ClusterIndexStatus] = [
        ClusterIndexStatus(
            index_name=index.index_name,
            is_current=index.is_current,
            model_name=index.model_name,
            model_dim=index.model_dim,
            vector_quantization=index.vector_quantization,
            health=summaries[index.index_name].get("health"),
            chunk_count=_int(summaries[index.index_name], "docs.count"),
            deleted_chunk_count=_int(summaries[index.index_name], "docs.deleted"),
            store_size_bytes=_int(summaries[index.index_name], "store.size"),
            primary_shards=_int(summaries[index.index_name], "pri"),
            replicas=_int(summaries[index.index_name], "rep"),
        )
        for index in indexes
        if index.index_name in summaries
    ]
    health: str = str(cluster.get("status", "red"))
    unassigned: int = int(cluster.get("unassigned_shards", 0))
    issues: list[ClusterIssue] = evaluate_cluster_issues(health, unassigned, nodes)
    # A reindex creates its index after it starts, so only the current one counts.
    if any(index.is_current and index.index_name not in summaries for index in indexes):
        issues.insert(
            0,
            ClusterIssue(
                kind=ClusterIssueKind.INDEX_MISSING,
                severity=ClusterIssueSeverity.CRITICAL,
                value=0,
            ),
        )
    return ClusterStatus(
        checked_at=datetime.now(timezone.utc),
        version=f"{version[0]}.{version[1]}" if version else None,
        health=health,
        data_node_count=int(cluster.get("number_of_data_nodes", len(nodes))),
        primary_shards=int(cluster.get("active_primary_shards", 0)),
        active_shards=int(cluster.get("active_shards", 0)),
        unassigned_shards=unassigned,
        nodes=nodes,
        indexes=index_statuses,
        issues=issues,
        thresholds=UsageThresholds(
            disk_warning_percent=DISK_WARNING_PERCENT,
            disk_critical_percent=DISK_USAGE_THRESHOLD_PERCENT,
            vector_warning_percent=VECTOR_USAGE_THRESHOLD_PERCENT,
            vector_critical_percent=VECTOR_CRITICAL_PERCENT,
        ),
    )
