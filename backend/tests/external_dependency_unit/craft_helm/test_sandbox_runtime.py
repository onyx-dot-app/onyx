"""Render tests for craft.sandboxRuntime (auto, firecracker, pod, off).

"auto" is the default. It must never fail an install or put pods on a
cluster without KVM nodes, and it must render the whole Firecracker stack,
with or without ENABLE_CRAFT, once the chart has a pinned release tag and a
node registration secret."""

import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest
import yaml

from tests.external_dependency_unit.craft_helm.rendering import (
    CHART_DIR,
    helm_template_command,
    render_chart,
    skip_or_fail,
)

_REG_VALUE = "reg-test-0123456789abcdef0123456789"
_NO_CRAFT = ["--set-string", "configMap.ENABLE_CRAFT="]
_REGISTRATION = [
    "--set",
    "auth.sandboxNodeRegistration.enabled=true",
    "--set-string",
    f"auth.sandboxNodeRegistration.values.sandbox_node_registration_secret={_REG_VALUE}",
]
_PINNED = ["--set-string", "global.version=v6.0.0"]
_KVM_SELECTOR = {"onyx.app/workload": "sandbox", "onyx.app/kvm": "true"}


def _docs(stdout: str) -> list[dict[str, Any]]:
    return [d for d in yaml.safe_load_all(stdout) if d]


def _check(result: subprocess.CompletedProcess[str]) -> list[dict[str, Any]]:
    if result.returncode != 0:
        if "missing in charts/" in result.stderr:
            skip_or_fail(f"chart dependencies not built: {result.stderr.strip()}")
        pytest.fail(f"helm template failed: {result.stderr.strip()}")
    return _docs(result.stdout)


def _render(args: list[str]) -> list[dict[str, Any]]:
    return _check(render_chart(args))


def _find(docs: list[dict[str, Any]], kind: str, name: str) -> dict[str, Any] | None:
    return next(
        (d for d in docs if d["kind"] == kind and d["metadata"]["name"] == name),
        None,
    )


def _configmap(docs: list[dict[str, Any]]) -> dict[str, str]:
    cm = _find(docs, "ConfigMap", "env-configmap")
    assert cm is not None
    return cm["data"]


def _agent(docs: list[dict[str, Any]]) -> dict[str, Any] | None:
    return _find(docs, "DaemonSet", "onyx-craft-fc-host-agent")


def _pod_spec(doc: dict[str, Any]) -> dict[str, Any]:
    return doc["spec"]["template"]["spec"]


def _firecracker_parts(docs: list[dict[str, Any]]) -> dict[str, bool]:
    return {
        "host agent": _agent(docs) is not None,
        "sandbox proxy": _find(docs, "Deployment", "onyx-sandbox-proxy") is not None,
        "sandbox namespace": _find(docs, "Namespace", "onyx-sandboxes") is not None,
        "relay TLS": _find(docs, "Secret", "onyx-sandbox-proxy-relay-tls") is not None,
        "egress CA": _find(docs, "Role", "onyx-craft-fc-host-agent-egress-ca-read")
        is not None,
    }


def test_default_install_without_craft_renders_no_firecracker() -> None:
    docs = _render(_NO_CRAFT)
    data = _configmap(docs)

    assert data["SANDBOX_RUNTIME"] == "auto"
    assert "SANDBOX_FC_TEMPLATE" not in data
    assert "SANDBOX_PROXY_HOST" not in data
    assert not any(_firecracker_parts(docs).values())


def test_auto_without_registration_renders_no_firecracker() -> None:
    docs = _render([*_NO_CRAFT, *_PINNED])
    assert not any(_firecracker_parts(docs).values())
    assert "SANDBOX_FC_TEMPLATE" not in _configmap(docs)


@pytest.mark.parametrize("craft", [[], _NO_CRAFT])
def test_auto_with_inputs_renders_firecracker_without_enable_craft(
    craft: list[str],
) -> None:
    docs = _render([*craft, *_PINNED, *_REGISTRATION])
    data = _configmap(docs)
    agent = _agent(docs)
    assert agent is not None
    spec = _pod_spec(agent)

    assert all(_firecracker_parts(docs).values()), _firecracker_parts(docs)
    assert data["SANDBOX_RUNTIME"] == "auto"
    # The root drive tag the chart renders is the template the backend asks for.
    assert data["SANDBOX_FC_TEMPLATE"] == "v6.0.0"
    assert spec["initContainers"][0]["image"] == (
        "onyxdotapp/craft-fc-artifacts:rootfs-v6.0.0"
    )
    assert spec["containers"][0]["image"] == "onyxdotapp/craft-fc-host-agent:v6.0.0"
    assert data["SANDBOX_PROXY_HOST"]
    assert data["ONYX_SERVER_URL"]
    # The api_server gets the agent client certificate.
    api = _find(docs, "Deployment", "onyx-api-server")
    assert api is not None
    env = {e["name"] for e in _pod_spec(api)["containers"][0].get("env", [])}
    assert "SANDBOX_FC_AGENT_CLIENT_CERT_PATH" in env


