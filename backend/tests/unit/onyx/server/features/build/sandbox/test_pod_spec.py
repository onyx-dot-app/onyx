"""Pod spec invariants for the two-container sandbox.

The pod has two containers — `sandbox` (agent) and `sidecar` (control plane) —
sharing a single image with different entrypoints. The asymmetries between
them carry the security model:

  - `sandbox` must not see the push public key or run the push daemon.
  - `sandbox` must not be able to mutate `/workspace/managed/`.
  - PID namespace sharing must be disabled (else /proc leaks the sidecar env).
  - The sidecar must expose the push/snapshot port with health probes.

Pure logic — bypasses `_initialize` so no cluster is needed.
"""

from __future__ import annotations

import base64

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding
from cryptography.hazmat.primitives.serialization import NoEncryption
from cryptography.hazmat.primitives.serialization import PrivateFormat
from kubernetes import client

import onyx.server.features.build.sandbox.kubernetes.kubernetes_sandbox_manager as ksm
from onyx.server.features.build.sandbox.kubernetes.kubernetes_sandbox_manager import (
    KubernetesSandboxManager,
)
from onyx.server.features.build.sandbox.kubernetes.kubernetes_sandbox_manager import (
    PUSH_DAEMON_PORT,
)


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
    monkeypatch.setenv("ONYX_SANDBOX_PUSH_PRIVATE_KEY", _gen_key_b64())
    monkeypatch.setattr(ksm, "_push_private_key", None, raising=False)
    monkeypatch.setattr(ksm, "_push_public_key_b64", None, raising=False)
    monkeypatch.setattr(ksm, "SANDBOX_PROXY_HOST", "sandbox-proxy.onyx.svc")
    monkeypatch.setattr(
        ksm.KubernetesSandboxManager,
        "_resolve_proxy_ip",
        lambda _self: _TEST_PROXY_IP,
    )


def _build_pod() -> client.V1Pod:
    mgr: KubernetesSandboxManager = object.__new__(KubernetesSandboxManager)
    mgr._namespace = "onyx-sandboxes"  # type: ignore[attr-defined]
    mgr._image = "onyxdotapp/sandbox:test"  # type: ignore[attr-defined]
    mgr._service_account = "sandbox-file-sync"  # type: ignore[attr-defined]
    mgr._s3_bucket = "test-bucket"  # type: ignore[attr-defined]
    return mgr._create_sandbox_pod(  # type: ignore[attr-defined]
        sandbox_id="abc12345-abcd-abcd-abcd-abcdef123456",
        tenant_id="t-1",
    )


@pytest.fixture
def pod() -> client.V1Pod:
    """A freshly-built pod spec. Each test gets its own — no cross-test state."""
    return _build_pod()


def _container(pod: client.V1Pod, name: str) -> client.V1Container:
    return next(c for c in pod.spec.containers if c.name == name)


def _mount(container: client.V1Container, name: str) -> client.V1VolumeMount:
    return next(m for m in container.volume_mounts if m.name == name)


# ---------------------------------------------------------------------------
# Container topology
# ---------------------------------------------------------------------------


def test_pod_has_sandbox_and_sidecar_with_distinct_entrypoints(
    pod: client.V1Pod,
) -> None:
    """Same image, different commands — the asymmetry that turns one image
    into two roles."""
    by_name = {c.name: c for c in pod.spec.containers}
    assert set(by_name) == {"sandbox", "sidecar"}
    assert by_name["sandbox"].image == by_name["sidecar"].image
    assert by_name["sandbox"].command != by_name["sidecar"].command
    assert by_name["sandbox"].command == ["/workspace/entrypoint.sh"]
    assert by_name["sidecar"].command == ["/workspace/sidecar-entrypoint.sh"]


# ---------------------------------------------------------------------------
# Push daemon / snapshot API placement (sidecar only)
# ---------------------------------------------------------------------------


def test_push_daemon_port_is_declared_on_sidecar_only(pod: client.V1Pod) -> None:
    sandbox_ports = {p.container_port for p in _container(pod, "sandbox").ports}
    sidecar_ports = {p.container_port for p in _container(pod, "sidecar").ports}
    assert PUSH_DAEMON_PORT in sidecar_ports
    assert PUSH_DAEMON_PORT not in sandbox_ports


