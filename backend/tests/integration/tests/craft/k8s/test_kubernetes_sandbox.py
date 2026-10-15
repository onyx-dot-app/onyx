"""K8s push contract + sandbox lifecycle against a live cluster."""

from __future__ import annotations

import json
from io import BytesIO, UnsupportedOperation
from tempfile import TemporaryFile
from uuid import uuid4

import pytest
from kubernetes import client
from kubernetes.client.rest import ApiException

from onyx.server.features.build.configs import (
    SANDBOX_NAMESPACE,
)
from onyx.server.features.build.sandbox.image.guest import PROTOCOL_VERSION
from onyx.server.features.build.sandbox.image.guest.models import RunRequest
from onyx.server.features.build.sandbox.image.guest.operations import MAX_INPUT_BYTES
from onyx.server.features.build.sandbox.kubernetes_runtime import KubernetesRuntime
from onyx.server.features.build.sandbox.manager import (
    SandboxManager,
)
from onyx.server.features.build.sandbox.models import SandboxExecError
from onyx.server.features.build.timeouts import BULK_TRANSFER_TIMEOUT_SECONDS
from onyx.utils.logger import setup_logger
from tests.integration.tests.craft.k8s.k8s_fixtures import (
    OwnedLivePod,
    PoolSession,
    pod_exec,
    wait_for_pod_deletion,
    wait_until_healthy,
)

logger = setup_logger()


class _NonSeekableInput(BytesIO):
    def seekable(self) -> bool:
        return False

    def seek(self, _offset: int, _whence: int = 0, /) -> int:
        raise UnsupportedOperation("input cannot seek")

    def tell(self) -> int:
        raise UnsupportedOperation("input length is unknown")


def _read_pod_file(k8s: client.CoreV1Api, pod_name: str, path: str) -> str:
    return pod_exec(k8s, pod_name, SANDBOX_NAMESPACE, f"cat {path}")


@pytest.mark.parametrize(
    "stdin",
    [None, b"", b"x" * (128 * 1024)],
    ids=["absent", "empty", "finite-128KiB"],
)
def test_guest_run_preserves_delayed_stdout_after_stdin_eof(
    k8s_manager: SandboxManager,
    pool_session: PoolSession,
    stdin: bytes | None,
) -> None:
    request = RunRequest(
        argv=[
            "python",
            "-c",
            "import sys, time; data = sys.stdin.buffer.read(); "
            "time.sleep(2); sys.stdout.buffer.write(b'after-eof\\n' + data)",
        ],
        timeout_seconds=30,
        has_stdin=stdin is not None,
    )

    stdout = k8s_manager._guest(
        pool_session.sandbox_id,
        "run",
        request.model_dump(mode="json"),
        stdin=stdin,
        timeout=45,
    )

    assert stdout == b"after-eof\n" + (stdin or b"")


@pytest.mark.parametrize("nonseekable", [False, True], ids=["bytes", "stream"])
def test_guest_stream_preserves_binary_stdout_after_stdin_eof(
    k8s_manager: SandboxManager,
    pool_session: PoolSession,
    nonseekable: bool,
) -> None:
    stdin = bytes(range(256)) * 512
    request = RunRequest(
        argv=[
            "python",
            "-c",
            "import sys, time; data = sys.stdin.buffer.read(); "
            "time.sleep(2); sys.stdout.buffer.write(data)",
        ],
        timeout_seconds=30,
        has_stdin=True,
    )

    with _NonSeekableInput(stdin) as source:
        stdout = b"".join(
            k8s_manager._guest_stream(
                pool_session.sandbox_id,
                "run",
                request.model_dump(mode="json"),
                stdin=source if nonseekable else stdin,
                timeout=45,
            )
        )
        assert not source.closed

    assert stdout == bytes(range(256)) * 512


@pytest.mark.parametrize(
    "input_bytes", [2 * 1024 * 1024, 50 * 1024 * 1024], ids=["2MiB", "50MiB"]
)
def test_guest_rejects_metadata_while_nonseekable_input_uploads(
    k8s_manager: SandboxManager,
    pool_session: PoolSession,
    input_bytes: int,
) -> None:
    with _NonSeekableInput(b"x" * input_bytes) as source:
        with pytest.raises(SandboxExecError) as failed:
            k8s_manager._guest(
                pool_session.sandbox_id,
                "run",
                {"argv": [], "has_stdin": True},
                stdin=source,
                timeout=BULK_TRANSFER_TIMEOUT_SECONDS,
            )
        assert not source.closed

    assert failed.value.returncode == 1
    assert "ValidationError:" in failed.value.stderr
    status = k8s_manager._guest(pool_session.sandbox_id, "status", {}, timeout=30)
    assert json.loads(status)["protocol"] == PROTOCOL_VERSION


