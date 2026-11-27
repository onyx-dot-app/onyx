"""Render tests for the harness sandbox pods (harnessSandbox): the container
backend of chat sandbox tools on clusters without KVM. The PodTemplate goes
through PodRuntime's overlay, so the chart and the backend contract are
checked together."""

import json
import subprocess
from typing import Any
from uuid import UUID

import pytest
import yaml
from kubernetes import client

from onyx.server.features.build.sandbox.container.models import ContainerSpec
from onyx.server.features.build.sandbox.container.pod_runtime import (
    DAEMON_CONTAINER_NAME,
    PodRuntime,
)
from tests.external_dependency_unit.craft_helm.rendering import (
    render_chart,
    skip_or_fail,
)

_NO_CRAFT = ["--set-string", "configMap.ENABLE_CRAFT="]
_TEMPLATE = "harness-sandbox-pod"
_POLICY = "onyx-harness-sandbox-daemon"
_CA_BUNDLE = "/etc/ssl/sandbox/ca-bundle.crt"


def _render(args: list[str]) -> list[dict[str, Any]]:
    result: subprocess.CompletedProcess[str] = render_chart(args)
    if result.returncode != 0:
        if "missing in charts/" in result.stderr:
            skip_or_fail(f"chart dependencies not built: {result.stderr.strip()}")
        pytest.fail(f"helm template failed: {result.stderr.strip()}")
    return [d for d in yaml.safe_load_all(result.stdout) if d]


def _find(docs: list[dict[str, Any]], kind: str, name: str) -> dict[str, Any] | None:
    return next(
        (d for d in docs if d["kind"] == kind and d["metadata"]["name"] == name),
        None,
    )


def _configmap(docs: list[dict[str, Any]]) -> dict[str, str]:
    cm = _find(docs, "ConfigMap", "env-configmap")
    assert cm is not None
    return cm["data"]


def _harness_parts(docs: list[dict[str, Any]]) -> dict[str, bool]:
    return {
        "pod template": _find(docs, "PodTemplate", _TEMPLATE) is not None,
        "daemon policy": _find(docs, "NetworkPolicy", _POLICY) is not None,
        "sandbox proxy": _find(docs, "Deployment", "onyx-sandbox-proxy") is not None,
        "sandbox namespace": _find(docs, "Namespace", "onyx-sandboxes") is not None,
        "egress policy": _find(docs, "NetworkPolicy", "onyx-sandbox-egress")
        is not None,
        "sandbox rbac": any(
            d["kind"] == "Role" and d["metadata"]["name"].endswith("-sandbox-manager")
            for d in docs
        ),
        "container harness env": _configmap(docs).get("SANDBOX_CONTAINER_HARNESS")
        == "true",
    }


def _template(docs: list[dict[str, Any]]) -> dict[str, Any]:
    doc = _find(docs, "PodTemplate", _TEMPLATE)
    assert doc is not None
    return doc


