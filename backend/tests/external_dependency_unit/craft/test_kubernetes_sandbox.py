"""K8s push contract + sandbox lifecycle (real K8s).

The file-level ``pytestmark`` gates the entire module to the K8s CI lane.
Per project memory: never run these locally — they touch the real cluster.

Prerequisites:
- A running Kubernetes cluster (kind, minikube, or real cluster)
- ``SANDBOX_BACKEND=kubernetes`` in the environment
- The sandbox namespace to exist (default: ``onyx-sandboxes``)
- Service accounts for sandbox (``sandbox-runner``)

Run with:

    SANDBOX_BACKEND=kubernetes python -m dotenv -f .vscode/.env run -- \\
        pytest backend/tests/external_dependency_unit/craft/test_kubernetes_sandbox.py -v
"""

from __future__ import annotations

import base64
import hashlib
import io
import os
import tarfile
import time
from uuid import UUID
from uuid import uuid4

import httpx
import pytest
from kubernetes import client
from kubernetes.client.rest import ApiException

from onyx.db.enums import SandboxStatus
from onyx.server.features.build.configs import SANDBOX_BACKEND
from onyx.server.features.build.configs import SANDBOX_NAMESPACE
from onyx.server.features.build.configs import SandboxBackend
from onyx.server.features.build.sandbox.image.sandbox_daemon.contract import (
    PUSH_DAEMON_PORT,
)
from onyx.server.features.build.sandbox.kubernetes.kubernetes_sandbox_manager import (
    KubernetesSandboxManager,
)
from onyx.server.features.build.sandbox.models import LLMProviderConfig
from onyx.utils.logger import setup_logger
from tests.external_dependency_unit.constants import TEST_TENANT_ID
from tests.external_dependency_unit.craft._test_helpers import default_llm_config
from tests.external_dependency_unit.craft.conftest import pod_exec
from tests.external_dependency_unit.craft.conftest import wait_for_pod_deletion

logger = setup_logger()

pytestmark = pytest.mark.skipif(
    SANDBOX_BACKEND != SandboxBackend.KUBERNETES,
    reason="K8s tests require SANDBOX_BACKEND=kubernetes; run in the dedicated K8s CI job.",
)

# Test constants
TEST_USER_ID = UUID("ee0dd46a-23dc-4128-abab-6712b3f4464c")


# ---------------------------------------------------------------------------
# Local helpers (file-scoped). Generic K8s helpers (``pod_exec``,
# ``wait_for_pod_deletion``, ``k8s_client`` fixture) live in conftest.py.
# ---------------------------------------------------------------------------


def _wait_until_healthy(
    manager: KubernetesSandboxManager,
    sandbox_id: UUID,
    max_attempts: int = 15,
    timeout: float = 5.0,
) -> None:
    """Poll ``health_check`` until True, raising if the pod never comes up."""
    for _ in range(max_attempts):
        if manager.health_check(sandbox_id, timeout=timeout):
            return
        time.sleep(2)
    raise RuntimeError(f"Sandbox {sandbox_id} never became healthy")


def _provisioned_sandbox(
    manager: KubernetesSandboxManager,
    sandbox_id: UUID,
    llm_config: LLMProviderConfig | None = None,
) -> None:
    """Provision a sandbox and block until the pod is healthy."""
    config = llm_config or default_llm_config(
        api_key=os.environ.get("OPENAI_API_KEY", "test-key"),
    )
    info = manager.provision(
        sandbox_id=sandbox_id,
        user_id=TEST_USER_ID,
        tenant_id=TEST_TENANT_ID,
        llm_config=config,
        onyx_pat="ci-test-pat",
    )
    assert info.status == SandboxStatus.RUNNING
    _wait_until_healthy(manager, sandbox_id)


def _read_pod_file(k8s: client.CoreV1Api, pod_name: str, path: str) -> str:
    return pod_exec(k8s, pod_name, SANDBOX_NAMESPACE, f"cat {path}")