def test_no_kvm_nodes_means_no_pods_and_no_wait() -> None:
    """Both privileged DaemonSets select onyx.app/kvm=true, so a cluster
    without KVM nodes runs none of their pods. The preflight has no
    readiness probe, so a failed check does not hold `helm --wait`."""
    docs = _render([*_PINNED, *_REGISTRATION])
    agent = _agent(docs)
    preflight = _find(docs, "DaemonSet", "onyx-craft-fc-preflight")
    assert agent is not None and preflight is not None

    assert _pod_spec(agent)["nodeSelector"] == _KVM_SELECTOR
    assert _pod_spec(preflight)["nodeSelector"] == _KVM_SELECTOR
    assert "readinessProbe" not in _pod_spec(preflight)["containers"][0]

    default_preflight = _find(
        _render(_NO_CRAFT), "DaemonSet", "onyx-craft-fc-preflight"
    )
    assert default_preflight is not None
    assert _pod_spec(default_preflight)["nodeSelector"] == _KVM_SELECTOR


def test_dev_twin_version_uses_the_release_tag() -> None:
    docs = _render(["--set-string", "global.version=v6.0.0-dev", *_REGISTRATION])
    agent = _agent(docs)
    assert agent is not None
    assert _pod_spec(agent)["containers"][0]["image"].endswith(":v6.0.0")
    assert _configmap(docs)["SANDBOX_FC_TEMPLATE"] == "v6.0.0"


def test_explicit_tags_win_over_a_floating_version() -> None:
    docs = _render(
        [
            *_REGISTRATION,
            "--set-string",
            "craft.hostAgent.image.tag=0.7.0",
            "--set-string",
            "craft.hostAgent.rootfs.version=0.3.0",
        ]
    )
    agent = _agent(docs)
    assert agent is not None
    spec = _pod_spec(agent)
    assert spec["containers"][0]["image"].endswith(":0.7.0")
    assert spec["initContainers"][0]["image"].endswith(":rootfs-0.3.0")
    assert _configmap(docs)["SANDBOX_FC_TEMPLATE"] == "0.3.0"

    pinned = _configmap(
        _render(
            [
                *_PINNED,
                *_REGISTRATION,
                "--set-string",
                "configMap.SANDBOX_FC_TEMPLATE=custom-template",
            ]
        )
    )
    assert pinned["SANDBOX_FC_TEMPLATE"] == "custom-template"


def test_app_version_is_the_fallback_release_tag(tmp_path: Path) -> None:
    """With global.version unset or floating, a pinned chart appVersion
    gives the image tags."""
    chart = tmp_path / "onyx"
    shutil.copytree(CHART_DIR, chart, symlinks=True)
    chart_yaml = chart / "Chart.yaml"
    text = chart_yaml.read_text()
    assert "\nappVersion: latest\n" in text
    chart_yaml.write_text(
        text.replace("\nappVersion: latest\n", "\nappVersion: v6.1.0\n")
    )

    command = helm_template_command(_REGISTRATION)
    command[command.index(str(CHART_DIR))] = str(chart)
    command[command.index(str(CHART_DIR / "values-ci.yaml"))] = str(
        chart / "values-ci.yaml"
    )
    docs = _check(subprocess.run(command, capture_output=True, text=True))
    agent = _agent(docs)
    assert agent is not None
    assert _pod_spec(agent)["containers"][0]["image"].endswith(":v6.1.0")
    assert _configmap(docs)["SANDBOX_FC_TEMPLATE"] == "v6.1.0"


def test_firecracker_fails_on_a_floating_version() -> None:
    result = render_chart(["--set", "craft.sandboxRuntime=firecracker", *_REGISTRATION])
    assert result.returncode != 0
    assert "pinned" in result.stderr


def test_firecracker_needs_no_enable_craft() -> None:
    docs = _render(
        [
            *_NO_CRAFT,
            *_PINNED,
            *_REGISTRATION,
            "--set",
            "craft.sandboxRuntime=firecracker",
        ]
    )
    assert all(_firecracker_parts(docs).values()), _firecracker_parts(docs)
    assert _configmap(docs)["SANDBOX_RUNTIME"] == "firecracker"