def test_guest_rejects_streamed_input_above_limit_before_running_command(
    k8s_manager: SandboxManager,
    pool_session: PoolSession,
) -> None:
    request = RunRequest(
        argv=["/bin/sh", "-c", "printf input-limit-command-executed"],
        timeout_seconds=BULK_TRANSFER_TIMEOUT_SECONDS,
        has_stdin=True,
    )
    stdout = bytearray()
    with TemporaryFile(mode="w+b") as source:
        source.truncate(MAX_INPUT_BYTES + 1)
        source.seek(0)
        with pytest.raises(SandboxExecError) as failed:
            for chunk in k8s_manager._guest_stream(
                pool_session.sandbox_id,
                "run",
                request.model_dump(mode="json"),
                stdin=source,
                timeout=BULK_TRANSFER_TIMEOUT_SECONDS,
            ):
                stdout.extend(chunk)
        assert not source.closed

    assert not stdout
    assert failed.value.returncode == 1
    assert failed.value.stderr == (
        f"ValueError: input exceeds {MAX_INPUT_BYTES} byte limit\n"
    )
    status = k8s_manager._guest(pool_session.sandbox_id, "status", {}, timeout=30)
    assert json.loads(status)["protocol"] == PROTOCOL_VERSION


@pytest.mark.parametrize(
    "wire",
    [
        b"\x00",
        b"\x00\x00\x00\x02x",
        b"\x00\x00\x00\x01x",
        (64 * 1024 + 1).to_bytes(4, "big"),
    ],
    ids=["short-header", "short-payload", "missing-terminator", "oversize-frame"],
)
def test_guest_decoder_rejects_malformed_input_before_running_commands(
    k8s_manager: SandboxManager,
    pool_session: PoolSession,
    wire: bytes,
) -> None:
    inner_command = KubernetesRuntime.guest_command(
        "run",
        {
            "argv": ["/bin/sh", "-c", "printf parser-accepted"],
            "has_stdin": True,
            "timeout_seconds": 10,
        },
    )
    request = RunRequest(argv=inner_command, has_stdin=True, timeout_seconds=20)
    stdout = bytearray()

    with pytest.raises(SandboxExecError) as failed:
        for chunk in k8s_manager._guest_stream(
            pool_session.sandbox_id,
            "run",
            request.model_dump(mode="json"),
            stdin=wire,
            timeout=30,
        ):
            stdout.extend(chunk)

    assert not stdout
    assert failed.value.returncode == 1
    assert "ValueError:" in failed.value.stderr


def test_guest_stream_preserves_delayed_output_and_nonzero_status_after_stdin_eof(
    k8s_manager: SandboxManager,
    pool_session: PoolSession,
) -> None:
    request = RunRequest(
        argv=[
            "python",
            "-c",
            "import sys, time; "
            "assert sys.stdin.buffer.read() == b'input-complete\\n'; "
            "time.sleep(2); sys.stdout.buffer.write(b'delayed-stdout\\n'); "
            "sys.stderr.buffer.write(b'delayed-stderr\\n'); sys.exit(7)",
        ],
        timeout_seconds=30,
        has_stdin=True,
    )
    stdout = bytearray()

    with pytest.raises(SandboxExecError) as exc_info:
        for chunk in k8s_manager._guest_stream(
            pool_session.sandbox_id,
            "run",
            request.model_dump(mode="json"),
            stdin=b"input-complete\n",
            timeout=45,
        ):
            stdout.extend(chunk)

    assert bytes(stdout) == b"delayed-stdout\n"
    assert exc_info.value.stderr == "delayed-stderr\n"
    assert exc_info.value.returncode == 7


