"""Docker-backend end-to-end approval-gate + posture tests."""

from __future__ import annotations

import json
import re
import subprocess
import time
from typing import Any
from uuid import UUID
from uuid import uuid4

import pytest
from httpx import Response

from onyx.db.engine.sql_engine import get_session_with_tenant
from onyx.db.enums import ApprovalDecision
from onyx.db.enums import ExternalAppType
from onyx.db.external_app import get_built_in_external_app
from onyx.server.features.build.configs import SANDBOX_BACKEND
from onyx.server.features.build.configs import SANDBOX_PROXY_INJECTED_PLACEHOLDER
from onyx.server.features.build.configs import SandboxBackend
from onyx.server.features.build.sandbox.docker.docker_sandbox_manager import (
    SANDBOX_EXEC_USER,
)
from tests.integration.common_utils.constants import API_SERVER_URL
from tests.integration.common_utils.http_client import client
from tests.integration.common_utils.managers.user import UserManager
from tests.integration.common_utils.test_models import DATestUser
from tests.integration.tests.craft.docker_e2e.conftest import DockerExec
from tests.integration.tests.craft.docker_e2e.conftest import ProvisionSandbox

pytestmark = pytest.mark.skipif(
    SANDBOX_BACKEND != SandboxBackend.DOCKER,
    reason="Docker integration tests require SANDBOX_BACKEND=docker.",
)

_SLACK_POST_MESSAGE_URL = "https://slack.com/api/chat.postMessage"
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


def _start_slack_post_via_proxy(
    container: str, session_id: UUID
) -> subprocess.Popen[str]:
    cmd = (
        f"curl -sS -X POST "
        f"-H 'Authorization: Bearer xoxb-fake' "
        f"-H 'Content-Type: application/json' "
        f"--data '{json.dumps({'channel': '#general', 'text': 'hi'})}' "
        f"-x 'http://{session_id}:x@sandbox-proxy:8080' "
        f"--max-time 60 "
        f"-o /tmp/slack_out -w '%{{http_code}}' {_SLACK_POST_MESSAGE_URL}"
    )
    return subprocess.Popen(  # noqa: S603
        ["docker", "exec", container, "sh", "-c", cmd],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )


def _wait_for_pending_approval(
    user: DATestUser, session_id: UUID, timeout_s: float = 30.0
) -> dict[str, Any]:
    deadline = time.monotonic() + timeout_s
    url = f"{API_SERVER_URL}/build/approvals/sessions/{session_id}/live"
    while time.monotonic() < deadline:
        resp = client.get(url, headers=user.headers, cookies=user.cookies)
        resp.raise_for_status()
        items = resp.json().get("items", [])
        if items:
            return items[0]
        time.sleep(0.5)
    raise AssertionError(
        f"No pending approval surfaced for session {session_id} within {timeout_s}s."
    )


def _post_decision(
    user: DATestUser, approval_id: str, decision: ApprovalDecision
) -> Response:
    url = f"{API_SERVER_URL}/build/approvals/{approval_id}/decision"
    return client.post(
        url,
        json={"decision": decision.value},
        headers=user.headers,
        cookies=user.cookies,
    )


@pytest.fixture(scope="module")
def module_user() -> DATestUser:
    return UserManager.create(name="craft_docker_module")


@pytest.fixture(scope="module")
def module_sandbox(
    module_user: DATestUser,
    provision_sandbox: ProvisionSandbox,
) -> tuple[UUID, str]:
    return provision_sandbox(module_user)


@pytest.fixture(scope="module")
def gated_user() -> DATestUser:
    return UserManager.create(name=f"craft_docker_gated_{uuid4().hex[:8]}")


@pytest.fixture(scope="module")
def gated_module_sandbox(
    gated_user: DATestUser,
    provision_sandbox: ProvisionSandbox,
) -> str:
    # Sandboxes are per-user, so every later ``gated_session`` mint reuses this
    # RUNNING container instead of paying the ~40s provisioning cost again.
    _session_id, container = provision_sandbox(gated_user)
    return container


@pytest.fixture
def gated_session(
    gated_user: DATestUser,
    gated_module_sandbox: str,
    provision_sandbox: ProvisionSandbox,
) -> tuple[DATestUser, UUID, str]:
    # Reuses the gated user's already-RUNNING container; only the build-session
    # row -- and thus the proxy tag / approval session id -- is new per test.
    session_id, container = provision_sandbox(gated_user)
    assert container == gated_module_sandbox, (
        "gated_session minted a new container instead of reusing the module "
        f"sandbox: {container!r} != {gated_module_sandbox!r}"
    )
    return gated_user, session_id, container


