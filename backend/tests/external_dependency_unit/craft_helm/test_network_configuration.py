"""Render Craft network configuration and enforce its security prerequisites."""

import subprocess
from typing import Any

import pytest
import yaml

from tests.external_dependency_unit.craft_helm.rendering import render_chart


@pytest.mark.parametrize(
    "setting",
    [
        "sandboxProxy.listenHost=::",
        "sandboxProxy.allowGlobalClients=true",
        "sandboxProxy.egressAllowIPv6=true",
    ],
)
def test_ipv6_and_global_clients_require_internal_networks(setting: str) -> None:
    result: subprocess.CompletedProcess[str] = render_chart(["--set", setting])

    assert result.returncode != 0
    assert "sandboxProxy.internalCIDRs must include" in result.stderr

    result = render_chart(
        ["--set", setting, "--set", "sandboxProxy.internalCIDRs[0]=2600:ffff::/64"]
    )
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize("listen_host", ["0.0.0.0", "::"])
def test_sandbox_processes_share_the_configured_listener(listen_host: str) -> None:
    result = render_chart(["--set-string", f"sandboxPod.listenHost={listen_host}"])
    assert result.returncode == 0, result.stderr
    resources: list[dict[str, Any]] = [
        resource for resource in yaml.safe_load_all(result.stdout) if resource
    ]
    template: dict[str, Any] = next(
        resource for resource in resources if resource["kind"] == "PodTemplate"
    )
    spec: dict[str, Any] = template["template"]["spec"]
    containers: dict[str, dict[str, Any]] = {
        container["name"]: container
        for container in [*spec["containers"], *spec["initContainers"]]
    }
    for name in ("sandbox", "sidecar"):
        listeners: list[dict[str, str]] = [
            env
            for env in containers[name]["env"]
            if env["name"] == "SANDBOX_LISTEN_HOST"
        ]
        assert listeners == [{"name": "SANDBOX_LISTEN_HOST", "value": listen_host}]


def test_default_proxy_preserves_ipv4_without_runtime_egress_flag() -> None:
    result = render_chart()
    assert result.returncode == 0, result.stderr
    resources = [resource for resource in yaml.safe_load_all(result.stdout) if resource]
    proxy: dict[str, Any] = next(
        resource
        for resource in resources
        if resource["kind"] == "Deployment"
        and resource["metadata"]["labels"].get("app.kubernetes.io/component")
        == "sandbox-proxy"
    )
    env: dict[str, str | None] = {
        entry["name"]: entry.get("value")
        for entry in proxy["spec"]["template"]["spec"]["containers"][0]["env"]
    }
    assert env["SANDBOX_PROXY_LISTEN_HOST"] == "0.0.0.0"
    assert env["SANDBOX_PROXY_ALLOW_GLOBAL_CLIENTS"] == "false"
    assert env["SANDBOX_PROXY_INTERNAL_CIDRS"] == ""
    assert "SANDBOX_PROXY_EGRESS_ALLOW_IPV6" not in env