# ---------------------------------------------------------------------------
# Fixtures: k8s_manager, pool_session, live_pod, provisioned_sandbox, and
# k8s_client are provided by conftest.py.
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_provisioned_pod_has_sandbox_image_directories(
    k8s_manager: KubernetesSandboxManager,
    k8s_client: client.CoreV1Api,
    pool_session: tuple[UUID, UUID, str],
) -> None:
    """After ``provision()``, the baked-in workspace directories exist.

    Pins the sandbox image contract: ``/workspace/templates``, ``/workspace/managed``
    and ``/workspace/sessions`` are all present and the pod is healthy enough to
    answer ``health_check``. Also doubles as the merged ``health_check_returns_true``
    coverage per the plan note.
    """
    sandbox_id, _, pod_name = pool_session

    pod = k8s_client.read_namespaced_pod(name=pod_name, namespace=SANDBOX_NAMESPACE)
    assert pod.status.phase == "Running"

    for required in (
        "/workspace/templates",
        "/workspace/managed",
        "/workspace/sessions",
    ):
        resp = pod_exec(
            k8s_client,
            pod_name,
            SANDBOX_NAMESPACE,
            f"test -d {required} && echo OK || echo MISSING",
        )
        assert "OK" in resp, (
            f"{required} should exist in the provisioned pod. Got: {resp!r}"
        )

    assert k8s_manager.health_check(sandbox_id, timeout=5.0), (
        "health_check() should return True for a freshly provisioned pod"
    )


def test_session_workspace_setup_creates_expected_tree(
    k8s_manager: KubernetesSandboxManager,  # noqa: ARG001 — required to build live_pod
    k8s_client: client.CoreV1Api,
    pool_session: tuple[UUID, UUID, str],
) -> None:
    """After ``setup_session_workspace``, the session dir contains the
    canonical tree: ``outputs/``, ``attachments/``, ``AGENTS.md``, and the
    ``.opencode/skills`` symlink. (opencode config is pod-level under the
    serve transport, not a per-session file.)
    """
    _, session_id, pod_name = pool_session
    session_path = f"/workspace/sessions/{session_id}"

    # Directories
    for sub in ("outputs", "attachments"):
        resp = pod_exec(
            k8s_client,
            pod_name,
            SANDBOX_NAMESPACE,
            f"test -d {session_path}/{sub} && echo OK || echo MISSING",
        )
        assert "OK" in resp, f"{session_path}/{sub} should exist: {resp!r}"

    # Files
    for fname in ("AGENTS.md",):
        resp = pod_exec(
            k8s_client,
            pod_name,
            SANDBOX_NAMESPACE,
            f"test -f {session_path}/{fname} && echo OK || echo MISSING",
        )
        assert "OK" in resp, f"{session_path}/{fname} should exist: {resp!r}"

    # AGENTS.md content has non-zero bytes
    agents_md = _read_pod_file(k8s_client, pod_name, f"{session_path}/AGENTS.md")
    assert agents_md, "AGENTS.md should not be empty"

    # .opencode/skills must be a symlink targeting /workspace/managed/skills
    link_target = pod_exec(
        k8s_client,
        pod_name,
        SANDBOX_NAMESPACE,
        f"readlink {session_path}/.opencode/skills || echo MISSING",
    )
    assert "/workspace/managed/skills" in link_target, (
        f".opencode/skills should symlink to managed skills, got: {link_target!r}"
    )

    # user_library must be a symlink targeting /workspace/managed/user_library
    library_link = pod_exec(
        k8s_client,
        pod_name,
        SANDBOX_NAMESPACE,
        f"readlink {session_path}/user_library || echo MISSING",
    )
    assert "/workspace/managed/user_library" in library_link, (
        f"user_library should symlink to managed user_library, got: {library_link!r}"
    )


