"""Docker-backend end-to-end approval-gate + posture tests.

Mirrors the K8s ``test_approval_gate.py`` (which lives at
``external_dependency_unit/craft/``) but runs as an **integration test**: the
full compose stack with the craft overlay must be up before pytest starts, and
assertions are made against the real api_server + sandbox-proxy + sandbox
containers via HTTP and ``docker exec``. The tier-up from external-dep-unit is
deliberate -- the docker-specific bug classes we catch here (image ENTRYPOINT
concat, HOME after setpriv, curl httpoxy interactions on the bridge) only
surface in the integrated provisioning flow.

Bring-up (handled by ``.github/workflows/pr-craft-compose-integration.yml``)::

    docker network create onyx_craft_sandbox
    docker volume create sandbox_proxy_ca
    docker compose \\
        -f docker-compose.yml \\
        -f docker-compose.dev.yml \\
        -f docker-compose.craft.yml \\
        --env-file env.template \\
        up -d --wait --wait-timeout 600

Skipped automatically when ``SANDBOX_BACKEND != docker`` so the file is a no-op
on the K8s lane.
"""

from __future__ import annotations

import json
import re
import subprocess
import time
from collections.abc import Generator
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
    """Finds the opencode-serve PID inside the sandbox.

    Returns the integer PID; raises with a diagnostic if not found. We rely on
    this to assert capability + uid invariants on the actual agent process, not
    the entrypoint shell.
    """
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
    """
    Starts a sandbox-side curl POST to ``chat.postMessage`` through the proxy
    and return the Popen. The bearer is intentionally fake; if the request
    reaches Slack it 401s. Caller drives the gate decision via the API while
    curl is parked, then ``communicate()``s to collect the result. Output body
    lands at ``/tmp/slack_out`` inside the sandbox.
    """
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
    """Polls the live-approvals HTTP endpoint until a pending row appears."""
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
    """POST APPROVE or REJECT via the decision API."""
    url = f"{API_SERVER_URL}/build/approvals/{approval_id}/decision"
    return client.post(
        url,
        json={"decision": decision.value},
        headers=user.headers,
        cookies=user.cookies,
    )


# ------------------------------------------------------------------------------
# Fixtures
# ------------------------------------------------------------------------------


@pytest.fixture(scope="module")
def module_user() -> DATestUser:
    """A user shared across the docker-posture tests (1-5).

    The K8s analogue gives each test its own user + sandbox. We share for the
    posture tests because they don't mutate any per-sandbox state -- they only
    read container properties. Tests that drive the gate flow (6-7) take their
    own fresh user via the ``gated_user`` fixture.
    """
    return UserManager.create(name="craft_docker_module")


@pytest.fixture(scope="module")
def module_sandbox(
    module_user: DATestUser,
    provision_sandbox: ProvisionSandbox,
) -> tuple[UUID, str]:
    """One sandbox provisioned via the real API; reused across posture tests."""
    return provision_sandbox(module_user)


@pytest.fixture
def gated_user() -> DATestUser:
    """Function-scoped user for the gate-flow tests -- each test gets its own
    session + sandbox so approval rows don't leak across tests."""
    return UserManager.create(name=f"craft_docker_gated_{uuid4().hex[:8]}")


@pytest.fixture
def gated_session(
    gated_user: DATestUser,
    provision_sandbox: ProvisionSandbox,
) -> Generator[tuple[DATestUser, UUID, str], None, None]:
    """Provisions a fresh sandbox via the real API for one gate-flow test."""
    session_id, container = provision_sandbox(gated_user)
    yield gated_user, session_id, container


# ------------------------------------------------------------------------------
# Tests 1-5: Docker-specific posture invariants
# ------------------------------------------------------------------------------


def test_sandbox_runs_with_zero_caps_at_uid_1000(
    module_sandbox: tuple[UUID, str],
    docker_exec: DockerExec,
) -> None:
    """
    The opencode-serve process must run as uid 1000 with an empty bounding set.
    This is the assertion that catches both the ENTRYPOINT-not-overridden bug
    (firewall-init.sh skipped -> process stays root) and the HOME-after- setpriv
    bug (opencode-serve never starts -> no pid to check).
    """
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
    """
    Public HTTPS gets MITM'd: leaf cert issued by the Onyx Sandbox Proxy CA.
    Proves the firewall-init.sh CA-install step + the iptables proxy-allow rule
    + the proxy's MITM both work end-to-end.
    """
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
    """
    Sandbox env carries the placeholder PAT; calling api_server/me via the proxy
    returns the REAL user record (proves the proxy substituted the bearer header
    from ``Sandbox.encrypted_pat``).
    """
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
    """
    All four bypass classes are kernel-level rejected; the loopback embedded
    resolver stays reachable by design (compose-internal name resolution).
    """
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

    # By-design exception: Docker's embedded resolver at 127.0.0.11 is reachable
    # via the loopback ACCEPT rule. Required so the sandbox can resolve
    # ``sandbox-proxy``. Asserting positively so a future "close all DNS"
    # over-correction would fail this test.
    embedded_dns = docker_exec(
        container,
        ["getent", "ahosts", "example.com"],
        timeout=10.0,
    )
    assert embedded_dns.returncode == 0, (
        f"Docker embedded resolver should resolve example.com: {embedded_dns.stderr!r}"
    )


