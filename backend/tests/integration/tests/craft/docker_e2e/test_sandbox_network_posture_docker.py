"""Docker-backend sandbox network/security-posture tests.

Zero-capabilities at UID 1000, proxy-MITM of HTTPS, credential injection on the
wire, iptables egress lockdown, unidentified-sandbox rejection, and workspace
ownership — exercised against one module-scoped RUNNING sandbox.
"""

from __future__ import annotations

import json
import re
import subprocess
from uuid import uuid4

import pytest

from onyx.server.features.build.configs import SANDBOX_BACKEND
from onyx.server.features.build.configs import SANDBOX_PROXY_INJECTED_PLACEHOLDER
from onyx.server.features.build.configs import SandboxBackend
from onyx.server.features.build.sandbox.docker.docker_sandbox_manager import (
    SANDBOX_EXEC_USER,
)
from tests.integration.common_utils.managers.user import UserManager
from tests.integration.common_utils.test_models import DATestUser
from tests.integration.tests.craft.docker_e2e.conftest import DockerExec
from tests.integration.tests.craft.docker_e2e.conftest import DockerSandbox
from tests.integration.tests.craft.docker_e2e.conftest import ProvisionSandbox

pytestmark = pytest.mark.skipif(
    SANDBOX_BACKEND != SandboxBackend.DOCKER,
    reason="Docker integration tests require SANDBOX_BACKEND=docker.",
)

_PROXY_CA_ISSUER_RE = re.compile(r"CN=Onyx Sandbox Proxy CA")
_SANDBOX_BRIDGE_NETWORK = "onyx_craft_sandbox"


def _opencode_pid(container: str, docker_exec: DockerExec) -> int:
    proc = docker_exec(container, ["pgrep", "-f", "opencode serve"])
    pids = [int(p) for p in proc.stdout.split() if p.strip()]
    assert pids, (
        f"No opencode-serve PID in {container!r}; entrypoint likely crashed. Docker "
        f"logs:\n{docker_exec(container, ['cat', '/proc/1/status']).stdout}"
    )
    return pids[0]


@pytest.fixture(scope="module")
def module_user() -> DATestUser:
    return UserManager.create(name="craft_docker_module")


@pytest.fixture(scope="module")
def module_sandbox(
    module_user: DATestUser,
    provision_sandbox: ProvisionSandbox,
) -> DockerSandbox:
    return provision_sandbox(module_user)


def test_sandbox_runs_with_zero_caps_at_uid_1000(
    module_sandbox: DockerSandbox,
    docker_exec: DockerExec,
) -> None:
    _session_id, container = module_sandbox
    pid = _opencode_pid(container, docker_exec)

    status = docker_exec(container, ["cat", f"/proc/{pid}/status"]).stdout
    uid_line = next(line for line in status.splitlines() if line.startswith("Uid:"))
    cap_lines = {
        line.split(":")[0]: line
        for line in status.splitlines()
        if line.startswith(("CapInh:", "CapPrm:", "CapEff:", "CapBnd:", "CapAmb:"))
    }

    assert uid_line.split() == ["Uid:", "1000", "1000", "1000", "1000"], uid_line
    for key, line in cap_lines.items():
        mask = line.split()[1]
        assert mask == "0000000000000000", (
            f"{key} not empty for opencode pid {pid}: {line!r}"
        )


def test_sandbox_https_is_mitmd_by_proxy_ca(
    module_sandbox: DockerSandbox,
    docker_exec: DockerExec,
) -> None:
    _session_id, container = module_sandbox
    proc = docker_exec(
        container,
        ["curl", "-sS", "-v", "--max-time", "10", "https://example.com"],
        timeout=20.0,
    )
    issuer_line = next(
        (line for line in proc.stderr.splitlines() if "issuer:" in line),
        None,
    )
    assert issuer_line is not None, (
        f"No 'issuer:' line in curl -v output: {proc.stderr}"
    )
    assert _PROXY_CA_ISSUER_RE.search(issuer_line), (
        f"Issuer is not the proxy CA: {issuer_line!r}"
    )


def test_credentials_injected_on_wire_returns_real_user(
    module_user: DATestUser,
    module_sandbox: DockerSandbox,
    docker_exec: DockerExec,
) -> None:
    _session_id, container = module_sandbox

    env_check = docker_exec(container, ["sh", "-c", "echo $ONYX_PAT"])
    assert env_check.stdout.strip() == SANDBOX_PROXY_INJECTED_PLACEHOLDER, (
        f"ONYX_PAT in sandbox env was not the placeholder: {env_check.stdout!r}"
    )

    me_call = docker_exec(
        container,
        [
            "curl",
            "-sS",
            "-w",
            "\nHTTP %{http_code}",
            "-H",
            f"Authorization: Bearer {SANDBOX_PROXY_INJECTED_PLACEHOLDER}",
            "http://api_server:8080/me",
        ],
        timeout=15.0,
    )
    assert "HTTP 200" in me_call.stdout, f"/me did not return 200: {me_call.stdout!r}"
    body = me_call.stdout.split("\nHTTP ")[0]
    payload = json.loads(body)
    assert payload["id"] == module_user.id, (
        f"Injected PAT did not resolve to {module_user.id}: {payload!r}"
    )