def test_push_signed_tarball_lands_under_mount_path(
    k8s_manager: KubernetesSandboxManager,
    k8s_client: client.CoreV1Api,
    pool_session: tuple[UUID, UUID, str],
) -> None:
    """``write_files_to_sandbox`` with a ``{slug}/SKILL.md`` fileset must
    land the file at ``/workspace/managed/skills/<slug>/SKILL.md`` after
    the in-pod daemon extracts the tarball.
    """
    sandbox_id, _, pod_name = pool_session
    slug = f"push-test-{uuid4().hex[:8]}"
    body = f"---\nname: {slug}\ndescription: pushed bundle\n---\n# v1\n"

    # Wait for the push daemon (port 8731) to be ready before pushing.
    for _ in range(15):
        try:
            resp = pod_exec(
                k8s_client,
                pod_name,
                SANDBOX_NAMESPACE,
                f"curl -sf http://localhost:{PUSH_DAEMON_PORT}/health || echo DOWN",
            )
            if "DOWN" not in resp:
                break
        except Exception:
            pass
        time.sleep(2)

    k8s_manager.write_files_to_sandbox(
        sandbox_id=sandbox_id,
        mount_path=f"/workspace/managed/skills/{slug}",
        files={"SKILL.md": body.encode("utf-8")},
    )

    target = f"/workspace/managed/skills/{slug}/SKILL.md"
    resp = pod_exec(
        k8s_client,
        pod_name,
        SANDBOX_NAMESPACE,
        f"test -f {target} && echo OK || echo MISSING",
    )
    assert "OK" in resp, f"Pushed file should be present at {target}: {resp!r}"

    contents = _read_pod_file(k8s_client, pod_name, target)
    assert contents == body, (
        f"Pushed file contents should match. Expected {body!r}, got {contents!r}"
    )


def test_push_second_call_replaces_previous_via_atomic_swap(
    k8s_manager: KubernetesSandboxManager,
    k8s_client: client.CoreV1Api,
    pool_session: tuple[UUID, UUID, str],
) -> None:
    """Push v1 then v2; the post-push file content reflects v2 (atomic swap)."""
    sandbox_id, _, pod_name = pool_session
    slug = f"swap-test-{uuid4().hex[:8]}"
    mount_path = f"/workspace/managed/skills/{slug}"
    target = f"{mount_path}/SKILL.md"

    v1 = f"---\nname: {slug}\ndescription: v1\n---\n# v1 content\n"
    v2 = f"---\nname: {slug}\ndescription: v2\n---\n# v2 content\n"

    k8s_manager.write_files_to_sandbox(
        sandbox_id=sandbox_id,
        mount_path=mount_path,
        files={"SKILL.md": v1.encode("utf-8")},
    )
    after_v1 = _read_pod_file(k8s_client, pod_name, target)
    assert after_v1 == v1, f"After v1 push, file should contain v1. Got: {after_v1!r}"

    k8s_manager.write_files_to_sandbox(
        sandbox_id=sandbox_id,
        mount_path=mount_path,
        files={"SKILL.md": v2.encode("utf-8")},
    )
    after_v2 = _read_pod_file(k8s_client, pod_name, target)
    assert after_v2 == v2, (
        f"After v2 push, file should contain v2 (atomic swap). Got: {after_v2!r}"
    )


def test_push_with_bad_signature_returns_401(
    k8s_manager: KubernetesSandboxManager,  # noqa: ARG001 — required to build live_pod
    k8s_client: client.CoreV1Api,
    pool_session: tuple[UUID, UUID, str],
) -> None:
    """A push request with a deliberately wrong signature returns 401 from
    the in-pod daemon.

    Builds the request payload manually (a valid tar.gz with a correct SHA
    header and timestamp), but supplies a garbage signature so the daemon's
    Ed25519 verify fails.
    """
    sandbox_id, _, pod_name = pool_session

    pod = k8s_client.read_namespaced_pod(name=pod_name, namespace=SANDBOX_NAMESPACE)
    pod_ip = pod.status.pod_ip
    assert pod_ip, f"pod {pod_name} has no IP — cannot reach push daemon"

    slug = f"bad-sig-{uuid4().hex[:8]}"
    file_bytes = b"---\nname: bad-sig\n---\n# nope\n"

    # Build a well-formed tar.gz so the daemon doesn't reject for archive shape.
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz", compresslevel=6) as tar:
        info = tarfile.TarInfo(name="SKILL.md")
        info.size = len(file_bytes)
        info.mtime = 0
        tar.addfile(info, io.BytesIO(file_bytes))
    tar_bytes = buf.getvalue()
    sha256_hex = hashlib.sha256(tar_bytes).hexdigest()
    bad_sig = base64.b64encode(b"\x00" * 64).decode()
    ts = str(int(time.time()))

    url = f"http://{pod_ip}:{PUSH_DAEMON_PORT}/push"
    # We POST from the test runner to the pod IP; the runner must have
    # cluster-network access (CI K8s lane provides it).
    with httpx.Client(timeout=30.0) as http_client:
        resp = http_client.post(
            url,
            params={"mount_path": f"/workspace/managed/skills/{slug}"},
            content=tar_bytes,
            headers={
                "Content-Type": "application/gzip",
                "X-Bundle-Sha256": sha256_hex,
                "X-Push-Signature": bad_sig,
                "X-Push-Timestamp": ts,
            },
        )

    assert resp.status_code == 401, (
        f"daemon should reject bad signature with 401, got "
        f"{resp.status_code}: {resp.text!r}"
    )


