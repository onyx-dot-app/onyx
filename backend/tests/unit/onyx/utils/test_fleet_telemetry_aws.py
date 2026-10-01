import json
from unittest.mock import Mock

import boto3
import pytest

from onyx.utils.fleet_telemetry import BoundedTelemetry, TelemetryConfig
from onyx.utils.fleet_telemetry_aws import collect_aws_resources


def test_managed_node_metrics_include_allocations_without_identifiers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sender = BoundedTelemetry(
        TelemetryConfig(
            "http://localhost:8787",
            "test-token",
            "11111111-1111-4111-8111-111111111111",
            "test-deployment",
            b"installation-secret-not-central-token",
        )
    )
    resource = {
        "kind": "opensearch",
        "resource_id": "PRIVATE_DOMAIN_SENTINEL",
        "node_id": "PRIVATE_NODE_SENTINEL",
        "account_id": "123456789012",
        "memory_limit_bytes": 1000000,
        "disk_limit_bytes": 10000000,
        "cpu_limit_cores": 2,
    }
    monkeypatch.setenv("ONYX_TELEMETRY_AWS_RESOURCES_JSON", json.dumps([resource]))
    cloudwatch = Mock()
    cloudwatch.get_metric_data.return_value = {
        "MetricDataResults": [
            {"Id": "m0", "StatusCode": "Complete", "Values": [25]},
            {"Id": "m1", "StatusCode": "Complete", "Values": [2]},
            {"Id": "m2", "StatusCode": "Complete", "Values": [80]},
        ]
    }
    monkeypatch.setattr(boto3, "client", Mock(return_value=cloudwatch))
    assert collect_aws_resources(sender) is True
    batch = sender._take_batch()
    assert len(batch) == 1 and batch[0]["service"] == "opensearch"
    assert batch[0]["data"]["memory_bytes"] == 800000
    assert batch[0]["data"]["memory_limit_bytes"] == 1000000
    assert batch[0]["data"]["cpu_cores"] == 0.5
    assert batch[0]["data"]["disk_bytes"] == 10000000 - 2 * 1024 * 1024
    assert "PRIVATE" not in json.dumps(batch) and "123456789012" not in json.dumps(
        batch
    )


def test_unconfigured_collector_never_initializes_sdk(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("ONYX_TELEMETRY_AWS_RESOURCES_JSON", raising=False)
    sdk = Mock(side_effect=AssertionError("must not initialize"))
    monkeypatch.setattr(boto3, "client", sdk)
    assert collect_aws_resources(Mock()) is None
    sdk.assert_not_called()


def test_cloudwatch_failure_is_reported_without_emission(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(
        "ONYX_TELEMETRY_AWS_RESOURCES_JSON", '[{"kind":"rds","resource_id":"PRIVATE"}]'
    )
    cloudwatch = Mock()
    cloudwatch.get_metric_data.side_effect = RuntimeError("PRIVATE_CREDENTIAL_SENTINEL")
    monkeypatch.setattr(boto3, "client", Mock(return_value=cloudwatch))
    sender = Mock()
    assert collect_aws_resources(sender) is False
    sender.emit.assert_not_called()


def test_resource_count_budget_rejects_before_io(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(
        "ONYX_TELEMETRY_AWS_RESOURCES_JSON",
        json.dumps([{"kind": "rds", "resource_id": "PRIVATE"}] * 33),
    )
    sdk = Mock(side_effect=AssertionError("must not initialize"))
    monkeypatch.setattr(boto3, "client", sdk)
    assert collect_aws_resources(Mock()) is False
    sdk.assert_not_called()
