"""The log export's Kubernetes access is off by default. When on, only the
api-server gets it, through its own service account; the other Onyx pods keep
the shared one."""

from typing import Any

import pytest
import yaml

from tests.external_dependency_unit.craft_helm.rendering import render_chart

_ENABLED = ["--set", "logExport.kubernetes.enabled=true"]
_API_SERVER_SA = "onyx-api-server"
_LOG_EXPORT_KINDS = ("ServiceAccount", "Role", "RoleBinding")


def _render(extra_args: list[str]) -> list[dict[str, Any]]:
    result = render_chart(extra_args)
    assert result.returncode == 0, result.stderr
    return [resource for resource in yaml.safe_load_all(result.stdout) if resource]


def _log_export_resources(resources: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {
        resource["kind"]: resource
        for resource in resources
        if resource["kind"] in _LOG_EXPORT_KINDS
        and resource["metadata"]["name"] in (_API_SERVER_SA, "onyx-log-export")
    }


def _service_account_of(resources: list[dict[str, Any]], deployment: str) -> str:
    [workload] = [
        resource
        for resource in resources
        if resource["kind"] == "Deployment"
        and resource["metadata"]["name"] == deployment
    ]
    return workload["spec"]["template"]["spec"]["serviceAccountName"]


@pytest.mark.parametrize(
    "extra_args",
    [
        [],
        ["--set", "serviceAccount.create=true"],
        # A --reuse-values upgrade from a release without the setting.
        ["--set", "logExport=null"],
    ],
)
def test_log_export_kubernetes_access_is_off_by_default(
    extra_args: list[str],
) -> None:
    resources = _render(extra_args)
    assert _log_export_resources(resources) == {}
    assert _service_account_of(resources, "onyx-api-server") != _API_SERVER_SA


def test_enabled_binds_only_the_api_server() -> None:
    resources = _render(
        [*_ENABLED, "--set", "serviceAccount.create=true", *_ALL_WORKLOADS_ARGS]
    )
    log_export = _log_export_resources(resources)

    [rule] = log_export["Role"]["rules"]
    assert set(rule["resources"]) == {"pods", "pods/log", "events"}
    assert set(rule["verbs"]) == {"get", "list"}
    assert log_export["RoleBinding"]["subjects"] == [
        {"kind": "ServiceAccount", "name": _API_SERVER_SA, "namespace": "onyx"}
    ]
    assert log_export["ServiceAccount"]["automountServiceAccountToken"] is True

    assert _service_account_of(resources, "onyx-api-server") == _API_SERVER_SA
    other_pods_on_api_server_account = [
        resource["metadata"]["name"]
        for resource in resources
        if resource["kind"] in ("Deployment", "StatefulSet")
        and resource["metadata"]["name"] != "onyx-api-server"
        and resource["spec"]["template"]["spec"].get("serviceAccountName")
        == _API_SERVER_SA
    ]
    assert other_pods_on_api_server_account == []
    assert _service_account_of(resources, "onyx-web-server") == "onyx"


def test_enabled_turns_on_the_backend_collector() -> None:
    def _collector_env(resources: list[dict[str, Any]]) -> list[dict[str, Any]]:
        [workload] = [
            resource
            for resource in resources
            if resource["kind"] == "Deployment"
            and resource["metadata"]["name"] == "onyx-api-server"
        ]
        [container] = workload["spec"]["template"]["spec"]["containers"]
        return [
            env
            for env in container.get("env") or []
            if env["name"] == "LOG_EXPORT_KUBERNETES_ENABLED"
        ]

    assert _collector_env(_render(_ENABLED)) == [
        {"name": "LOG_EXPORT_KUBERNETES_ENABLED", "value": "true"}
    ]
    assert _collector_env(_render([])) == []


@pytest.mark.parametrize(
    ("extra_args", "bound_service_accounts"),
    [
        ([], ["onyx"]),
        (_ENABLED, ["onyx", _API_SERVER_SA]),
    ],
)
def test_craft_bindings_follow_the_api_server_account(
    extra_args: list[str], bound_service_accounts: list[str]
) -> None:
    """The api-server provisions Craft sandboxes, so it keeps the sandbox-manager
    and proxy-resolve access when it moves to its own service account."""
    resources = _render(
        [
            "--set-string",
            "configMap.ENABLE_CRAFT=true",
            "--set",
            "serviceAccount.create=true",
            *extra_args,
        ]
    )
    craft_bindings = [
        resource
        for resource in resources
        if resource["kind"] == "RoleBinding"
        and resource["metadata"]["labels"].get("app.kubernetes.io/component")
        == "sandbox-manager"
    ]
    assert len(craft_bindings) == 2
    for binding in craft_bindings:
        assert [subject["name"] for subject in binding["subjects"]] == (
            bound_service_accounts
        )


def test_api_server_service_account_keeps_the_shared_annotations() -> None:
    resources = _render(
        [
            *_ENABLED,
            "--set",
            "serviceAccount.annotations.shared=a",
            "--set",
            "serviceAccount.annotations.overridden=a",
            "--set",
            "logExport.kubernetes.serviceAccount.annotations.overridden=b",
        ]
    )
    annotations = _log_export_resources(resources)["ServiceAccount"]["metadata"][
        "annotations"
    ]
    assert annotations == {"shared": "a", "overridden": "b"}


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