def _containers(spec: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {c["name"]: c for c in [*spec["containers"], *spec["initContainers"]]}


@pytest.mark.parametrize("runtime", ["auto", "pod"])
def test_auto_and_pod_render_harness_pods_without_craft(runtime: str) -> None:
    docs = _render(
        [*_NO_CRAFT, "--set-string", f"craft.sandboxRuntime={runtime}"]
        + ["--set-string", "global.version=v6.0.0"]
    )
    assert all(_harness_parts(docs).values()), _harness_parts(docs)
    data = _configmap(docs)
    assert data["SANDBOX_RUNTIME"] == runtime
    assert data["SANDBOX_HARNESS_IMAGE"] == "onyxdotapp/craft-runtime:v6.0.0-container"
    assert data["SANDBOX_HARNESS_DAEMON_PORT"] == "8052"
    # No Craft pod parts.
    assert _find(docs, "PodTemplate", "sandbox-pod") is None
    assert _find(docs, "NetworkPolicy", "onyx-sandbox-push") is None


@pytest.mark.parametrize(
    "args",
    [
        [
            "--set-string",
            "craft.sandboxRuntime=firecracker",
            "--set-string",
            "global.version=v6.0.0",
            "--set",
            "auth.sandboxNodeRegistration.enabled=true",
            "--set-string",
            "auth.sandboxNodeRegistration.values.sandbox_node_registration_secret=reg-test-0123456789abcdef0123456789",
        ],
        ["--set-string", "craft.sandboxRuntime=off"],
        ["--set", "harnessSandbox.enabled=false"],
        # A release before v6 has no container backend.
        ["--set-string", "global.version=v5.2.0"],
        # Lite: no beat or heavy worker to stop idle pods.
        ["--set", "vectorDB.enabled=false"],
    ],
    ids=["firecracker", "off", "disabled", "pre-v6", "lite"],
)
def test_no_harness_pods(args: list[str]) -> None:
    docs = _render([*_NO_CRAFT, *args])
    parts = _harness_parts(docs)
    assert not parts["pod template"]
    assert not parts["daemon policy"]
    assert not parts["container harness env"]
    assert not parts["egress policy"]
    assert not parts["sandbox rbac"]


def test_craft_and_harness_pods_render_together() -> None:
    docs = _render([])
    assert _find(docs, "PodTemplate", "sandbox-pod") is not None
    assert _find(docs, "PodTemplate", _TEMPLATE) is not None


def test_runtime_class_and_scheduling() -> None:
    docs = _render(
        [
            *_NO_CRAFT,
            "--set-string",
            "harnessSandbox.runtimeClassName=gvisor",
            "--set-string",
            "harnessSandbox.nodeSelector.pool=sandbox",
        ]
    )
    spec = _template(docs)["template"]["spec"]
    assert spec["runtimeClassName"] == "gvisor"
    assert spec["nodeSelector"] == {"pool": "sandbox"}
    default = _template(_render(_NO_CRAFT))["template"]["spec"]
    assert "runtimeClassName" not in default
    # Any node by default; a sandbox pool is preferred and tolerated.
    assert "nodeSelector" not in default
    assert default["affinity"]["nodeAffinity"][
        "preferredDuringSchedulingIgnoredDuringExecution"
    ]
    assert {"key": "workload", "operator": "Equal", "value": "sandbox"}.items() <= (
        default["tolerations"][0].items()
    )


def test_pod_shape_shares_the_proxy_ca() -> None:
    spec = _template(_render(_NO_CRAFT))["template"]["spec"]
    containers = _containers(spec)
    init = containers["sandbox-init"]
    sandbox = containers[DAEMON_CONTAINER_NAME]
    assert init["command"] == ["/usr/local/bin/firewall-init"]
    assert init["securityContext"]["capabilities"]["add"] == ["NET_ADMIN"]
    init_mounts = {m["name"]: m for m in init["volumeMounts"]}
    assert init_mounts["sandbox-ca-bundle"]["mountPath"] == "/etc/ssl/sandbox"
    assert not init_mounts["sandbox-ca-bundle"].get("readOnly")
    mounts = {m["name"]: m for m in sandbox["volumeMounts"]}
    assert mounts["sandbox-ca-bundle"] == {
        "name": "sandbox-ca-bundle",
        "mountPath": "/etc/ssl/sandbox",
        "readOnly": True,
    }
    # The entrypoint adds this file to Chrome's NSS database.
    assert mounts["sandbox-ca-source"]["mountPath"] == "/sandbox-ca"
    volumes = {v["name"]: v for v in spec["volumes"]}
    assert volumes["sandbox-ca-bundle"] == {"name": "sandbox-ca-bundle", "emptyDir": {}}
    assert volumes["dshm"]["emptyDir"]["medium"] == "Memory"
    env = {e["name"]: e["value"] for e in sandbox["env"]}
    assert env["SSL_CERT_FILE"] == _CA_BUNDLE
    assert env["REQUESTS_CA_BUNDLE"] == _CA_BUNDLE
    assert env["SANDBOX_PROXY_CA_BUNDLE_SRC"] == "/sandbox-ca/ca.crt"
    assert env["HTTPS_PROXY"] == "http://sandbox-proxy:8080"
    assert spec["securityContext"]["runAsNonRoot"] is True
    assert spec["automountServiceAccountToken"] is False
    assert sandbox["securityContext"]["capabilities"] == {"drop": ["ALL"]}


def test_lockdown_off_drops_net_admin() -> None:
    spec = _template(
        _render([*_NO_CRAFT, "--set", "sandboxPod.netAdminLockdown=false"])
    )["template"]["spec"]
    init = _containers(spec)["sandbox-init"]
    assert "add" not in init["securityContext"]["capabilities"]


def test_daemon_policy_admits_only_the_callers() -> None:
    docs = _render([*_NO_CRAFT, "--set", "harnessSandbox.daemonPort=9443"])
    policy = _find(docs, "NetworkPolicy", _POLICY)
    assert policy is not None
    assert policy["metadata"]["namespace"] == "onyx-sandboxes"
    assert policy["spec"]["podSelector"]["matchLabels"] == {
        "app.kubernetes.io/component": "sandbox",
        "onyx.app/sandbox-kind": "harness",
    }
    (rule,) = policy["spec"]["ingress"]
    assert rule["ports"] == [{"protocol": "TCP", "port": 9443}]
    assert sorted(
        peer["podSelector"]["matchLabels"]["app"] for peer in rule["from"]
    ) == [
        "api-server",
        "celery-worker-heavy",
        "celery-worker-light",
        "celery-worker-scheduled-tasks",
    ]
    for peer in rule["from"]:
        assert peer["namespaceSelector"]["matchLabels"] == {
            "kubernetes.io/metadata.name": "onyx"
        }
    assert _configmap(docs)["SANDBOX_HARNESS_DAEMON_PORT"] == "9443"


def test_configmap_values_do_not_duplicate_the_chart_keys() -> None:
    docs = _render(
        [*_NO_CRAFT, "--set-string", "configMap.SANDBOX_CONTAINER_HARNESS=false"]
    )
    assert _configmap(docs)["SANDBOX_CONTAINER_HARNESS"] == "true"


class _FakeCoreApi:
    def __init__(self, template: client.V1PodTemplate) -> None:
        self._template = template

    def read_namespaced_pod_template(
        self, name: str, namespace: str
    ) -> client.V1PodTemplate:
        assert (name, namespace) == (_TEMPLATE, "onyx-sandboxes")
        return self._template


def test_pod_runtime_builds_a_pod_from_the_rendered_template() -> None:
    rendered = _template(_render(_NO_CRAFT))

    class _Resp:
        data = json.dumps(rendered)

    template = client.ApiClient().deserialize(_Resp(), "V1PodTemplate")
    runtime = PodRuntime(
        core_api=_FakeCoreApi(template),  # ty: ignore[invalid-argument-type]
        namespace="onyx-sandboxes",
        template_name=_TEMPLATE,
        proxy_host="",
    )
    sandbox_id = UUID("00000000-0000-0000-0000-0000000000aa")
    pod = runtime.build_pod(
        ContainerSpec(
            tenant_id="public",
            sandbox_id=sandbox_id,
            attempt=1,
            name=f"harness-{sandbox_id}-1",
        )
    )
    labels = pod.metadata.labels
    assert labels["onyx.app/sandbox-kind"] == "harness"
    assert labels["app.kubernetes.io/component"] == "sandbox"
    containers = {c.name: c for c in pod.spec.containers}
    daemon = containers[DAEMON_CONTAINER_NAME]
    assert daemon.command == ["/usr/local/bin/sandbox-entrypoint"]
    assert daemon.ports[0].container_port == 8052
    mounts = {m.name: m.mount_path for m in daemon.volume_mounts}
    # The template's mounts stay beside the overlay's.
    assert mounts["sandbox-ca-bundle"] == "/etc/ssl/sandbox"
    assert mounts["daemon-files"] == "/run/craft-fc/daemon"
    assert [c.name for c in pod.spec.init_containers] == ["sandbox-init"]
    assert pod.spec.restart_policy == "Always"
