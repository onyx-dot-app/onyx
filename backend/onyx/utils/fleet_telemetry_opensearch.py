"""Bounded OpenSearch checks run only in the isolated fleet collector."""

from datetime import datetime, timezone
from typing import Any

from onyx.configs.app_configs import DISABLE_VECTOR_DB
from onyx.document_index.opensearch.client import OpenSearchClient
from onyx.document_index.opensearch.models import ResourceHealth, ResourceIssue
from onyx.document_index.opensearch.resource_health import get_resource_health
from onyx.utils.fleet_telemetry import BoundedTelemetry


def collect_opensearch_health(client: BoundedTelemetry) -> None:
    if DISABLE_VECTOR_DB:
        return
    now = datetime.now(timezone.utc)
    data: dict[str, Any] = {
        "service_instance_id": "opensearch-health",
        "shared": True,
        "opensearch_status": "unavailable",
        "opensearch_checked_at": now.isoformat(),
        "opensearch_resource_stale": True,
    }
    try:
        with OpenSearchClient(timeout=2, max_retries=0) as search:
            health = search.cluster_health()
        status = health.get("status")
        if status in {"green", "yellow", "red"} and not health.get("timed_out"):
            data["opensearch_status"] = status
            for key in (
                "number_of_nodes",
                "number_of_data_nodes",
                "active_shards",
                "unassigned_shards",
                "initializing_shards",
                "relocating_shards",
                "number_of_pending_tasks",
            ):
                value = health.get(key)
                if type(value) is int and value >= 0:
                    data["opensearch_" + key] = value
    except Exception:
        # No endpoint, credentials, cluster names, or raw exceptions leave this collector.
        pass
    try:
        resources: ResourceHealth = get_resource_health(operation_timeout_s=0.2)
        if resources.checked_at is not None:
            data.update(
                opensearch_resource_checked_at=resources.checked_at.isoformat(),
                opensearch_resource_stale=resources.stale,
                opensearch_disk_pressure=ResourceIssue.DISK in resources.issues,
                opensearch_heap_pressure=ResourceIssue.JVM_MEMORY in resources.issues,
                opensearch_vector_pressure=ResourceIssue.VECTOR_MEMORY
                in resources.issues,
            )
    except Exception:
        pass
    client.emit("resource", data, service="opensearch")