def test_pod_renders_no_firecracker() -> None:
    docs = _render([*_PINNED, *_REGISTRATION, "--set", "craft.sandboxRuntime=pod"])
    parts = _firecracker_parts(docs)
    assert not parts["host agent"] and not parts["relay TLS"]
    # Craft pod sandboxes keep their proxy.
    assert parts["sandbox proxy"]
    assert _configmap(docs)["SANDBOX_RUNTIME"] == "pod"
    assert _find(docs, "DaemonSet", "onyx-craft-fc-preflight") is None


def test_off_renders_no_sandbox_parts() -> None:
    docs = _render(
        [*_NO_CRAFT, *_PINNED, *_REGISTRATION, "--set", "craft.sandboxRuntime=off"]
    )
    assert not any(_firecracker_parts(docs).values())
    assert _find(docs, "DaemonSet", "onyx-craft-fc-preflight") is None
    assert _configmap(docs)["SANDBOX_RUNTIME"] == "off"


def test_off_fails_with_enable_craft() -> None:
    result = render_chart(["--set", "craft.sandboxRuntime=off"])
    assert result.returncode != 0
    assert "craft.sandboxRuntime=off" in result.stderr


def test_auto_acts_as_pod_before_v6() -> None:
    """An Onyx release before v6 rejects SANDBOX_RUNTIME=auto and "off" at
    import, so the chart must not send them."""
    docs = _render(["--set-string", "global.version=v5.1.3", *_REGISTRATION])
    assert _configmap(docs)["SANDBOX_RUNTIME"] == "pod"
    assert _agent(docs) is None

    off = _render(
        [
            *_NO_CRAFT,
            "--set-string",
            "global.version=v5.1.3",
            "--set",
            "craft.sandboxRuntime=off",
        ]
    )
    assert "SANDBOX_RUNTIME" not in _configmap(off)


def test_kvm_toleration_check_only_with_firecracker() -> None:
    """A pod sandbox toleration of every taint is fine until the chart
    renders Firecracker."""
    tolerate_all = ["--set-string", "sandboxPod.tolerations[0].operator=Exists"]
    assert _render(tolerate_all)

    result = render_chart([*tolerate_all, *_PINNED, *_REGISTRATION])
    assert result.returncode != 0
    assert "sandboxPod.tolerations" in result.stderr


@pytest.mark.parametrize("version", ["v5", "5.1", "v5.1.3", "5.1.3-dev"])
def test_short_and_unprefixed_old_tags_act_as_pod(version: str) -> None:
    docs = _render(["--set-string", f"global.version={version}", *_REGISTRATION])
    assert _configmap(docs)["SANDBOX_RUNTIME"] == "pod"


def test_unprefixed_version_uses_the_git_tag_of_the_images() -> None:
    """Releases publish the Firecracker images only under the git tag."""
    docs = _render(["--set-string", "global.version=6.0.0", *_REGISTRATION])
    agent = _agent(docs)
    assert agent is not None
    assert _pod_spec(agent)["containers"][0]["image"].endswith(":v6.0.0")
    assert _configmap(docs)["SANDBOX_FC_TEMPLATE"] == "v6.0.0"


@pytest.mark.parametrize("version", ["6", "v6.1"])
def test_short_v6_tags_float(version: str) -> None:
    docs = _render(["--set-string", f"global.version={version}", *_REGISTRATION])
    assert _agent(docs) is None
    assert _configmap(docs)["SANDBOX_RUNTIME"] == "auto"


def test_registration_existing_secret_needs_the_agent_copy() -> None:
    """auth.sandboxNodeRegistration.existingSecret lives in the release
    namespace; without the agent copy, "auto" stays off instead of failing."""
    reg = [
        "--set",
        "auth.sandboxNodeRegistration.enabled=true",
        "--set-string",
        "auth.sandboxNodeRegistration.existingSecret=reg",
    ]
    assert _agent(_render([*_PINNED, *reg])) is None
    docs = _render(
        [
            *_PINNED,
            *reg,
            "--set-string",
            "craft.hostAgent.registrationExistingSecret=agent-reg",
        ]
    )
    assert _agent(docs) is not None


def test_bundled_store_host_is_the_fqdn_with_firecracker() -> None:
    """The agents upload session saves from their own namespace."""
    store = ["--set", "minio.enabled=true"]
    assert "svc" not in _configmap(_render(store))["S3_ENDPOINT_URL"]
    data = _configmap(_render([*store, *_PINNED, *_REGISTRATION]))
    assert ".onyx.svc." in data["S3_ENDPOINT_URL"]
