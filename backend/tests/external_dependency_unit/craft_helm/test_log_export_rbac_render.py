"""The chart grants the log export read access to pods, pod logs, and events:
``logExport.kubernetesRbac.mode`` auto binds only a named service account,
true always binds (also to "default"), and false never binds."""

from typing import Any

import pytest
import yaml

from tests.external_dependency_unit.craft_helm.rendering import render_chart

# Service account setups: the namespace default, one the chart creates, and one
# the operator names.
_DEFAULT_SA: list[str] = []
_CREATED_SA = ["--set", "serviceAccount.create=true"]
_NAMED_SA = ["--set", "serviceAccount.name=onyx-runtime"]


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


@pytest.mark.parametrize(
    ("mode_args", "service_account_args", "bound_service_account"),
    [
        ([], _DEFAULT_SA, None),
        ([], _CREATED_SA, "onyx"),
        ([], _NAMED_SA, "onyx-runtime"),
        (["--set", "logExport.kubernetesRbac.mode=true"], _DEFAULT_SA, "default"),
        (["--set", "logExport.kubernetesRbac.mode=true"], _CREATED_SA, "onyx"),
        (
            ["--set-string", "logExport.kubernetesRbac.mode=true"],
            _NAMED_SA,
            "onyx-runtime",
        ),
        (["--set", "logExport.kubernetesRbac.mode=false"], _DEFAULT_SA, None),
        (["--set", "logExport.kubernetesRbac.mode=false"], _CREATED_SA, None),
        (["--set", "logExport.kubernetesRbac.mode=false"], _NAMED_SA, None),
    ],
)
def test_log_export_rbac_modes(
    mode_args: list[str],
    service_account_args: list[str],
    bound_service_account: str | None,
) -> None:
    resources = _log_export_resources([*mode_args, *service_account_args])

    if bound_service_account is None:
        assert resources == []
        return

    role = next(r for r in resources if r["kind"] == "Role")
    [rule] = role["rules"]
    assert set(rule["resources"]) == {"pods", "pods/log", "events"}
    assert set(rule["verbs"]) == {"get", "list"}
    assert role["metadata"]["namespace"] == "onyx"

    binding = next(r for r in resources if r["kind"] == "RoleBinding")
    assert binding["roleRef"]["name"] == role["metadata"]["name"]
    assert binding["subjects"] == [
        {"kind": "ServiceAccount", "name": bound_service_account, "namespace": "onyx"}
    ]


def test_log_export_rbac_rejects_unknown_mode() -> None:
    result = render_chart(["--set", "logExport.kubernetesRbac.mode=sometimes"])
    assert result.returncode != 0
    assert "logExport.kubernetesRbac.mode must be auto, true, or false" in (
        result.stderr
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
# Helm prefixes each rendered document with its template path. Subchart
# documents come from ``onyx/charts/<subchart>/``, which the log export does
# not collect.
_ONYX_TEMPLATE_SOURCE = "# Source: onyx/templates/"


def _onyx_chart_documents(rendered: str) -> list[dict[str, Any]]:
    documents: list[dict[str, Any]] = []
    for document in rendered.split("\n---\n"):
        if _ONYX_TEMPLATE_SOURCE not in document:
            continue
        resource = yaml.safe_load(document)
        if resource:
            documents.append(resource)
    return documents


def test_every_onyx_pod_carries_the_release_labels() -> None:
    """The log export selects the Onyx chart's pods by these labels."""
    result = render_chart(_ALL_WORKLOADS_ARGS)
    assert result.returncode == 0, result.stderr

    workloads = [
        resource
        for resource in _onyx_chart_documents(result.stdout)
        if resource["kind"] in _POD_WORKLOAD_KINDS
    ]
    assert workloads
    unlabeled = [
        resource["metadata"]["name"]
        for resource in workloads
        if not _RELEASE_LABELS.items()
        <= (resource["spec"]["template"]["metadata"].get("labels") or {}).items()
    ]
    assert unlabeled == []