def test_health_check_returns_false_for_missing_pod(
    k8s_manager: KubernetesSandboxManager,
) -> None:
    """``health_check`` returns False when the pod does not exist.

    Tiny isolated test — no provision needed.
    """
    nonexistent_sandbox_id = uuid4()
    assert not k8s_manager.health_check(nonexistent_sandbox_id, timeout=5.0), (
        "health_check() should return False for a non-existent pod"
    )


# ---------------------------------------------------------------------------
# Sidecar contract: the sandbox app container plus native init sidecar model
# is what enforces credential isolation. These tests verify the live-cluster
# shape that the unit-level pod-spec tests can't observe (IRSA injection
# happens at admission time).
# ---------------------------------------------------------------------------


def test_pod_runs_sandbox_container_and_native_init_sidecar(
    k8s_client: client.CoreV1Api,
    pool_session: tuple[UUID, UUID, str],
) -> None:
    """After provision, the pod has one `sandbox` app container and a running
    `sidecar` init container. The sidecar's `/health` readiness probe gates
    pod readiness.
    """
    _, _, pod_name = pool_session
    pod = k8s_client.read_namespaced_pod(name=pod_name, namespace=SANDBOX_NAMESPACE)

    container_statuses = {c.name: c for c in pod.status.container_statuses or []}
    init_statuses = {c.name: c for c in pod.status.init_container_statuses or []}
    assert set(container_statuses) == {"sandbox"}, (
        f"pod should have exactly 1 app container, got {set(container_statuses)}"
    )
    assert {"sandbox-init", "sidecar"}.issubset(init_statuses), (
        f"pod missing expected init containers, got {set(init_statuses)}"
    )
    assert init_statuses["sidecar"].ready, (
        "sidecar init container should be ready via /health probe"
    )
    assert container_statuses["sandbox"].ready, "sandbox container should be ready"


def test_irsa_credentials_stripped_from_sandbox_container(
    k8s_client: client.CoreV1Api,
    pool_session: tuple[UUID, UUID, str],
) -> None:
    """The sandbox container must never see IRSA credentials.

    Guards the code-side half of the IRSA contract: the pod spec must keep
    the agent container free of `AWS_*` env vars and the projected token
    mount, so that even if a misconfigured SA grants IRSA, the agent can't
    use it to reach cross-tenant S3.

    The matching positive check ("sidecar *does* get AWS_ROLE_ARN from
    IRSA") depends on the EKS pod-identity webhook plus SA annotations
    that don't exist on a kind cluster, so it lives elsewhere.
    """
    _, _, pod_name = pool_session

    # Check each var independently so partial leakage (one set, one unset)
    # cannot pass as "all unset". The shell expansion ${VAR:-} substitutes
    # an empty string when the var is unset OR empty; we then explicitly
    # report which (if any) is non-empty.
    sandbox_env = pod_exec(
        k8s_client,
        pod_name,
        SANDBOX_NAMESPACE,
        (
            "for v in AWS_ROLE_ARN AWS_WEB_IDENTITY_TOKEN_FILE; do "
            '  eval "val=\\${${v}:-}"; '
            '  if [ -n "$val" ]; then echo "LEAK:$v=$val"; fi; '
            "done; echo DONE"
        ),
        container="sandbox",
    )
    assert "LEAK:" not in sandbox_env, (
        f"sandbox container leaked IRSA env vars: {sandbox_env!r}"
    )
    assert "DONE" in sandbox_env, (
        f"env-leak probe did not run to completion: {sandbox_env!r}"
    )

    token_mount = pod_exec(
        k8s_client,
        pod_name,
        SANDBOX_NAMESPACE,
        "[ -d /var/run/secrets/eks.amazonaws.com ] && echo PRESENT || echo MISSING",
        container="sandbox",
    )
    assert "MISSING" in token_mount, (
        f"IRSA token mount leaked into sandbox container: {token_mount!r}"
    )


