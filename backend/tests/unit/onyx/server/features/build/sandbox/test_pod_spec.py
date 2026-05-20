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


@pytest.fixture(autouse=True)
def _push_key_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ONYX_SANDBOX_PUSH_PRIVATE_KEY", _gen_key_b64())
    monkeypatch.setattr(ksm, "_push_private_key", None, raising=False)
    monkeypatch.setattr(ksm, "_push_public_key_b64", None, raising=False)


@pytest.fixture
def pod() -> client.V1Pod:
    """A freshly-built pod spec. Each test gets its own — no cross-test state."""
    mgr: KubernetesSandboxManager = object.__new__(KubernetesSandboxManager)
    mgr._namespace = "onyx-sandboxes"  # type: ignore[attr-defined]
    mgr._image = "onyxdotapp/sandbox:test"  # type: ignore[attr-defined]
    mgr._service_account = "sandbox-file-sync"  # type: ignore[attr-defined]
    mgr._s3_bucket = "test-bucket"  # type: ignore[attr-defined]
    return mgr._create_sandbox_pod(  # type: ignore[attr-defined]
        sandbox_id="abc12345-abcd-abcd-abcd-abcdef123456",
        tenant_id="t-1",
        onyx_pat="test-pat",
    )


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
    assert volume_names == {"workspace", "managed"}
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
