"""Pod spec invariants for the Kubernetes sandbox pod.

The pod has one app container — `sandbox` (agent) — plus a native Kubernetes
sidecar implemented as a restartable init container named `sidecar`. They
share a single image with different entrypoints. The asymmetries between them
carry the security model:

  - `sandbox` must not see the push public key or run the push daemon.
  - `sandbox` must not be able to mutate `/workspace/managed/`.
  - PID namespace sharing must be disabled (else /proc leaks the sidecar env).
  - The sidecar must expose the push/snapshot port with health probes.
  - Neither container should receive durable-storage credentials for snapshots.

The static pod shape now lives in the Helm-rendered ``sandbox-pod`` PodTemplate
(templates/sandbox-podtemplate.yaml); `_create_sandbox_pod` reads it and overlays
the per-pod fields. This suite renders that chart template, feeds it through the
overlay (via a mocked ``read_namespaced_pod_template``), and asserts the
invariants on the result — so it verifies the Helm template + Python overlay
end to end. Skips if the ``helm`` binary or chart deps are unavailable.
"""

from __future__ import annotations

import base64
import json
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding
from cryptography.hazmat.primitives.serialization import NoEncryption
from cryptography.hazmat.primitives.serialization import PrivateFormat
from kubernetes import client

import onyx.server.features.build.sandbox.kubernetes.kubernetes_sandbox_manager as ksm
import onyx.server.features.build.sandbox.kubernetes.sidecar_client as sidecar
from onyx.server.features.build.configs import SANDBOX_PROXY_INJECTED_PLACEHOLDER
from onyx.server.features.build.sandbox.image.sandbox_daemon.contract import (
    PUSH_DAEMON_PORT,
)
from onyx.server.features.build.sandbox.image.sandbox_daemon.contract import (
    SIDECAR_HEALTH_PATH,
)
from onyx.server.features.build.sandbox.image.sandbox_daemon.contract import (
    SIDECAR_READY_PATH,
)
from onyx.server.features.build.sandbox.kubernetes.kubernetes_sandbox_manager import (
    KubernetesSandboxManager,
)

# backend/tests/unit/onyx/server/features/build/sandbox/ -> repo root
_REPO_ROOT = Path(__file__).resolve().parents[8]
_CHART_DIR = _REPO_ROOT / "deployment" / "helm" / "charts" / "onyx"
_DEFAULT_KUBE_VERSION_ARGS = ["--kube-version", "1.33.0"]


def _chart_args_with_default_kube_version(
    extra_args: list[str] | None = None,
) -> list[str]:
    if extra_args is not None and "--kube-version" in extra_args:
        return list(extra_args)
    return [*_DEFAULT_KUBE_VERSION_ARGS, *(extra_args or [])]


def _gen_key_b64() -> str:
    seed = Ed25519PrivateKey.generate().private_bytes(
        encoding=Encoding.Raw,
        format=PrivateFormat.Raw,
        encryption_algorithm=NoEncryption(),
    )
    return base64.b64encode(seed).decode()


_TEST_PROXY_IP = "10.255.255.254"


@pytest.fixture(autouse=True)
def _push_key_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sidecar, "SANDBOX_PUSH_PRIVATE_KEY", _gen_key_b64())
    monkeypatch.setattr(sidecar, "_push_private_key", None, raising=False)
    monkeypatch.setattr(sidecar, "_push_public_key_b64", None, raising=False)
    monkeypatch.setattr(ksm, "SANDBOX_PROXY_HOST", "sandbox-proxy.onyx.svc")
    monkeypatch.setattr(
        ksm.KubernetesSandboxManager,
        "_resolve_proxy_ip",
        lambda _self: _TEST_PROXY_IP,
    )


