"""The chart grants the api-server's service account read access to pods, pod
logs, and events for the log export, and drops the grant when disabled."""

from typing import Any

import yaml

from tests.external_dependency_unit.craft_helm.rendering import render_chart


def _log_export_resources(extra_args: list[str]) -> list[dict[str, Any]]:
    result = render_chart(extra_args)
    assert result.returncode == 0, result.stderr
    return [
        resource
        for resource in yaml.safe_load_all(result.stdout)
        if resource
        and resource["kind"] in ("Role", "RoleBinding")
        and resource["metadata"]["name"].endswith("log-export")
    ]


def test_log_export_rbac_binds_read_access_to_service_account() -> None:
    resources = _log_export_resources(["--set", "serviceAccount.create=true"])

    role = next(r for r in resources if r["kind"] == "Role")
    [rule] = role["rules"]
    assert set(rule["resources"]) == {"pods", "pods/log", "events"}
    assert set(rule["verbs"]) == {"get", "list"}
    assert role["metadata"]["namespace"] == "onyx"

    binding = next(r for r in resources if r["kind"] == "RoleBinding")
    assert binding["roleRef"]["name"] == role["metadata"]["name"]
    assert binding["subjects"] == [
        {"kind": "ServiceAccount", "name": "onyx", "namespace": "onyx"}
    ]


def test_log_export_rbac_disabled() -> None:
    assert (
        _log_export_resources(["--set", "logExport.kubernetesRbac.enabled=false"]) == []
    )


# Turns on the workloads values-ci.yaml leaves off.
_ALL_WORKLOADS_ARGS = [
    "--set",
    ",".join(
        [
            "webserver.replicaCount=1",
            "celery_worker_docfetching.replicaCount=1",
            "celery_worker_docprocessing.replicaCount=1",
            "celery_worker_user_file_processing.replicaCount=1",
            "celery_worker_monitoring.replicaCount=1",
            "slackbot.enabled=true",
            "discordbot.enabled=true",
            "mcpServer.enabled=true",
            "inferenceCapability.replicaCount=1",
            "indexCapability.replicaCount=1",
        ]
    ),
]
_RELEASE_LABELS = {
    "app.kubernetes.io/name": "onyx",
    "app.kubernetes.io/instance": "onyx",
}
_POD_WORKLOAD_KINDS = ("Deployment", "StatefulSet", "DaemonSet", "Job")


def test_every_onyx_pod_carries_the_release_labels() -> None:
    """The log export selects Onyx pods by these labels."""
    result = render_chart(_ALL_WORKLOADS_ARGS)
    assert result.returncode == 0, result.stderr

    unlabeled = [
        resource["metadata"]["name"]
        for resource in yaml.safe_load_all(result.stdout)
        if resource
        and resource["kind"] in _POD_WORKLOAD_KINDS
        and not _RELEASE_LABELS.items()
        <= (resource["spec"]["template"]["metadata"].get("labels") or {}).items()
    ]
    assert unlabeled == []
