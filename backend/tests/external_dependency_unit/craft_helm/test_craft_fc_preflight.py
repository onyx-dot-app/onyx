"""Render tests for the opt-in Craft Firecracker node preflight DaemonSet.

The preflight is only useful if it lands on the sandbox nodes, sees the host
/dev/kvm, and checks the host directory that will hold sandbox data. None of
those mistakes fail at runtime: the pod still prints a log, just for the wrong
node or the wrong filesystem."""

import os
import subprocess
from pathlib import Path
from typing import Any

import pytest
import yaml

from tests.external_dependency_unit.craft_helm.rendering import (
    CHART_DIR,
    render_chart,
    skip_or_fail,
)

_TEMPLATE = "templates/craft-fc-preflight.yaml"
_PODTEMPLATE_TEMPLATE = "templates/sandbox-podtemplate.yaml"
_ENABLED = ["--set", "craft.firecrackerPreflight.enabled=true"]
_SCRIPT = CHART_DIR / "scripts" / "craft-fc-preflight.sh"


def _render(extra_args: list[str], template: str = _TEMPLATE) -> list[dict[str, Any]]:
    """Rendered documents, or [] when the template renders nothing."""
    result = render_chart([*extra_args, "--show-only", template])
    if result.returncode != 0:
        # --show-only on an empty template is a helm error, not empty output.
        if "could not find template" in result.stderr:
            return []
        if "missing in charts/" in result.stderr:
            skip_or_fail(f"chart dependencies not built: {result.stderr.strip()}")
        pytest.fail(f"helm template failed: {result.stderr.strip()}")
    return [d for d in yaml.safe_load_all(result.stdout) if d]


def _by_kind(docs: list[dict[str, Any]], kind: str) -> dict[str, Any]:
    return next(d for d in docs if d["kind"] == kind)


def _pod_spec(extra_args: list[str] | None = None) -> dict[str, Any]:
    docs = _render([*_ENABLED, *(extra_args or [])])
    return _by_kind(docs, "DaemonSet")["spec"]["template"]["spec"]


def test_preflight_renders_nothing_by_default() -> None:
    assert _render([]) == []


def test_preflight_schedules_like_sandbox_pods_without_runtime_class() -> None:
    """Same nodes as the sandboxes, but never the sandbox RuntimeClass: gVisor
    and Kata hide the host /dev/kvm, so every check would read the wrong
    kernel."""
    args = ["--set-string", "sandboxPod.runtimeClassName=gvisor"]
    preflight = _pod_spec(args)
    sandbox = _render(args, _PODTEMPLATE_TEMPLATE)[0]["template"]["spec"]

    assert preflight["nodeSelector"] == {"onyx.app/workload": "sandbox"}
    assert preflight["nodeSelector"] == sandbox["nodeSelector"]
    # Also the Firecracker nodes, which Terraform taints onyx.app/kvm.
    assert preflight["tolerations"] == [
        *sandbox["tolerations"],
        {
            "key": "onyx.app/kvm",
            "operator": "Equal",
            "value": "true",
            "effect": "NoSchedule",
        },
    ]
    assert "runtimeClassName" not in preflight


def test_preflight_mounts_script_and_scratch_host_path() -> None:
    args = [
        "--set-string",
        "craft.firecrackerPreflight.scratchHostPath=/data/onyx-preflight",
    ]
    spec = _pod_spec(args)
    container = spec["containers"][0]
    mounts = {m["name"]: m for m in container["volumeMounts"]}
    volumes = {v["name"]: v for v in spec["volumes"]}

    assert mounts["script"]["readOnly"] is True
    assert mounts["scratch"]["mountPath"] == "/scratch"
    assert volumes["scratch"]["hostPath"] == {
        "path": "/data/onyx-preflight",
        "type": "DirectoryOrCreate",
    }
    # The only host mount: CPU, kernel, sysctl and cgroup data are visible
    # from inside the container.
    assert [v for v in spec["volumes"] if "hostPath" in v] == [volumes["scratch"]]
    env = {e["name"]: e.get("value") for e in container["env"]}
    assert env["SCRATCH_DIR"] == "/scratch"
    assert env["SCRATCH_HOST_PATH"] == "/data/onyx-preflight"


def test_preflight_script_comes_from_the_chart_file() -> None:
    docs = _render(_ENABLED)
    script = _by_kind(docs, "ConfigMap")["data"]["craft-fc-preflight.sh"]
    assert script.startswith("#!/bin/sh")
    assert "RESULT:" in script
    volume = next(v for v in _pod_spec()["volumes"] if v["name"] == "script")
    assert (
        volume["configMap"]["name"] == _by_kind(docs, "ConfigMap")["metadata"]["name"]
    )