def _render_pod_template_yaml(extra_args: list[str] | None = None) -> str:
    """Render the sandbox-pod PodTemplate from the chart."""
    helm = shutil.which("helm")
    if helm is None:
        pytest.skip("helm binary not available")
    cmd = [
        helm,
        "template",
        "onyx",
        str(_CHART_DIR),
        "-n",
        "onyx",
        "-f",
        str(_CHART_DIR / "values-ci.yaml"),
        *_chart_args_with_default_kube_version(extra_args),
        "--show-only",
        "templates/sandbox-podtemplate.yaml",
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        pytest.skip(f"helm template failed (chart deps?): {result.stderr.strip()}")
    return result.stdout


def _render_chart(
    extra_args: list[str] | None = None,
) -> subprocess.CompletedProcess[str]:
    helm = shutil.which("helm")
    if helm is None:
        pytest.skip("helm binary not available")
    cmd = [
        helm,
        "template",
        "onyx",
        str(_CHART_DIR),
        "-n",
        "onyx",
        "-f",
        str(_CHART_DIR / "values-ci.yaml"),
        *_chart_args_with_default_kube_version(extra_args),
    ]
    return subprocess.run(cmd, capture_output=True, text=True)


def _render_pod_template() -> client.V1PodTemplate:
    """Render the sandbox-pod PodTemplate from the chart and deserialize it
    into the same model the K8s API would return."""
    rendered = yaml.safe_load(_render_pod_template_yaml())

    class _Resp:
        def __init__(self, obj: dict) -> None:
            self.data = json.dumps(obj)

    return client.ApiClient().deserialize(_Resp(rendered), "V1PodTemplate")


def test_sandbox_image_defaults_to_global_version() -> None:
    rendered = yaml.safe_load(
        _render_pod_template_yaml(
            [
                "--set",
                "global.version=v9.8.7",
                "--set-string",
                "configMap.SANDBOX_CONTAINER_IMAGE=",
            ]
        )
    )
    containers = {c["name"]: c for c in rendered["template"]["spec"]["containers"]}
    init_containers = {
        c["name"]: c for c in rendered["template"]["spec"]["initContainers"]
    }
    sandbox = containers["sandbox"]
    sandbox_init = init_containers["sandbox-init"]
    sidecar = init_containers["sidecar"]

    assert sandbox["image"] == "onyxdotapp/sandbox:v9.8.7"
    assert sandbox_init["image"] == "onyxdotapp/sandbox:v9.8.7"
    assert sidecar["image"] == "onyxdotapp/sandbox:v9.8.7"
    assert sandbox["imagePullPolicy"] == "IfNotPresent"
    assert sandbox_init["imagePullPolicy"] == "IfNotPresent"
    assert sidecar["imagePullPolicy"] == "IfNotPresent"


def test_moving_sandbox_image_defaults_to_global_pull_policy() -> None:
    rendered = yaml.safe_load(
        _render_pod_template_yaml(
            [
                "--set",
                "global.version=edge",
                "--set-string",
                "configMap.SANDBOX_CONTAINER_IMAGE=",
            ]
        )
    )
    containers = {c["name"]: c for c in rendered["template"]["spec"]["containers"]}
    init_containers = {
        c["name"]: c for c in rendered["template"]["spec"]["initContainers"]
    }
    sandbox = containers["sandbox"]
    sandbox_init = init_containers["sandbox-init"]
    sidecar = init_containers["sidecar"]

    assert sandbox["image"] == "onyxdotapp/sandbox:edge"
    assert sandbox["imagePullPolicy"] == "IfNotPresent"
    assert sandbox_init["imagePullPolicy"] == "IfNotPresent"
    assert sidecar["imagePullPolicy"] == "IfNotPresent"


def test_internal_sandbox_pull_policy_override_wins() -> None:
    rendered = yaml.safe_load(
        _render_pod_template_yaml(
            [
                "--set",
                "global.version=edge",
                "--set-string",
                "configMap.SANDBOX_CONTAINER_IMAGE=",
                "--set",
                "configMap.SANDBOX_IMAGE_PULL_POLICY=Always",
            ]
        )
    )
    containers = {c["name"]: c for c in rendered["template"]["spec"]["containers"]}
    init_containers = {
        c["name"]: c for c in rendered["template"]["spec"]["initContainers"]
    }
    sandbox = containers["sandbox"]
    sandbox_init = init_containers["sandbox-init"]
    sidecar = init_containers["sidecar"]

    assert sandbox["image"] == "onyxdotapp/sandbox:edge"
    assert sandbox["imagePullPolicy"] == "Always"
    assert sandbox_init["imagePullPolicy"] == "Always"
    assert sidecar["imagePullPolicy"] == "Always"


def test_implicit_latest_sandbox_image_defaults_to_global_pull_policy() -> None:
    rendered = yaml.safe_load(
        _render_pod_template_yaml(
            [
                "--set-string",
                "configMap.SANDBOX_CONTAINER_IMAGE=onyxdotapp/sandbox",
            ]
        )
    )
    containers = {c["name"]: c for c in rendered["template"]["spec"]["containers"]}
    init_containers = {
        c["name"]: c for c in rendered["template"]["spec"]["initContainers"]
    }
    sandbox = containers["sandbox"]
    sandbox_init = init_containers["sandbox-init"]
    sidecar = init_containers["sidecar"]

    assert sandbox["image"] == "onyxdotapp/sandbox"
    assert sandbox["imagePullPolicy"] == "IfNotPresent"
    assert sandbox_init["imagePullPolicy"] == "IfNotPresent"
    assert sidecar["imagePullPolicy"] == "IfNotPresent"


def test_local_dev_sandbox_image_defaults_to_if_not_present() -> None:
    rendered = yaml.safe_load(
        _render_pod_template_yaml(
            [
                "--set-string",
                "configMap.SANDBOX_CONTAINER_IMAGE=onyxdotapp/sandbox:dev",
            ]
        )
    )
    containers = {c["name"]: c for c in rendered["template"]["spec"]["containers"]}
    init_containers = {
        c["name"]: c for c in rendered["template"]["spec"]["initContainers"]
    }
    sandbox = containers["sandbox"]
    sandbox_init = init_containers["sandbox-init"]
    sidecar = init_containers["sidecar"]

    assert sandbox["image"] == "onyxdotapp/sandbox:dev"
    assert sandbox["imagePullPolicy"] == "IfNotPresent"
    assert sandbox_init["imagePullPolicy"] == "IfNotPresent"
    assert sidecar["imagePullPolicy"] == "IfNotPresent"


def test_craft_helm_version_guard_rejects_old_kubernetes() -> None:
    result = _render_chart(
        [
            "--kube-version",
            "1.32.0",
        ]
    )

    assert result.returncode != 0
    assert "Kubernetes >= 1.33" in result.stderr
    assert "v1.32.0" in result.stderr


def test_craft_helm_rejects_docker_sandbox_backend_override() -> None:
    result = _render_chart(
        [
            "--kube-version",
            "1.33.0",
            "--set",
            "configMap.SANDBOX_BACKEND=docker",
        ]
    )

    assert result.returncode != 0
    assert 'configMap.SANDBOX_BACKEND must be "kubernetes"' in result.stderr


def _build_pod() -> client.V1Pod:
    pod_template = _render_pod_template()
    mgr: KubernetesSandboxManager = object.__new__(KubernetesSandboxManager)
    mgr._namespace = "onyx-sandboxes"  # type: ignore[attr-defined]
    mgr._core_api = _FakeCoreApi(pod_template)  # type: ignore[attr-defined]
    return mgr._create_sandbox_pod(  # type: ignore[attr-defined]
        sandbox_id="abc12345-abcd-abcd-abcd-abcdef123456",
        tenant_id="t-1",
    )


class _FakeCoreApi:
    """Returns the rendered PodTemplate from read_namespaced_pod_template."""

    def __init__(self, pod_template: client.V1PodTemplate) -> None:
        self._pod_template = pod_template

    def read_namespaced_pod_template(
        self,
        name: str,  # noqa: ARG002
        namespace: str,  # noqa: ARG002
    ) -> client.V1PodTemplate:
        return self._pod_template


@pytest.fixture
def pod() -> client.V1Pod:
    """A freshly-built pod spec. Each test gets its own — no cross-test state."""
    return _build_pod()


def _container(pod: client.V1Pod, name: str) -> client.V1Container:
    return next(c for c in pod.spec.containers if c.name == name)


def _init_container(pod: client.V1Pod, name: str) -> client.V1Container:
    return next(c for c in pod.spec.init_containers or [] if c.name == name)


def _sidecar(pod: client.V1Pod) -> client.V1Container:
    return _init_container(pod, "sidecar")


def _mount(container: client.V1Container, name: str) -> client.V1VolumeMount:
    return next(m for m in container.volume_mounts if m.name == name)


# ---------------------------------------------------------------------------
# Container topology
# ---------------------------------------------------------------------------


def test_pod_has_sandbox_app_container_and_native_init_sidecar(
    pod: client.V1Pod,
) -> None:
    """Same image, different commands — the asymmetry that turns one image
    into two roles."""
    app_by_name = {c.name: c for c in pod.spec.containers}
    init_by_name = {c.name: c for c in pod.spec.init_containers or []}

    assert set(app_by_name) == {"sandbox"}
    assert list(init_by_name) == ["sandbox-init", "sidecar"]
    assert app_by_name["sandbox"].image == init_by_name["sidecar"].image
    assert app_by_name["sandbox"].command != init_by_name["sidecar"].command
    assert app_by_name["sandbox"].command == ["/workspace/entrypoint.sh"]
    assert init_by_name["sidecar"].command == ["/workspace/sidecar-entrypoint.sh"]
    assert init_by_name["sidecar"].restart_policy == "Always"
    assert pod.spec.restart_policy == "Never"


# ---------------------------------------------------------------------------
# Push daemon / snapshot API placement (sidecar only)
# ---------------------------------------------------------------------------


def test_push_daemon_port_is_declared_on_sidecar_only(pod: client.V1Pod) -> None:
    sandbox_ports = {p.container_port for p in _container(pod, "sandbox").ports}
    sidecar_ports = {p.container_port for p in _sidecar(pod).ports}
    assert PUSH_DAEMON_PORT in sidecar_ports
    assert PUSH_DAEMON_PORT not in sandbox_ports


def test_push_public_key_is_in_sidecar_env_only(pod: client.V1Pod) -> None:
    """The push public key gates writes to /workspace/managed.

    Leaking it into the sandbox container would let the agent process
    enumerate it via /proc/self/environ — not a credential by itself,
    but unnecessary surface.
    """
    sandbox_env = {e.name for e in _container(pod, "sandbox").env}
    sidecar_env = {e.name for e in _sidecar(pod).env}
    assert "ONYX_SANDBOX_PUSH_PUBLIC_KEY" in sidecar_env
    assert "ONYX_SANDBOX_PUSH_PUBLIC_KEY" not in sandbox_env


def test_sidecar_probes_target_the_daemon_port(pod: client.V1Pod) -> None:
    sidecar = _sidecar(pod)
    assert sidecar.liveness_probe is not None
    assert sidecar.liveness_probe.http_get.path == SIDECAR_HEALTH_PATH
    assert sidecar.liveness_probe.http_get.port == PUSH_DAEMON_PORT

    assert sidecar.startup_probe is not None
    assert sidecar.startup_probe.http_get.path == SIDECAR_READY_PATH
    assert sidecar.startup_probe.http_get.port == PUSH_DAEMON_PORT

    assert sidecar.readiness_probe is not None
    assert sidecar.readiness_probe.http_get.path == SIDECAR_HEALTH_PATH
    assert sidecar.readiness_probe.http_get.port == PUSH_DAEMON_PORT


# ---------------------------------------------------------------------------
# Volume access model: sidecar owns managed/, agent is read-only
# ---------------------------------------------------------------------------


def test_managed_volume_is_writable_only_from_sidecar(pod: client.V1Pod) -> None:
    """The sidecar receives pushed files and writes them to /workspace/managed.
    The agent reads from there but must not be able to tamper with files
    after extraction — so it mounts the same volume read-only.
    """
    sandbox_mount = _mount(_container(pod, "sandbox"), "managed")
    sidecar_mount = _mount(_sidecar(pod), "managed")
    assert sandbox_mount.read_only is True
    # K8s treats None and False equivalently for volume mounts.
    assert not sidecar_mount.read_only
    assert sandbox_mount.mount_path == sidecar_mount.mount_path == "/workspace/managed"


def test_workspace_volume_is_shared_for_session_io(pod: client.V1Pod) -> None:
    """Both containers must reach /workspace/sessions: the agent to do its
    work, the sidecar to tar/untar snapshots.
    """
    volume_names = {v.name for v in pod.spec.volumes}
    assert volume_names == {
        "workspace",
        "opencode-data",
        "managed",
        "tmp",
        "sidecar-tmp",
        "sandbox-ca-source",
        "sandbox-ca-bundle",
    }
    for container in (_container(pod, "sandbox"), _sidecar(pod)):
        mount = _mount(container, "workspace")
        assert mount.mount_path == "/workspace/sessions"
        assert not mount.read_only


def test_tmp_volumes_are_writable_and_isolated_by_container(
    pod: client.V1Pod,
) -> None:
    """Agents need /tmp for scratch files. The sidecar also uses /tmp while
    restoring snapshot archives, but it must not share that scratch space with
    the agent after archive checksum verification.
    """
    assert pod.spec.security_context.fs_group == 1000

    volumes = {v.name: v for v in pod.spec.volumes}
    assert volumes["tmp"].empty_dir.size_limit == "5Gi"
    assert volumes["sidecar-tmp"].empty_dir.size_limit == "5Gi"

    sandbox_tmp = _mount(_container(pod, "sandbox"), "tmp")
    sidecar_tmp = _mount(_sidecar(pod), "sidecar-tmp")
    assert sandbox_tmp.mount_path == sidecar_tmp.mount_path == "/tmp"
    assert not sandbox_tmp.read_only
    assert not sidecar_tmp.read_only

    sandbox_mount_names = {m.name for m in _container(pod, "sandbox").volume_mounts}
    sidecar_mount_names = {m.name for m in _sidecar(pod).volume_mounts}
    assert "sidecar-tmp" not in sandbox_mount_names
    assert "tmp" not in sidecar_mount_names


def test_opencode_data_volume_is_shared_outside_session_tree(
    pod: client.V1Pod,
) -> None:
    """Opencode's sandbox-global data must not live under /workspace/sessions,
    which is the user/session workspace tree.
    """
    env = {e.name: e.value for e in _container(pod, "sandbox").env}
    assert env["OPENCODE_DATA_HOME"] == "/workspace/opencode-data"

    volume = next(v for v in pod.spec.volumes if v.name == "opencode-data")
    assert volume.empty_dir.size_limit == "5Gi"

    for container in (_container(pod, "sandbox"), _sidecar(pod)):
        mount = _mount(container, "opencode-data")
        assert mount.mount_path == "/workspace/opencode-data"
        assert not mount.read_only


# ---------------------------------------------------------------------------
# Process isolation
# ---------------------------------------------------------------------------


def test_share_process_namespace_is_disabled(pod: client.V1Pod) -> None:
    """PID-sharing would expose sidecar process state via /proc to the agent.
    Pin explicitly False (not just None / unset)."""
    assert pod.spec.share_process_namespace is False


def test_service_account_token_automount_is_disabled(pod: client.V1Pod) -> None:
    """The sandbox pod never needs the Kubernetes API token mounted."""
    assert pod.spec.automount_service_account_token is False


# ---------------------------------------------------------------------------
# Credential rip-out: the real PAT never lives in the pod
# ---------------------------------------------------------------------------


def test_onyx_pat_env_is_placeholder_not_real(pod: client.V1Pod) -> None:
    """The pod ships a placeholder; the egress proxy injects the real PAT."""
    env = {e.name: e.value for e in _container(pod, "sandbox").env}
    assert env["ONYX_PAT"] == SANDBOX_PROXY_INJECTED_PLACEHOLDER


def test_no_proxy_is_loopback_only(pod: client.V1Pod) -> None:
    """Only loopback may bypass the proxy; the Onyx API host must route through
    it so the PAT can be injected on the wire."""
    env = {e.name: e.value for e in _container(pod, "sandbox").env}
    assert set(env["NO_PROXY"].split(",")) == {"127.0.0.1", "localhost"}
    assert env["no_proxy"] == env["NO_PROXY"]


# ---------------------------------------------------------------------------
# Egress proxy wiring on the built pod (mandatory — no direct-egress path)
# ---------------------------------------------------------------------------


_PROXY_ENV_NAMES = {
    "HTTP_PROXY",
    "HTTPS_PROXY",
    "http_proxy",
    "https_proxy",
    "NO_PROXY",
    "no_proxy",
}


def test_proxy_env_is_set_on_sandbox_and_sidecar(pod: client.V1Pod) -> None:
    """Both containers' outbound traffic must be routed through the proxy —
    sandbox for the agent and sidecar for control-plane callbacks."""
    containers = {
        "sandbox": _container(pod, "sandbox"),
        "sidecar": _sidecar(pod),
    }
    for name, container in containers.items():
        env = {e.name for e in container.env}
        assert _PROXY_ENV_NAMES.issubset(env), (
            f"{name} container missing proxy env: {_PROXY_ENV_NAMES - env}"
        )


def test_snapshot_storage_credentials_are_not_in_pod_env(pod: client.V1Pod) -> None:
    """Snapshots stream to api-server-owned FileStore persistence, so sandbox
    pods do not need bucket names, endpoints, or AWS credentials."""
    forbidden = {
        "SANDBOX_S3_BUCKET",
        "S3_ENDPOINT_URL",
        "AWS_ENDPOINT_URL",
        "AWS_ACCESS_KEY_ID",
        "AWS_SECRET_ACCESS_KEY",
        "S3_AWS_ACCESS_KEY_ID",
        "S3_AWS_SECRET_ACCESS_KEY",
    }
    containers = {
        "sandbox": _container(pod, "sandbox"),
        "sidecar": _sidecar(pod),
    }
    for name, container in containers.items():
        env = {e.name for e in container.env}
        assert env.isdisjoint(forbidden), (
            f"{name} leaked storage env: {env & forbidden}"
        )


def test_all_containers_set_ephemeral_storage_requests(pod: client.V1Pod) -> None:
    """A pod with no ephemeral-storage request is invisible to the scheduler's
    disk accounting and first in line for kubelet eviction under node disk
    pressure — the exact failure that loses un-snapshotted workspaces."""
    for container in (_container(pod, "sandbox"), _sidecar(pod)):
        resources = container.resources
        assert "ephemeral-storage" in (resources.requests or {}), (
            f"{container.name} container missing ephemeral-storage request"
        )
        assert "ephemeral-storage" in (resources.limits or {}), (
            f"{container.name} container missing ephemeral-storage limit"
        )


def test_init_containers_preserve_proxy_then_sidecar_order(pod: client.V1Pod) -> None:
    """The iptables-lockdown initContainer must run before any user code —
    it's what blocks direct egress that the HTTPS_PROXY env doesn't catch."""
    init_names = [c.name for c in (pod.spec.init_containers or [])]
    assert init_names == ["sandbox-init", "sidecar"]
    assert _init_container(pod, "sandbox-init").restart_policy is None
    assert _sidecar(pod).restart_policy == "Always"


def test_sidecar_restart_policy_serializes_for_kubernetes_api(
    pod: client.V1Pod,
) -> None:
    serialized = client.ApiClient().sanitize_for_serialization(pod)
    init_containers = serialized["spec"]["initContainers"]
    sidecar = next(c for c in init_containers if c["name"] == "sidecar")
    sandbox_init = next(c for c in init_containers if c["name"] == "sandbox-init")

    assert sidecar["restartPolicy"] == "Always"
    assert "restartPolicy" not in sandbox_init


def test_host_aliases_pin_proxy(pod: client.V1Pod) -> None:
    """The iptables rules block DNS, so the proxy hostname must be resolved
    via pod hostAliases."""
    assert pod.spec.host_aliases is not None
    aliases = {ha.ip: ha.hostnames for ha in pod.spec.host_aliases}
    assert aliases == {_TEST_PROXY_IP: ["sandbox-proxy"]}


def test_ca_bundle_mounted_read_only_on_both_containers(pod: client.V1Pod) -> None:
    """The proxy terminates TLS with its own CA, so every container that
    makes HTTPS calls must mount the CA bundle. Read-only — the bundle is
    populated by the initContainer and must not be writable by the agent."""
    for container in (_container(pod, "sandbox"), _sidecar(pod)):
        mount = _mount(container, "sandbox-ca-bundle")
        assert mount.read_only is True
        assert mount.mount_path == "/etc/ssl/sandbox"


def test_missing_container_raises_clear_error_on_version_skew() -> None:
    """A chart/api-server version skew (template missing an expected container)
    must surface as an actionable RuntimeError, not an opaque StopIteration."""
    spec = client.V1PodSpec(containers=[client.V1Container(name="sandbox")])
    with pytest.raises(RuntimeError, match="sidecar"):
        KubernetesSandboxManager._require_container(spec, "sidecar")


def test_service_exposes_push_daemon_port() -> None:
    """push/snapshot/health reach the pod via the Service FQDN, so the
    push-daemon port must be exposed on the Service, not just the pod."""
    mgr: KubernetesSandboxManager = object.__new__(KubernetesSandboxManager)
    mgr._namespace = "onyx-sandboxes"  # type: ignore[attr-defined]
    svc = mgr._create_sandbox_service(  # type: ignore[attr-defined]
        sandbox_id="abc12345-abcd-abcd-abcd-abcdef123456",
        tenant_id="t-1",
    )
    assert PUSH_DAEMON_PORT in {p.port for p in svc.spec.ports}