def test_managed_directory_is_read_only_from_sandbox_container(
    k8s_manager: KubernetesSandboxManager,  # noqa: ARG001 — required to build live_pod
    k8s_client: client.CoreV1Api,
    live_pod: tuple[UUID, UUID, str],
) -> None:
    """A write attempt to `/workspace/managed/` from the agent container
    must fail at the kernel level (EROFS), not just at the application level.

    Without this, a compromised agent could swap a pushed skill bundle
    after the daemon extracts it.

    Stays on ``live_pod`` (not ``pool_session``) because the sidecar
    write in the second half lands a stray ``/workspace/managed/probe.txt``
    that pool cleanup doesn't sweep.
    """
    _, _, pod_name = live_pod

    write_attempt = pod_exec(
        k8s_client,
        pod_name,
        SANDBOX_NAMESPACE,
        # sh writes the error to stderr; pod_exec captures combined output.
        "echo agent-write > /workspace/managed/probe.txt 2>&1 || echo BLOCKED",
        container="sandbox",
    )
    assert "BLOCKED" in write_attempt, (
        f"sandbox container should NOT be able to write to /workspace/managed. "
        f"Got: {write_attempt!r}"
    )

    # And the same write from the sidecar succeeds — confirming the mount
    # is rw there and the volume is actually shared.
    pod_exec(
        k8s_client,
        pod_name,
        SANDBOX_NAMESPACE,
        "echo sidecar-write > /workspace/managed/probe.txt",
        container="sidecar",
    )
    read_from_sandbox = pod_exec(
        k8s_client,
        pod_name,
        SANDBOX_NAMESPACE,
        "cat /workspace/managed/probe.txt",
        container="sandbox",
    )
    assert "sidecar-write" in read_from_sandbox, (
        f"sandbox should see files the sidecar wrote. Got: {read_from_sandbox!r}"
    )


# ---------------------------------------------------------------------------
# Egress proxy: the sandbox must reach the outside world ONLY via the proxy.
# Run against the live container to catch runtime resolution / iptables bugs
# that pod-spec unit tests can't observe.
# ---------------------------------------------------------------------------


def test_sandbox_etc_hosts_resolves_proxy_alias(
    k8s_client: client.CoreV1Api,
    pool_session: tuple[UUID, UUID, str],
) -> None:
    """The main container's /etc/hosts must contain the `sandbox-proxy` alias.

    kubelet manages /etc/hosts per-container so initContainer writes don't
    propagate; host_aliases on the PodSpec is the only path that works.
    """
    _, _, pod_name = pool_session
    hosts = pod_exec(
        k8s_client,
        pod_name,
        SANDBOX_NAMESPACE,
        "cat /etc/hosts",
        container="sandbox",
    )
    assert "sandbox-proxy" in hosts, (
        f"main container /etc/hosts missing sandbox-proxy alias: {hosts!r}"
    )


