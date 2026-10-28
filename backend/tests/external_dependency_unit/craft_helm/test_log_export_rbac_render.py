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