def test_unlabeled_container_gets_unidentified_sandbox_403() -> None:
    """
    A non-sandbox container on the bridge that hits the proxy must get a 403 + a
    ``identity_unknown_sandbox`` warning in the proxy logs. Proves
    DockerEventsLookup rejects unknown source IPs and the observability hook we
    added in branch 6 still fires.
    """
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
    """
    The /workspace/sessions volume mount must be writable by UID 1000.

    Regression test: Docker volumes are created with root:root ownership.
    firewall-init.sh must chown the directory before dropping to UID 1000,
    otherwise session workspace creation fails with EACCES.

    This test verifies that UID 1000 can create a test directory inside
    /workspace/sessions, proving the permissions fix in firewall-init.sh
    works correctly.
    """
    _session_id, container = module_sandbox

    # Verify /workspace/sessions exists and is owned by 1000:1000
    stat_result = docker_exec(container, ["stat", "-c", "%u:%g", "/workspace/sessions"])
    assert stat_result.returncode == 0, (
        f"/workspace/sessions stat failed: {stat_result.stderr}"
    )
    assert stat_result.stdout.strip() == "1000:1000", (
        f"/workspace/sessions not owned by 1000:1000: {stat_result.stdout.strip()}"
    )

    # Attempt to create a test directory as UID 1000. Must set the exec user
    # explicitly because in proxy mode docker exec defaults to the container's
    # configured root user, not the setpriv-dropped agent user.
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


# ------------------------------------------------------------------------------
# Tests 6-7: Gate APPROVE / REJECT flow (analogues of K8s test_approval_gate)
#
# Depend on the ``slack_external_app`` fixture so the proxy's
# ``ExternalAppActionMatcher`` actually claims ``chat.postMessage``. Without
# that seeding the matcher returns ``None``, the request leaves the proxy with
# ``policy=off_catalog``, and no approval ever parks. The default deployment has
# no external apps configured and the K8s lane's ``test_approval_gate.py`` isn't
# actually run by its CI (verified -- not in the lane's ``paths:`` filter or
# pytest args), so this fixture is the first place to wire the seeding in.
# ------------------------------------------------------------------------------


def test_approve_decision_forwards_to_slack(
    slack_external_app: None,  # noqa: ARG001 -- side-effect fixture
    gated_session: tuple[DATestUser, UUID, str],
    docker_exec: DockerExec,
) -> None:
    """
    A gated Slack request parks at the proxy, becomes a pending ActionApproval,
    and on APPROVE the proxy forwards upstream. Mirrors K8s
    ``test_approved_decision_forwards_to_slack``.

    The fake bearer means Slack returns ``invalid_auth`` once the request
    actually reaches it -- evidence the forward fired (vs. the gate having
    short-circuited).
    """
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
    """
    REJECT causes the parked sandbox-side curl to return a 403 carrying the
    ``USER_REJECTED_ACTION`` error code. Mirrors K8s
    ``test_rejected_decision_returns_403_user_rejected``.
    """
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
    """ASKs on an app whose auth template can't be filled forwards bare.

    Documents the credential gate's short-circuit: With no credentials to inject
    after approval, the gate skips the ASK prompt and forwards the request
    as-is. Mirrors K8s ``test_ask_with_uninvokable_app_forwards_bare``.
    """
    user, session_id, container = gated_session

    # Strip Slack's org credential so app_is_available -> False.
    with get_session_with_tenant(tenant_id="public") as db:
        app = get_built_in_external_app(db, ExternalAppType.SLACK)
        assert app is not None, "slack_external_app fixture must seed the row"
        app.organization_credentials = {}  # ty: ignore[invalid-assignment]
        db.commit()

    try:
        curl_proc = _start_slack_post_via_proxy(container, session_id)
        try:
            stdout, _stderr = curl_proc.communicate(timeout=60)
            # Slack returns HTTP 200 with `invalid_auth` in the body for the
            # fake bearer -- the 200 + body is the proof the request actually
            # reached slack.com bare (no injection from the gate).
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
        # Restore the seeded fake token so sibling tests still gate.
        with get_session_with_tenant(tenant_id="public") as db:
            app = get_built_in_external_app(db, ExternalAppType.SLACK)
            assert app is not None
            app.organization_credentials = {  # ty: ignore[invalid-assignment]
                "access_token": "fake-test-token"
            }
            db.commit()