def test_sandbox_egress_only_flows_via_proxy(
    provisioned_sandbox: tuple[UUID, str],
    k8s_client: client.CoreV1Api,
) -> None:
    """End-to-end: TLS through the proxy reaches the internet while direct
    egress is blocked by iptables. Catches missing host_aliases, broken CA
    trust, iptables misconfiguration, or proxy-listen-port drift.

    Uses the ``provisioned_sandbox`` fixture, which provisions through the
    app's own path (committed Sandbox + User rows), so the proxy can resolve
    the pod's identity; without a backing row the gate fail-closes with 403
    ``unidentified_sandbox`` even for non-gated hosts.
    """
    _sandbox_id, pod_name = provisioned_sandbox

    # Proxied egress: exercises HTTPS_PROXY, /etc/hosts, CA bundle, and proxy.
    proxied = pod_exec(
        k8s_client,
        pod_name,
        SANDBOX_NAMESPACE,
        "curl -s -o /dev/null -w '%{http_code}' https://www.example.com",
        container="sandbox",
    )
    assert proxied.strip() == "200", (
        f"proxied egress should return 200, got {proxied!r}"
    )

    # Direct egress: --noproxy bypasses HTTPS_PROXY; iptables must block it
    # (curl exits non-zero and writes 000 on failure).
    direct = pod_exec(
        k8s_client,
        pod_name,
        SANDBOX_NAMESPACE,
        (
            "curl --noproxy '*' -s -o /dev/null --max-time 5 "
            "-w '%{http_code}' https://1.1.1.1 || echo BLOCKED:$?"
        ),
        container="sandbox",
    )
    assert "200" not in direct, (
        f"direct egress should be blocked, but got HTTP 200: {direct!r}"
    )
    assert "BLOCKED:" in direct or direct.strip().startswith("000"), (
        f"direct egress should fail closed, got {direct!r}"
    )


def test_terminate_removes_pod_and_marks_db(
    k8s_manager: KubernetesSandboxManager,
    k8s_client: client.CoreV1Api,
) -> None:
    """``terminate`` removes the pod (404 on subsequent read) and renders
    ``health_check`` False.
    """
    sandbox_id = uuid4()
    _provisioned_sandbox(k8s_manager, sandbox_id)
    pod_name = k8s_manager._get_pod_name(sandbox_id)

    # Pod exists before termination.
    pod = k8s_client.read_namespaced_pod(name=pod_name, namespace=SANDBOX_NAMESPACE)
    assert pod.status.phase == "Running"

    k8s_manager.terminate(sandbox_id)
    wait_for_pod_deletion(k8s_client, pod_name, SANDBOX_NAMESPACE)

    with pytest.raises(ApiException) as exc_info:
        k8s_client.read_namespaced_pod(name=pod_name, namespace=SANDBOX_NAMESPACE)
    assert exc_info.value.status == 404, (
        f"after terminate, the pod should be gone (404). Got: {exc_info.value.status}"
    )

    assert not k8s_manager.health_check(sandbox_id, timeout=5.0), (
        "health_check() should return False after termination"
    )


@pytest.mark.xfail(
    strict=True,
    reason=(
        "known: _get_pod_name uses uuid[:8] = 32 bits of entropy. Birthday "
        "collision at ~77k sandboxes ever; current failure on collision is "
        "K8s 409 on provision, not data leak."
    ),
)
def test_pod_name_uses_full_uuid_not_first_8_chars() -> None:
    """Asserts pod_name encodes the full sandbox UUID, so two UUIDs sharing
    the first 8 hex chars produce distinct pod names.

    Currently fails because ``_get_pod_name`` truncates to 8 chars
    (xfail strict absorbs). When the fix lands, the xfail flips to XPASS
    and the fixer removes the mark.
    """
    # Bypass __init__/_initialize since _get_pod_name does not touch the K8s
    # client; it only formats the UUID. This keeps the test deterministic
    # even though the file's pytestmark gate already restricts execution to
    # the K8s CI job.
    manager = KubernetesSandboxManager.__new__(KubernetesSandboxManager)

    uuid_a = UUID("abc12345-0000-0000-0000-000000000001")
    uuid_b = UUID("abc12345-0000-0000-0000-000000000002")

    assert manager._get_pod_name(uuid_a) != manager._get_pod_name(uuid_b), (
        "pod name must encode the full UUID so distinct sandboxes do not "
        "collide on the first 8 hex chars"
    )
