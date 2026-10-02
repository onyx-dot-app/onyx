"""Optional bounded CloudWatch reads in the isolated collector only.

Resource IDs stay in local configuration. Central telemetry receives a keyed
hash and a fixed service role. Allocations must describe the same metric scope
(instance/node, not an unrelated cluster total); absent allocations stay null.
"""

import json
import math
import os
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from onyx.utils.fleet_telemetry import BoundedTelemetry

_METRICS = {
    "rds": (
        "AWS/RDS",
        "DBInstanceIdentifier",
        "postgres",
        {
            "cpu": "CPUUtilization",
            "memory_free": "FreeableMemory",
            "disk_free": "FreeStorageSpace",
        },
    ),
    "elasticache": (
        "AWS/ElastiCache",
        "CacheClusterId",
        "redis",
        {
            "cpu": "CPUUtilization",
            "memory_used": "BytesUsedForCache",
            "memory_percent": "DatabaseMemoryUsagePercentage",
        },
    ),
    "opensearch": (
        "AWS/ES",
        "DomainName",
        "opensearch",
        {
            "cpu": "CPUUtilization",
            "disk_free_mb": "FreeStorageSpace",
            "system_memory_percent": "SysMemoryUtilization",
        },
    ),
}


def _allocation(resource: dict[str, Any], name: str) -> float | None:
    value = resource.get(name)
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return None
    return float(value) if math.isfinite(value) and 0 < value <= 1e18 else None


def _target(
    resource: dict[str, Any],
) -> tuple[str, str, dict[str, str], list[dict[str, str]]] | None:
    kind, resource_id = resource.get("kind"), resource.get("resource_id")
    if (
        kind not in _METRICS
        or not isinstance(resource_id, str)
        or not 0 < len(resource_id) <= 256
    ):
        return None
    namespace, dimension, service, metrics = _METRICS[kind]
    dimensions = [{"Name": dimension, "Value": resource_id}]
    if kind == "elasticache":
        node = resource.get("node_id")
        if not isinstance(node, str) or not node:
            return None
        dimensions.append({"Name": "CacheNodeId", "Value": node})
    elif kind == "opensearch":
        account, node = resource.get("account_id"), resource.get("node_id")
        if (
            not isinstance(account, str)
            or not account.isdigit()
            or len(account) != 12
            or not isinstance(node, str)
            or not node
        ):
            return None
        dimensions.extend(
            [{"Name": "ClientId", "Value": account}, {"Name": "NodeId", "Value": node}]
        )
    return namespace, service, metrics, dimensions


def collect_aws_resources(client: "BoundedTelemetry") -> bool | None:
    """At most 32 resources, one bounded AWS request with zero retries."""
    try:
        raw = os.environ.get("ONYX_TELEMETRY_AWS_RESOURCES_JSON", "[]")
        if raw == "[]":
            return None
        if len(raw) > 16384:
            return False
        resources = json.loads(raw)
        if not isinstance(resources, list) or len(resources) > 32:
            return False
        queries: list[dict[str, Any]] = []
        targets: list[tuple[dict[str, Any], str, dict[str, str]]] = []
        for resource in resources:
            if not isinstance(resource, dict):
                continue
            target = _target(resource)
            if target is None:
                continue
            namespace, service, metrics, dimensions = target
            ids = {}
            for metric_key, metric_name in metrics.items():
                query_id = f"m{len(queries)}"
                ids[metric_key] = query_id
                queries.append(
                    {
                        "Id": query_id,
                        "MetricStat": {
                            "Metric": {
                                "Namespace": namespace,
                                "MetricName": metric_name,
                                "Dimensions": dimensions,
                            },
                            "Period": 60,
                            "Stat": "Average",
                        },
                        "ReturnData": True,
                    }
                )
            targets.append((resource, service, ids))
        if not queries:
            return False if resources else None
        import boto3
        from botocore.config import Config

        cloudwatch = boto3.client(
            "cloudwatch",
            region_name=os.environ.get("AWS_REGION", "us-east-2"),
            config=Config(
                connect_timeout=1, read_timeout=2, retries={"total_max_attempts": 1}
            ),
        )
        # Five completed minute buckets keep all 32 x 3 metrics below the cap.
        end = datetime.now(timezone.utc).replace(second=0, microsecond=0)
        response = cloudwatch.get_metric_data(
            MetricDataQueries=queries,
            StartTime=end - timedelta(minutes=5),
            EndTime=end,
            ScanBy="TimestampDescending",
            MaxDatapoints=500,
        )
        values = {
            result["Id"]: float(result["Values"][0])
            for result in response.get("MetricDataResults", [])
            if result.get("StatusCode") == "Complete"
            and result.get("Values")
            and math.isfinite(result["Values"][0])
            and result["Values"][0] >= 0
        }
        for resource, service, ids in targets:
            metrics = {
                name: values[query_id]
                for name, query_id in ids.items()
                if query_id in values
            }
            if not metrics:
                continue
            memory_limit = _allocation(resource, "memory_limit_bytes")
            disk_limit = _allocation(resource, "disk_limit_bytes")
            cpu_limit = _allocation(resource, "cpu_limit_cores")
            data: dict[str, Any] = {
                "service_instance_id": client.fingerprint(
                    "aws:"
                    + resource["kind"]
                    + ":"
                    + resource["resource_id"]
                    + ":"
                    + str(resource.get("node_id", ""))
                ),
                "shared": True,
            }
            if cpu_limit is not None and "cpu" in metrics:
                data.update(
                    cpu_limit_cores=cpu_limit,
                    cpu_cores=cpu_limit * metrics["cpu"] / 100,
                )
            if "memory_used" in metrics:
                used = metrics["memory_used"]
                percent = metrics.get("memory_percent", 0)
                limit = memory_limit or (used * 100 / percent if percent > 0 else None)
                data.update(
                    memory_bytes=round(used),
                    memory_limit_bytes=round(limit) if limit else None,
                )
            elif memory_limit is not None and "memory_free" in metrics:
                data.update(
                    memory_bytes=round(max(0, memory_limit - metrics["memory_free"])),
                    memory_limit_bytes=round(memory_limit),
                )
            elif memory_limit is not None and "system_memory_percent" in metrics:
                data.update(
                    memory_bytes=round(
                        memory_limit * metrics["system_memory_percent"] / 100
                    ),
                    memory_limit_bytes=round(memory_limit),
                )
            free = metrics.get(
                "disk_free", metrics.get("disk_free_mb", 0) * 1024 * 1024
            )
            if disk_limit is not None and (
                "disk_free" in metrics or "disk_free_mb" in metrics
            ):
                data.update(
                    disk_bytes=round(max(0, disk_limit - free)),
                    disk_limit_bytes=round(disk_limit),
                )
            if len(data) > 2:
                client.emit("resource", data, service=service)
        return bool(response.get("MetricDataResults")) and all(
            result.get("StatusCode") == "Complete"
            for result in response.get("MetricDataResults", [])
        )
    except Exception:
        # Never log configuration, resource identifiers, AWS responses or errors.
        return False