def test_sandbox_runs_with_zero_caps_at_uid_1000(
    module_sandbox: tuple[UUID, str],
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
    module_sandbox: tuple[UUID, str],
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
    module_sandbox: tuple[UUID, str],
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
    module_sandbox: tuple[UUID, str],
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
    module_sandbox: tuple[UUID, str],
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


# Gate-flow tests depend on the ``slack_external_app`` fixture; without it the
# matcher claims nothing and no approval parks. They also share one
# module-scoped sandbox (``gated_module_sandbox``), so the credential-mutating
# ``test_ask_*`` case below is defined LAST and additionally save/restores the
# Slack row's credentials around its mutation -- two independent guards so it
# can never strip the token the approve/reject siblings rely on to gate.


def _set_slack_org_credentials(value: dict[str, str]) -> None:
    with get_session_with_tenant(tenant_id="public") as db:
        app = get_built_in_external_app(db, ExternalAppType.SLACK)
        assert app is not None, "slack_external_app fixture must seed the row"
        app.organization_credentials = value  # ty: ignore[invalid-assignment]
        db.commit()


def _get_slack_org_credentials() -> dict[str, str]:
    with get_session_with_tenant(tenant_id="public") as db:
        app = get_built_in_external_app(db, ExternalAppType.SLACK)
        assert app is not None, "slack_external_app fixture must seed the row"
        return dict(app.organization_credentials or {})


def test_approve_decision_forwards_to_slack(
    slack_external_app: None,  # noqa: ARG001 -- side-effect fixture
    gated_session: tuple[DATestUser, UUID, str],
    docker_exec: DockerExec,
) -> None:
    user, session_id, container = gated_session

    curl_proc = _start_slack_post_via_proxy(container, session_id)

    try:
        approval = _wait_for_pending_approval(user, session_id, timeout_s=30.0)
        resp = _post_decision(user, approval["approval_id"], ApprovalDecision.APPROVED)
        assert resp.status_code == 200, (
            f"APPROVE failed: {resp.status_code} {resp.text!r}"
        )

        stdout, _stderr = curl_proc.communicate(timeout=60)
        http_code = stdout.strip()
        assert http_code in ("200", "401"), (
            f"Forwarded curl did not return slack response (got {http_code!r})."
        )

        body = docker_exec(container, ["cat", "/tmp/slack_out"]).stdout
        payload = json.loads(body)
        assert payload.get("ok") is False
        assert payload.get("error") == "invalid_auth", (
            f"Slack did not 401 our fake bearer: {payload!r}"
        )
    finally:
        curl_proc.kill()


def test_reject_decision_returns_403_user_rejected(
    slack_external_app: None,  # noqa: ARG001 -- side-effect fixture
    gated_session: tuple[DATestUser, UUID, str],
    docker_exec: DockerExec,
) -> None:
    user, session_id, container = gated_session

    curl_proc = _start_slack_post_via_proxy(container, session_id)

    try:
        approval = _wait_for_pending_approval(user, session_id, timeout_s=30.0)
        resp = _post_decision(user, approval["approval_id"], ApprovalDecision.REJECTED)
        assert resp.status_code == 200, (
            f"REJECT failed: {resp.status_code} {resp.text!r}"
        )

        stdout, _stderr = curl_proc.communicate(timeout=60)
        assert stdout.strip() == "403", (
            f"Rejected forward did not return 403: {stdout!r}"
        )

        body = docker_exec(container, ["cat", "/tmp/slack_out"]).stdout
        payload = json.loads(body)
        assert payload.get("error") == "user_rejected", (
            f"Expected error='user_rejected', got {payload!r}"
        )
    finally:
        curl_proc.kill()


def test_ask_with_uninvokable_app_forwards_bare(
    slack_external_app: None,  # noqa: ARG001 -- side-effect fixture
    gated_session: tuple[DATestUser, UUID, str],
    docker_exec: DockerExec,
) -> None:
    user, session_id, container = gated_session

    # Snapshot the row so the strip below is restored exactly, no matter what
    # the fixture seeded -- the approve/reject siblings share this row.
    saved_credentials = _get_slack_org_credentials()

    # Strip Slack's org credential so app_is_available -> False.
    _set_slack_org_credentials({})

    try:
        curl_proc = _start_slack_post_via_proxy(container, session_id)
        try:
            stdout, _stderr = curl_proc.communicate(timeout=60)
            assert stdout.strip() == "200", (
                "Uninvokable ASK should forward bare to Slack and Slack should "
                f"200 with invalid_auth in the body, got {stdout!r}"
            )
            body = docker_exec(container, ["cat", "/tmp/slack_out"]).stdout
            payload = json.loads(body)
            assert payload.get("error") == "invalid_auth", (
                f"Bare-forwarded request should reach slack.com and get "
                f"invalid_auth, got {payload!r}"
            )

            live_url = f"{API_SERVER_URL}/build/approvals/sessions/{session_id}/live"
            resp = client.get(live_url, headers=user.headers, cookies=user.cookies)
            resp.raise_for_status()
            assert resp.json().get("items") == [], (
                "Uninvokable ASK must not mint an approval row."
            )
        finally:
            curl_proc.kill()
    finally:
        # Restore the seeded credential so sibling tests still gate.
        _set_slack_org_credentials(saved_credentials)