@pytest.mark.parametrize(
    ("exit_code", "expected_marker"),
    [(7, b"cleaned"), (0, b"leaked")],
    ids=["failed-command", "successful-background"],
)
def test_guest_run_background_children_follow_exit_status(
    k8s_manager: SandboxManager,
    pool_session: PoolSession,
    exit_code: int,
    expected_marker: bytes,
) -> None:
    marker = f"/tmp/onyx-guest-failed-run-{uuid4().hex}"
    request = RunRequest(
        argv=[
            "sh",
            "-c",
            '(sleep 2; printf leaked > "$1") >/dev/null 2>&1 & '
            f"printf 'command-stderr\\n' >&2; exit {exit_code}",
            "failed-guest-run",
            marker,
        ],
        timeout_seconds=30,
    )

    try:
        try:
            stdout = k8s_manager._guest(
                pool_session.sandbox_id,
                "run",
                request.model_dump(mode="json"),
                timeout=45,
            )
        except SandboxExecError as error:
            assert error.returncode == exit_code == 7
            assert error.stderr == "command-stderr\n"
        else:
            assert exit_code == 0
            assert stdout == b""
        probe = RunRequest(
            argv=[
                "sh",
                "-c",
                'sleep 3; if test -e "$1"; then cat "$1"; else printf cleaned; fi',
                "check-failed-guest-run",
                marker,
            ],
            timeout_seconds=30,
        )
        assert (
            k8s_manager._guest(
                pool_session.sandbox_id,
                "run",
                probe.model_dump(mode="json"),
                timeout=45,
            )
            == expected_marker
        )
    finally:
        cleanup = RunRequest(argv=["rm", "-f", "--", marker], timeout_seconds=10)
        k8s_manager._guest(
            pool_session.sandbox_id,
            "run",
            cleanup.model_dump(mode="json"),
            timeout=20,
        )


def test_provisioned_pod_has_sandbox_image_directories(
    k8s_manager: SandboxManager,
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
    k8s_manager: SandboxManager,  # noqa: ARG001 — required to build pool_session
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
    k8s_manager: SandboxManager,
) -> None:
    nonexistent_sandbox_id = uuid4()
    assert not k8s_manager.health_check(nonexistent_sandbox_id, timeout=5.0), (
        "health_check() should return False for a non-existent pod"
    )


def test_pod_runs_one_guest_after_firewall_init(
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
    assert set(init_statuses) == {"sandbox-firewall"}, (
        f"pod missing expected init containers, got {set(init_statuses)}"
    )
    assert init_statuses["sandbox-firewall"].state.terminated.exit_code == 0
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
        root=False,
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
        root=False,
    )
    assert "MISSING" in token_mount, (
        f"IRSA token mount leaked into sandbox container: {token_mount!r}"
    )


def test_managed_directory_is_read_only_from_sandbox_container(
    k8s_manager: SandboxManager,  # noqa: ARG001 — required to build live_pod
    k8s_client: client.CoreV1Api,
    live_pod: PoolSession,
) -> None:
    """Root-owned managed content must remain readable but unwritable by the agent."""
    _, _, pod_name = live_pod

    write_attempt = pod_exec(
        k8s_client,
        pod_name,
        SANDBOX_NAMESPACE,
        "echo agent-write > /workspace/managed/probe.txt 2>&1 || echo BLOCKED",
        root=False,
    )
    assert "BLOCKED" in write_attempt, (
        f"sandbox container should NOT be able to write to /workspace/managed. "
        f"Got: {write_attempt!r}"
    )

    pod_exec(
        k8s_client,
        pod_name,
        SANDBOX_NAMESPACE,
        "echo root-fixture-write > /workspace/managed/probe.txt",
        root=True,
    )
    read_from_sandbox = pod_exec(
        k8s_client,
        pod_name,
        SANDBOX_NAMESPACE,
        "cat /workspace/managed/probe.txt",
        root=False,
    )
    assert "root-fixture-write" in read_from_sandbox, (
        f"agent should see root-published managed content. Got: {read_from_sandbox!r}"
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
        root=False,
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
        root=False,
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
        root=False,
    )
    assert "200" not in direct, (
        f"direct egress should be blocked, but got HTTP 200: {direct!r}"
    )
    assert "BLOCKED:" in direct or direct.strip().startswith("000"), (
        f"direct egress should fail closed, got {direct!r}"
    )


def test_terminate_removes_pod(
    k8s_manager: SandboxManager,
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
