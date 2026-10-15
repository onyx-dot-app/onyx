"""Runtime selection in the rendered sandbox resources."""

from pathlib import Path
from typing import Any

import pytest
import yaml

from onyx.server.features.build.sandbox.image.guest import PROTOCOL_VERSION
from onyx.server.features.build.sandbox.labels import LABEL_SANDBOX_PROTOCOL
from tests.external_dependency_unit.craft_helm.rendering import render_chart


def _sandbox_specs(extra_args: list[str]) -> list[dict[str, Any]]:
    result = render_chart(extra_args)
    assert result.returncode == 0, result.stderr
    resources: list[dict[str, Any]] = [
        resource for resource in yaml.safe_load_all(result.stdout) if resource
    ]
    return [
        resource["template"]["spec"]
        if resource["kind"] == "PodTemplate"
        else resource["spec"]["template"]["spec"]
        for resource in resources
        if resource["kind"] in {"PodTemplate", "DaemonSet"}
        and resource["metadata"]["name"]
        in {"sandbox-pod", "onyx-sandbox-image-prepuller"}
    ]


@pytest.mark.parametrize("runtime_class", ["", "kata-fc"])
def test_sandbox_and_prepuller_use_the_same_runtime(runtime_class: str) -> None:
    specs = _sandbox_specs(
        ["--set-string", f"sandboxPod.runtimeClassName={runtime_class}"]
    )
    assert len(specs) == 2
    for spec in specs:
        assert spec["runtimeClassName"] == "kata-fc"


def test_default_runtime_is_firecracker_for_sandbox_and_prepuller() -> None:
    specs = _sandbox_specs([])
    assert len(specs) == 2
    for spec in specs:
        assert spec["runtimeClassName"] == "kata-fc"
        assert spec["nodeSelector"]["onyx.app/workload"] == "sandbox"


def test_sandbox_template_declares_the_guest_protocol() -> None:
    result = render_chart([])
    assert result.returncode == 0, result.stderr
    template = next(
        resource
        for resource in yaml.safe_load_all(result.stdout)
        if resource
        and resource["kind"] == "PodTemplate"
        and resource["metadata"]["name"] == "sandbox-pod"
    )

    assert template["template"]["metadata"]["labels"][LABEL_SANDBOX_PROTOCOL] == str(
        PROTOCOL_VERSION
    )


@pytest.mark.parametrize(
    "runtime_class", ["runc", "kata", "kata-qemu", "kata-fc-custom"]
)
def test_non_firecracker_runtime_is_rejected(runtime_class: str) -> None:
    result = render_chart(
        ["--set-string", f"sandboxPod.runtimeClassName={runtime_class}"]
    )
    assert result.returncode != 0
    assert (
        "sandboxPod.runtimeClassName must be kata-fc; Craft requires Firecracker"
        in result.stderr
    )


@pytest.mark.parametrize("runtime", [None, "", "kubernetes_firecracker"])
def test_kubernetes_launcher_is_accepted(runtime: str | None) -> None:
    args = (
        ["--set-string", f"configMap.CRAFT_SANDBOX_RUNTIME={runtime}"]
        if runtime is not None
        else ["--set", "configMap.CRAFT_SANDBOX_RUNTIME=null"]
    )
    result = render_chart(args)
    assert result.returncode == 0, result.stderr
    config_map = next(
        resource
        for resource in yaml.safe_load_all(result.stdout)
        if resource
        and resource["kind"] == "ConfigMap"
        and resource["metadata"]["name"] == "env-configmap"
    )
    assert config_map["data"].get("CRAFT_SANDBOX_RUNTIME") == (runtime or None)


@pytest.mark.parametrize(
    "runtime",
    ["docker_firecracker", "legacy", "kubernetes", "KUBERNETES_FIRECRACKER"],
)
def test_unsupported_launcher_is_rejected(runtime: str) -> None:
    result = render_chart(
        ["--set-string", f"configMap.CRAFT_SANDBOX_RUNTIME={runtime}"]
    )
    assert result.returncode != 0
    assert "configMap.CRAFT_SANDBOX_RUNTIME must be kubernetes_firecracker" in (
        result.stderr
    )


@pytest.mark.parametrize("version", ["1.25.0", "1.29.0", "1.29.15-gke.123"])
def test_kubernetes_without_default_v5_exec_is_rejected(version: str) -> None:
    result = render_chart(["--kube-version", version])
    assert result.returncode != 0
    assert "requires Kubernetes >= 1.30" in result.stderr


@pytest.mark.parametrize("version", ["1.30.0", "1.33.0", "1.30.2-eks-abcdef"])
def test_kubernetes_with_default_v5_exec_is_accepted(version: str) -> None:
    assert len(_sandbox_specs(["--kube-version", version])) == 2


@pytest.mark.parametrize("runtime", ["kubernetes_firecracker", "docker_firecracker"])
def test_runtime_does_not_enable_disabled_craft(tmp_path: Path, runtime: str) -> None:
    existing = tmp_path / "existing.yaml"
    existing.write_text('configMap:\n  ENABLE_CRAFT: "false"\n')
    assert not _sandbox_specs(
        [
            "-f",
            str(existing),
            "--set-string",
            f"configMap.CRAFT_SANDBOX_RUNTIME={runtime}",
            "--kube-version",
            "1.25.0",
        ]
    )


def test_runtime_preserves_existing_node_selector(tmp_path: Path) -> None:
    existing = tmp_path / "existing.yaml"
    existing.write_text(
        "sandboxPod:\n  nodeSelector:\n    onyx.app/workload: craft-test\n"
    )
    specs = _sandbox_specs(["-f", str(existing)])
    assert len(specs) == 2
    for spec in specs:
        assert spec["nodeSelector"]["onyx.app/workload"] == "craft-test"
