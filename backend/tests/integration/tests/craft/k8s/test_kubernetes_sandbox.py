"""K8s push contract + sandbox lifecycle against a live cluster."""

from __future__ import annotations

from uuid import uuid4

import pytest
from kubernetes import client
from kubernetes.client.rest import ApiException

from onyx.server.features.build.configs import SANDBOX_BACKEND
from onyx.server.features.build.configs import SANDBOX_NAMESPACE
from onyx.server.features.build.configs import SandboxBackend
from onyx.server.features.build.sandbox.kubernetes.kubernetes_sandbox_manager import (
    KubernetesSandboxManager,
)
from onyx.utils.logger import setup_logger
from tests.integration.tests.craft.k8s.k8s_fixtures import OwnedLivePod
from tests.integration.tests.craft.k8s.k8s_fixtures import pod_exec
from tests.integration.tests.craft.k8s.k8s_fixtures import PoolSession
from tests.integration.tests.craft.k8s.k8s_fixtures import wait_for_pod_deletion
from tests.integration.tests.craft.k8s.k8s_fixtures import wait_until_healthy

logger = setup_logger()

pytestmark = pytest.mark.skipif(
    SANDBOX_BACKEND != SandboxBackend.KUBERNETES,
    reason="K8s tests require SANDBOX_BACKEND=kubernetes; run in the dedicated K8s CI job.",
)


def _read_pod_file(k8s: client.CoreV1Api, pod_name: str, path: str) -> str:
    return pod_exec(k8s, pod_name, SANDBOX_NAMESPACE, f"cat {path}")


def test_provisioned_pod_has_sandbox_image_directories(
    k8s_manager: KubernetesSandboxManager,
    k8s_client: client.CoreV1Api,
    pool_session: PoolSession,
) -> None:
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

    wait_until_healthy(k8s_manager, sandbox_id)


def test_session_workspace_setup_creates_expected_tree(
    k8s_manager: KubernetesSandboxManager,  # noqa: ARG001 — required to build pool_session
    k8s_client: client.CoreV1Api,
    pool_session: PoolSession,
) -> None:
    _, session_id, pod_name = pool_session
    session_path = f"/workspace/sessions/{session_id}"

    for sub in ("outputs", "attachments"):
        resp = pod_exec(
            k8s_client,
            pod_name,
            SANDBOX_NAMESPACE,
            f"test -d {session_path}/{sub} && echo OK || echo MISSING",
        )
        assert "OK" in resp, f"{session_path}/{sub} should exist: {resp!r}"

    for fname in ("AGENTS.md",):
        resp = pod_exec(
            k8s_client,
            pod_name,
            SANDBOX_NAMESPACE,
            f"test -f {session_path}/{fname} && echo OK || echo MISSING",
        )
        assert "OK" in resp, f"{session_path}/{fname} should exist: {resp!r}"

    agents_md = _read_pod_file(k8s_client, pod_name, f"{session_path}/AGENTS.md")
    assert agents_md, "AGENTS.md should not be empty"

    link_target = pod_exec(
        k8s_client,
        pod_name,
        SANDBOX_NAMESPACE,
        f"readlink {session_path}/.opencode/skills || echo MISSING",
    )
    assert "/workspace/managed/skills" in link_target, (
        f".opencode/skills should symlink to managed skills, got: {link_target!r}"
    )

    library_link = pod_exec(
        k8s_client,
        pod_name,
        SANDBOX_NAMESPACE,
        f"readlink {session_path}/user_library || echo MISSING",
    )
    assert "/workspace/managed/user_library" in library_link, (
        f"user_library should symlink to managed user_library, got: {library_link!r}"
    )


def test_health_check_returns_false_for_missing_pod(
    k8s_manager: KubernetesSandboxManager,
) -> None:
    nonexistent_sandbox_id = uuid4()
    assert not k8s_manager.health_check(nonexistent_sandbox_id, timeout=5.0), (
        "health_check() should return False for a non-existent pod"
    )


def test_pod_runs_sandbox_container_and_native_init_sidecar(
    k8s_client: client.CoreV1Api,
    pool_session: PoolSession,
) -> None:
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
    pool_session: PoolSession,
) -> None:
    """The sandbox container must never see IRSA credentials (AWS_* env, token mount)."""
    _, _, pod_name = pool_session

    # Check each var independently so partial leakage can't pass as "all unset".
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
    live_pod: PoolSession,
) -> None:
    """A write to `/workspace/managed/` from the agent container must fail at the kernel (EROFS).

    On live_pod (not pool_session) since the sidecar write leaves a stray probe.txt.
    """
    _, _, pod_name = live_pod

    write_attempt = pod_exec(
        k8s_client,
        pod_name,
        SANDBOX_NAMESPACE,
        "echo agent-write > /workspace/managed/probe.txt 2>&1 || echo BLOCKED",
        container="sandbox",
    )
    assert "BLOCKED" in write_attempt, (
        f"sandbox container should NOT be able to write to /workspace/managed. "
        f"Got: {write_attempt!r}"
    )

    # The same write from the sidecar succeeds: mount is rw there and shared.
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


def test_sandbox_etc_hosts_resolves_proxy_alias(
    k8s_client: client.CoreV1Api,
    pool_session: PoolSession,
) -> None:
    """The main container's /etc/hosts must contain the `sandbox-proxy` alias.

    kubelet manages /etc/hosts per-container; only host_aliases on the PodSpec works.
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
    pool_session: PoolSession,
    k8s_client: client.CoreV1Api,
) -> None:
    """TLS through the proxy reaches the internet while direct egress is iptables-blocked.

    Uses the pool pod (committed rows) so the proxy can resolve identity; egress
    leaves no workspace residue, so a shared pod is safe.
    """
    _sandbox_id, _session_id, pod_name = pool_session

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

    # --noproxy bypasses HTTPS_PROXY; iptables must block it (curl exits non-zero, writes 000).
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


def test_terminate_removes_pod(
    k8s_manager: KubernetesSandboxManager,
    k8s_client: client.CoreV1Api,
    owned_live_pod: OwnedLivePod,
) -> None:
    sandbox_id = owned_live_pod.sandbox_id
    pod_name = owned_live_pod.pod_name

    pod = k8s_client.read_namespaced_pod(name=pod_name, namespace=SANDBOX_NAMESPACE)
    assert pod.status.phase == "Running"

    k8s_manager.terminate(sandbox_id)
    wait_for_pod_deletion(k8s_client, pod_name, SANDBOX_NAMESPACE)

    with pytest.raises(ApiException) as exc_info:
        k8s_client.read_namespaced_pod(name=pod_name, namespace=SANDBOX_NAMESPACE)
    assert exc_info.value.status == 404, (
        f"after terminate, the pod should be gone (404). Got: {exc_info.value.status}"
    )
