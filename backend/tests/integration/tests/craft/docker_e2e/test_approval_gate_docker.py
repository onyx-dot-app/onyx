"""Docker-backend end-to-end approval-gate decision tests."""

from __future__ import annotations

import json
import subprocess
from typing import NamedTuple
from uuid import UUID
from uuid import uuid4

import pytest
from httpx import Response

from onyx.db.engine.sql_engine import get_session_with_tenant
from onyx.db.enums import ApprovalDecision
from onyx.db.enums import ExternalAppType
from onyx.db.external_app import get_built_in_external_app
from onyx.server.features.build.configs import SANDBOX_BACKEND
from onyx.server.features.build.configs import SandboxBackend
from tests.integration.common_utils.constants import API_SERVER_URL
from tests.integration.common_utils.http_client import client
from tests.integration.common_utils.managers.build_approvals import (
    BuildApprovalsManager,
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


class DockerGatedSession(NamedTuple):
    user: DATestUser
    session_id: UUID
    container_name: str


_SLACK_POST_MESSAGE_URL = "https://slack.com/api/chat.postMessage"


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
def gated_user() -> DATestUser:
    return UserManager.create(name=f"craft_docker_gated_{uuid4().hex[:8]}")


@pytest.fixture(scope="module")
def gated_module_sandbox(
    gated_user: DATestUser,
    provision_sandbox: ProvisionSandbox,
) -> DockerSandbox:
    # Sandboxes are per-user, so every later ``gated_session`` mint reuses this
    # RUNNING container instead of paying the ~40s provisioning cost again.
    return provision_sandbox(gated_user)


@pytest.fixture
def gated_session(
    gated_user: DATestUser,
    gated_module_sandbox: DockerSandbox,
    provision_sandbox: ProvisionSandbox,
) -> DockerGatedSession:
    # Reuses the gated user's already-RUNNING container; only the build-session
    # row -- and thus the proxy tag / approval session id -- is new per test.
    result = provision_sandbox(gated_user)
    assert result.container_name == gated_module_sandbox.container_name, (
        "gated_session minted a new container instead of reusing the module "
        f"sandbox: {result.container_name!r} != "
        f"{gated_module_sandbox.container_name!r}"
    )
    return DockerGatedSession(
        user=gated_user,
        session_id=result.session_id,
        container_name=result.container_name,
    )


# Gate-flow tests depend on the ``slack_external_app`` fixture.
#  They also share one module-scoped sandbox (``gated_module_sandbox``),
# so the credential-mutating ``test_ask_*`` case below is defined LAST
# and additionally save/restores the Slack row's credentials around its mutation


def _set_slack_org_credentials(value: dict[str, str]) -> None:
    with get_session_with_tenant(tenant_id="public") as db:
        app = get_built_in_external_app(db, ExternalAppType.SLACK)
        assert app is not None, "slack_external_app fixture must seed the row"
        app.organization_credentials = value  # ty: ignore[invalid-assignment]
        db.commit()


def test_approve_decision_forwards_to_slack(
    slack_external_app: None,  # noqa: ARG001 -- side-effect fixture
    gated_session: DockerGatedSession,
    docker_exec: DockerExec,
) -> None:
    user, session_id, container = gated_session

    curl_proc = _start_slack_post_via_proxy(container, session_id)

    try:
        approval = BuildApprovalsManager.wait_for_pending(
            user, session_id, timeout_s=30.0
        )
        resp = _post_decision(
            user, str(approval.approval_id), ApprovalDecision.APPROVED
        )
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
    gated_session: DockerGatedSession,
    docker_exec: DockerExec,
) -> None:
    user, session_id, container = gated_session

    curl_proc = _start_slack_post_via_proxy(container, session_id)

    try:
        approval = BuildApprovalsManager.wait_for_pending(
            user, session_id, timeout_s=30.0
        )
        resp = _post_decision(
            user, str(approval.approval_id), ApprovalDecision.REJECTED
        )
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
    gated_session: DockerGatedSession,
    docker_exec: DockerExec,
) -> None:
    user, session_id, container = gated_session

    # Snapshot the row so the strip below is restored exactly, no matter what
    # the fixture seeded -- the approve/reject siblings share this row.
    with get_session_with_tenant(tenant_id="public") as db:
        app = get_built_in_external_app(db, ExternalAppType.SLACK)
        assert app is not None, "slack_external_app fixture must seed the row"
        saved_credentials = dict(
            app.organization_credentials.get_value(apply_mask=False) or {}
        )

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
