"""Bounded OpenSearch checks run only in the isolated fleet collector."""

from datetime import datetime, timezone
from typing import Any

from onyx.configs.app_configs import DISABLE_VECTOR_DB
from onyx.document_index.opensearch.client import OpenSearchClient
from onyx.document_index.opensearch.models import ResourceIssue, ResourceSnapshot
from onyx.document_index.opensearch.resource_health import (
    RESOURCE_SNAPSHOT_KEY,
    RESOURCE_STALE_SECONDS,
)
from onyx.redis.redis_pool import redis_pool
from onyx.utils.fleet_telemetry import BoundedTelemetry
from shared_configs.configs import DEFAULT_REDIS_PREFIX


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
        redis = redis_pool.get_client(DEFAULT_REDIS_PREFIX, operation_timeout_s=0.2)
        raw = redis.get(RESOURCE_SNAPSHOT_KEY)
        if raw:
            snapshot = ResourceSnapshot.model_validate_json(raw)
            stale = (now - snapshot.checked_at).total_seconds() > RESOURCE_STALE_SECONDS
            data.update(
                opensearch_resource_checked_at=snapshot.checked_at.isoformat(),
                opensearch_resource_stale=stale,
                opensearch_disk_pressure=ResourceIssue.DISK in snapshot.issues,
                opensearch_heap_pressure=ResourceIssue.JVM_MEMORY in snapshot.issues,
                opensearch_vector_pressure=ResourceIssue.VECTOR_MEMORY
                in snapshot.issues,
            )
    except Exception:
        pass
    client.emit("resource", data, service="opensearch")