def test_push_public_key_is_in_sidecar_env_only(pod: client.V1Pod) -> None:
    """The push public key gates writes to /workspace/managed.

    Leaking it into the sandbox container would let the agent process
    enumerate it via /proc/self/environ — not a credential by itself,
    but unnecessary surface.
    """
    sandbox_env = {e.name for e in _container(pod, "sandbox").env}
    sidecar_env = {e.name for e in _container(pod, "sidecar").env}
    assert "ONYX_SANDBOX_PUSH_PUBLIC_KEY" in sidecar_env
    assert "ONYX_SANDBOX_PUSH_PUBLIC_KEY" not in sandbox_env


def test_sidecar_health_probes_target_the_daemon_port(pod: client.V1Pod) -> None:
    sidecar = _container(pod, "sidecar")
    for probe in (sidecar.liveness_probe, sidecar.readiness_probe):
        assert probe is not None
        assert probe.http_get.path == "/health"
        assert probe.http_get.port == PUSH_DAEMON_PORT


# ---------------------------------------------------------------------------
# Volume access model: sidecar owns managed/, agent is read-only
# ---------------------------------------------------------------------------


def test_managed_volume_is_writable_only_from_sidecar(pod: client.V1Pod) -> None:
    """The sidecar receives pushed files and writes them to /workspace/managed.
    The agent reads from there but must not be able to tamper with files
    after extraction — so it mounts the same volume read-only.
    """
    sandbox_mount = _mount(_container(pod, "sandbox"), "managed")
    sidecar_mount = _mount(_container(pod, "sidecar"), "managed")
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
        "managed",
        "sandbox-ca-source",
        "sandbox-ca-bundle",
    }
    for name in ("sandbox", "sidecar"):
        mount = _mount(_container(pod, name), "workspace")
        assert mount.mount_path == "/workspace/sessions"
        assert not mount.read_only


# ---------------------------------------------------------------------------
# Process isolation
# ---------------------------------------------------------------------------


def test_share_process_namespace_is_disabled(pod: client.V1Pod) -> None:
    """PID-sharing would expose the sidecar's IRSA env via /proc to the
    agent. Pin explicitly False (not just None / unset)."""
    assert pod.spec.share_process_namespace is False


# ---------------------------------------------------------------------------
# Credential rip-out: the real PAT never lives in the pod
# ---------------------------------------------------------------------------


def test_onyx_pat_env_is_placeholder_not_real(pod: client.V1Pod) -> None:
    """The pod ships a placeholder; the egress proxy injects the real PAT."""
    env = {e.name: e.value for e in _container(pod, "sandbox").env}
    assert env["ONYX_PAT"] == ksm._PROXY_INJECTED_PLACEHOLDER


def test_no_proxy_is_loopback_only() -> None:
    """Only loopback may bypass the proxy; the Onyx API host must route through
    it so the PAT can be injected on the wire."""
    env = {e.name: e.value for e in ksm._proxy_main_container_env_vars()}
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
    sandbox for the agent, sidecar for `aws s3` (the pod-wide iptables
    lockdown blocks direct egress for either)."""
    for name in ("sandbox", "sidecar"):
        env = {e.name for e in _container(pod, name).env}
        assert _PROXY_ENV_NAMES.issubset(env), (
            f"{name} container missing proxy env: {_PROXY_ENV_NAMES - env}"
        )


def test_proxy_init_container_present(pod: client.V1Pod) -> None:
    """The iptables-lockdown initContainer must run before any user code —
    it's what blocks direct egress that the HTTPS_PROXY env doesn't catch."""
    init_names = [c.name for c in (pod.spec.init_containers or [])]
    assert init_names == ["sandbox-init"]


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
    for name in ("sandbox", "sidecar"):
        mount = _mount(_container(pod, name), "sandbox-ca-bundle")
        assert mount.read_only is True
        assert mount.mount_path == "/etc/ssl/sandbox"


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
