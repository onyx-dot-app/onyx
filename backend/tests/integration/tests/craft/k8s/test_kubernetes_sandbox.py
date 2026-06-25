"""K8s push contract + sandbox lifecycle against a live cluster."""

from __future__ import annotations

import base64
import hashlib
import io
import os
import tarfile
import time
from contextlib import suppress
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
from shared_configs.configs import POSTGRES_DEFAULT_SCHEMA_STANDARD_VALUE
from tests.common.craft.payloads import default_llm_config
from tests.integration.tests.craft.k8s.k8s_fixtures import CRAFT_TEST_USER_ID
from tests.integration.tests.craft.k8s.k8s_fixtures import pod_exec
from tests.integration.tests.craft.k8s.k8s_fixtures import wait_for_pod_deletion
from tests.integration.tests.craft.k8s.k8s_fixtures import wait_until_healthy

logger = setup_logger()

pytestmark = pytest.mark.skipif(
    SANDBOX_BACKEND != SandboxBackend.KUBERNETES,
    reason="K8s tests require SANDBOX_BACKEND=kubernetes; run in the dedicated K8s CI job.",
)


def _provisioned_sandbox(
    manager: KubernetesSandboxManager,
    sandbox_id: UUID,
    llm_config: LLMProviderConfig | None = None,
) -> None:
    config = llm_config or default_llm_config(
        api_key=os.environ.get("OPENAI_API_KEY", "test-key"),
    )
    info = manager.provision(
        sandbox_id=sandbox_id,
        user_id=CRAFT_TEST_USER_ID,
        tenant_id=POSTGRES_DEFAULT_SCHEMA_STANDARD_VALUE,
        llm_config=config,
        onyx_pat="ci-test-pat",
    )
    assert info.status == SandboxStatus.RUNNING
    wait_until_healthy(manager, sandbox_id)


def _read_pod_file(k8s: client.CoreV1Api, pod_name: str, path: str) -> str:
    return pod_exec(k8s, pod_name, SANDBOX_NAMESPACE, f"cat {path}")


def test_provisioned_pod_has_sandbox_image_directories(
    k8s_manager: KubernetesSandboxManager,
    k8s_client: client.CoreV1Api,
    pool_session: tuple[UUID, UUID, str],
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
    k8s_manager: KubernetesSandboxManager,  # noqa: ARG001 — required to build live_pod
    k8s_client: client.CoreV1Api,
    pool_session: tuple[UUID, UUID, str],
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


def test_push_signed_tarball_lands_under_mount_path(
    k8s_manager: KubernetesSandboxManager,
    k8s_client: client.CoreV1Api,
    pool_session: tuple[UUID, UUID, str],
) -> None:
    sandbox_id, _, pod_name = pool_session
    slug = f"push-test-{uuid4().hex[:8]}"
    body = f"---\nname: {slug}\ndescription: pushed bundle\n---\n# v1\n"

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
    sandbox_id, _, pod_name = pool_session

    pod = k8s_client.read_namespaced_pod(name=pod_name, namespace=SANDBOX_NAMESPACE)
    pod_ip = pod.status.pod_ip
    assert pod_ip, f"pod {pod_name} has no IP — cannot reach push daemon"

    slug = f"bad-sig-{uuid4().hex[:8]}"
    file_bytes = b"---\nname: bad-sig\n---\n# nope\n"

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
    nonexistent_sandbox_id = uuid4()
    assert not k8s_manager.health_check(nonexistent_sandbox_id, timeout=5.0), (
        "health_check() should return False for a non-existent pod"
    )


def test_pod_runs_sandbox_container_and_native_init_sidecar(
    k8s_client: client.CoreV1Api,
    pool_session: tuple[UUID, UUID, str],
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
    pool_session: tuple[UUID, UUID, str],
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
    live_pod: tuple[UUID, UUID, str],
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
    pool_session: tuple[UUID, UUID, str],
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
    provisioned_sandbox: tuple[UUID, str],
    k8s_client: client.CoreV1Api,
) -> None:
    """TLS through the proxy reaches the internet while direct egress is iptables-blocked.

    Uses ``provisioned_sandbox`` (committed rows) so the proxy can resolve identity.
    """
    _sandbox_id, pod_name = provisioned_sandbox

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


def test_terminate_removes_pod_and_marks_db(
    k8s_manager: KubernetesSandboxManager,
    k8s_client: client.CoreV1Api,
) -> None:
    sandbox_id = uuid4()
    pod_name = k8s_manager._get_pod_name(sandbox_id)
    try:
        _provisioned_sandbox(k8s_manager, sandbox_id)

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
    finally:
        with suppress(Exception):
            k8s_manager.terminate(sandbox_id)
        with suppress(Exception):
            wait_for_pod_deletion(k8s_client, pod_name, SANDBOX_NAMESPACE)