def test_preflight_is_privileged_without_a_kvm_device_plugin() -> None:
    """runc's device cgroup denies /dev/kvm to a non-privileged container."""
    security = _pod_spec()["containers"][0]["securityContext"]
    assert security["privileged"] is True
    assert security["readOnlyRootFilesystem"] is True


def test_preflight_drops_privilege_with_a_kvm_device_plugin() -> None:
    resource = "devices.kubevirt.io/kvm"
    container = _pod_spec(
        ["--set-string", f"craft.firecrackerPreflight.kvmDeviceResource={resource}"]
    )["containers"][0]
    security = container["securityContext"]

    assert security["privileged"] is False
    assert security["allowPrivilegeEscalation"] is False
    assert security["capabilities"] == {"drop": ["ALL"]}
    assert container["resources"]["limits"][resource] == "1"
    assert container["resources"]["requests"][resource] == "1"


def test_preflight_does_not_need_craft_enabled() -> None:
    """Operators check nodes before they turn Craft on."""
    docs = _render([*_ENABLED, "--set-string", "configMap.ENABLE_CRAFT=false"])
    assert _by_kind(docs, "DaemonSet")


def test_preflight_carries_a_deny_all_network_policy() -> None:
    docs = _render(_ENABLED)
    policy = _by_kind(docs, "NetworkPolicy")
    pod_labels = _by_kind(docs, "DaemonSet")["spec"]["template"]["metadata"]["labels"]

    assert set(policy["spec"]["policyTypes"]) == {"Ingress", "Egress"}
    assert "ingress" not in policy["spec"]
    assert "egress" not in policy["spec"]
    assert policy["spec"]["podSelector"]["matchLabels"].items() <= pod_labels.items()
    # Not `component: sandbox`, so the sandbox NetworkPolicies do not select it.
    assert pod_labels["app.kubernetes.io/component"] == "craft-fc-preflight"


def test_preflight_has_no_service_account_token() -> None:
    assert _pod_spec()["automountServiceAccountToken"] is False


def test_preflight_checks_the_agent_data_dir_by_default() -> None:
    env = {
        e["name"]: e.get("value")
        for e in _pod_spec(["--set-string", "craft.hostAgent.dataDir=/data/fc"])[
            "containers"
        ][0]["env"]
    }
    assert env["SCRATCH_HOST_PATH"] == "/data/fc"
    default_env = {
        e["name"]: e.get("value") for e in _pod_spec()["containers"][0]["env"]
    }
    assert default_env["SCRATCH_HOST_PATH"] == "/var/lib/craft-fc"


def _filesystem_line(tmp_path: Path, reflink: bool) -> str:
    """Runs the chart's preflight script with stub stat and cp, and returns its
    filesystem line."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    scratch = tmp_path / "scratch"
    scratch.mkdir()
    stubs = {
        "stat": "#!/bin/sh\necho ext2/ext3\n",
        "cp": (
            "#!/bin/sh\nexit 0\n"
            if reflink
            else "#!/bin/sh\necho 'cp: failed to clone: Operation not supported' >&2\nexit 1\n"
        ),
    }
    for name, body in stubs.items():
        stub = bin_dir / name
        stub.write_text(body)
        stub.chmod(0o755)
    result = subprocess.run(
        ["sh", str(_SCRIPT)],
        capture_output=True,
        text=True,
        env={
            "PATH": f"{bin_dir}:{os.environ['PATH']}",
            "SCRATCH_DIR": str(scratch),
            "SCRATCH_HOST_PATH": "/var/lib/craft-fc",
        },
    )
    return next(line for line in result.stdout.splitlines() if " filesystem: " in line)


def test_preflight_warns_without_reflink(tmp_path: Path) -> None:
    """The agent makes a loop store on ext4, so no reflink is a WARN, not a FAIL."""
    line = _filesystem_line(tmp_path, reflink=False)
    assert line.startswith("WARN  filesystem:")
    assert "'ext2/ext3' without reflink" in line
    assert ".craft-fc-store.img" in line


def test_preflight_passes_with_reflink(tmp_path: Path) -> None:
    line = _filesystem_line(tmp_path, reflink=True)
    assert line == "PASS  filesystem: /var/lib/craft-fc is ext2/ext3 with reflink"