def test_iptables_rejects_bypass_attempts(
    module_sandbox: DockerSandbox,
    docker_exec: DockerExec,
) -> None:
    _session_id, container = module_sandbox

    direct_api = docker_exec(
        container,
        [
            "curl",
            "-sS",
            "-o",
            "/dev/null",
            "--noproxy",
            "*",
            "--max-time",
            "5",
            "http://api_server:8080/me",
        ],
        timeout=10.0,
    )
    assert direct_api.returncode == 7, (
        f"direct api_server bypass not rejected: rc={direct_api.returncode} "
        f"stderr={direct_api.stderr!r}"
    )

    direct_internet = docker_exec(
        container,
        [
            "curl",
            "-sS",
            "-o",
            "/dev/null",
            "--noproxy",
            "*",
            "--max-time",
            "5",
            "https://1.1.1.1",
        ],
        timeout=10.0,
    )
    assert direct_internet.returncode == 7, "Direct external IP bypass not rejected."

    udp_dns = docker_exec(
        container,
        [
            "python3",
            "-c",
            (
                "import socket; "
                "s=socket.socket(socket.AF_INET, socket.SOCK_DGRAM); "
                "s.settimeout(5); "
                "s.sendto(b'\\x00\\x01\\x01\\x00\\x00\\x01\\x00\\x00\\x00\\x00\\x00\\x00"
                "\\x07example\\x03com\\x00\\x00\\x01\\x00\\x01', ('8.8.8.8', 53)); "
                "s.recvfrom(512)"
            ),
        ],
        timeout=10.0,
    )
    assert udp_dns.returncode != 0, (
        f"External DNS not blocked: stdout={udp_dns.stdout!r} stderr={udp_dns.stderr!r}"
    )
    assert (
        "Operation not permitted" in udp_dns.stderr
        or "PermissionError" in udp_dns.stderr
    )

    ipv6_egress = docker_exec(
        container,
        [
            "curl",
            "-sS",
            "-o",
            "/dev/null",
            "--noproxy",
            "*",
            "-6",
            "--max-time",
            "5",
            "https://ipv6.google.com",
        ],
        timeout=10.0,
    )
    assert ipv6_egress.returncode == 7, "IPv6 egress not blocked"

    # Docker's embedded resolver (127.0.0.11) must stay reachable so the sandbox
    # can resolve ``sandbox-proxy``.
    embedded_dns = docker_exec(
        container,
        ["getent", "ahosts", "example.com"],
        timeout=10.0,
    )
    assert embedded_dns.returncode == 0, (
        f"Docker embedded resolver should resolve example.com: {embedded_dns.stderr!r}"
    )


def test_unlabeled_container_gets_unidentified_sandbox_403() -> None:
    proc = subprocess.run(
        [
            "docker",
            "run",
            "--rm",
            "--network",
            _SANDBOX_BRIDGE_NETWORK,
            "curlimages/curl:latest",
            "-sS",
            "-o",
            "/dev/null",
            "-w",
            "%{http_code}",
            "--max-time",
            "10",
            "-x",
            "http://sandbox-proxy:8080",
            "http://api_server:8080/me",
        ],
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert proc.stdout.strip() == "403", f"Unlabeled bypass not 403: {proc.stdout!r}"

    proxy_logs = subprocess.run(
        ["docker", "logs", "--tail", "50", "onyx-sandbox-proxy-1"],
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )
    assert "identity_unknown_sandbox" in proxy_logs.stderr + proxy_logs.stdout, (
        f"Proxy did not log identity_unknown_sandbox warning. Recent "
        f"logs:\n{proxy_logs.stdout[-2000:]}"
    )


def test_sessions_directory_writable_by_sandbox_user(
    module_sandbox: DockerSandbox,
    docker_exec: DockerExec,
) -> None:
    _session_id, container = module_sandbox

    stat_result = docker_exec(container, ["stat", "-c", "%u:%g", "/workspace/sessions"])
    assert stat_result.returncode == 0, (
        f"/workspace/sessions stat failed: {stat_result.stderr}"
    )
    assert stat_result.stdout.strip() == "1000:1000", (
        f"/workspace/sessions not owned by 1000:1000: {stat_result.stdout.strip()}"
    )

    # docker exec defaults to root, not the setpriv-dropped agent user.
    test_dir = f"/workspace/sessions/test-{uuid4().hex[:8]}"
    mkdir_result = docker_exec(
        container,
        ["mkdir", "-p", test_dir],
        timeout=10.0,
        user=SANDBOX_EXEC_USER,
    )
    assert mkdir_result.returncode == 0, (
        f"mkdir failed as UID 1000: rc={mkdir_result.returncode} "
        f"stderr={mkdir_result.stderr!r}"
    )

    docker_exec(container, ["rm", "-rf", test_dir], user=SANDBOX_EXEC_USER)
