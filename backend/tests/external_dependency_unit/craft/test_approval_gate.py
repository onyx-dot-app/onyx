"""Approval-gate end-to-end (real proxy + Redis + sandbox pod + Postgres).

Gated to the K8s CI lane via ``pytestmark`` — never run locally (touches the
real cluster). Each test provisions a sandbox pod, seeds a User + BuildSession,
drives a real sandbox-side curl against slack.com tagged with the session id (as
the opencode plugin does in production), and asserts the ApprovalDecision flow.
Complements the in-process ``test_approvals_api.py`` by exercising the real
proxy/Redis/SIGTERM-drain paths.

Run with::

    SANDBOX_BACKEND=kubernetes python -m dotenv -f .vscode/.env run -- \\
        pytest backend/tests/external_dependency_unit/craft/test_approval_gate.py -v
"""

from __future__ import annotations

import json
import time
from datetime import datetime
from datetime import timedelta
from datetime import timezone
from typing import Generator
from uuid import UUID
from uuid import uuid4

import pytest
from kubernetes import client
from sqlalchemy import select
from sqlalchemy import text
from sqlalchemy import update
from sqlalchemy.orm import Session

from onyx.cache.factory import get_cache_backend
from onyx.configs.constants import NotificationType
from onyx.db.engine.sql_engine import get_session_with_current_tenant
from onyx.db.engine.sql_engine import SqlEngine
from onyx.db.enums import ApprovalDecision
from onyx.db.enums import BuildSessionStatus
from onyx.db.enums import EndpointPolicy
from onyx.db.enums import ExternalAppType
from onyx.db.external_app import create_external_app
from onyx.db.external_app import get_built_in_external_app
from onyx.db.models import ActionApproval
from onyx.db.models import BuildSession
from onyx.db.models import Notification
from onyx.db.models import Sandbox
from onyx.db.models import User
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.sandbox_proxy import approval_cache
from onyx.server.features.build.approvals.api import DecisionBody
from onyx.server.features.build.approvals.api import list_live_approvals
from onyx.server.features.build.approvals.api import submit_decision
from onyx.server.features.build.configs import SANDBOX_BACKEND
from onyx.server.features.build.configs import SANDBOX_NAMESPACE
from onyx.server.features.build.configs import SANDBOX_PROXY_NAMESPACE
from onyx.server.features.build.configs import SANDBOX_PROXY_PORT
from onyx.server.features.build.configs import SandboxBackend
from onyx.utils.logger import setup_logger
from shared_configs.contextvars import CURRENT_TENANT_ID_CONTEXTVAR
from tests.external_dependency_unit.constants import TEST_TENANT_ID
from tests.external_dependency_unit.craft._test_helpers import action_entry
from tests.external_dependency_unit.craft.conftest import pod_exec
from tests.external_dependency_unit.craft.conftest import pod_exec_async
from tests.external_dependency_unit.craft.conftest import wait_for_pod_exec_output
from tests.external_dependency_unit.craft.conftest import wait_for_proxy_redeploy

logger = setup_logger()

pytestmark = pytest.mark.skipif(
    SANDBOX_BACKEND != SandboxBackend.KUBERNETES,
    reason="K8s tests require SANDBOX_BACKEND=kubernetes; run in the dedicated K8s CI job.",
)

# Label the helm chart attaches to the proxy Deployment + pods.
_PROXY_COMPONENT_LABEL = "app.kubernetes.io/component=sandbox-proxy"

# Matches catalog action ``slack.messages.write``.
_SLACK_POST_MESSAGE_URL = "https://slack.com/api/chat.postMessage"

# Spec value for approval_cache.WAIT_TIMEOUT_S; pinned by
# test_wait_timeout_constant_matches_spec.
_WAIT_TIMEOUT_S_SPEC = 180


@pytest.fixture(scope="module", autouse=True)
def _seed_slack_external_app() -> Generator[None, None, None]:
    """
    Seeds an enabled Slack ``external_app`` so the matcher claims
    ``chat.postMessage``. The K8s lane doesn't auto-provision
    (``AUTO_PROVISION_DEFAULT_EXTERNAL_APPS`` defaults off and only fires in MT
    tenant provisioning), so without this row every test below would 404 the
    matcher and never park an approval.

    Survives the per-test ``_isolate_skill_tables`` snapshot/restore because it
    commits before the first test in this module runs -- the isolation fixture's
    baseline captures it and restores it after each test. Idempotent: skips if a
    Slack row already exists.
    """
    SqlEngine.init_engine(pool_size=10, max_overflow=5)
    token = CURRENT_TENANT_ID_CONTEXTVAR.set(TEST_TENANT_ID)
    try:
        with get_session_with_current_tenant() as session:
            if get_built_in_external_app(session, ExternalAppType.SLACK) is None:
                create_external_app(
                    db_session=session,
                    name="Slack",
                    description="Slack integration for gate-flow K8s tests.",
                    bundle_file_id="",
                    bundle_sha256="",
                    app_type=ExternalAppType.SLACK,
                    upstream_url_patterns=["https://slack\\.com/api/.*"],
                    auth_template={"Authorization": "Bearer {access_token}"},
                    # Fake token. An unfillable template short-circuits the ASK
                    # gate (forwards bare, no DB row), which breaks every
                    # gate-flow test below. ``test_ask_with_uninvokable_app_
                    # forwards_bare`` strips this back out to exercise that
                    # short-circuit path.
                    organization_credentials={"access_token": "fake-test-token"},
                    enabled=True,
                    is_public=True,
                    action_policies={"slack.messages.write": EndpointPolicy.ASK},
                )
                session.commit()
        yield
    finally:
        CURRENT_TENANT_ID_CONTEXTVAR.reset(token)


def _post_slack_via_curl(
    k8s: client.CoreV1Api,
    pod_name: str,
    output_path: str,
    *,
    text: str = "approval test",
    max_time_s: int = 240,
    session_id: UUID | None = None,
) -> None:
    """Drives a sandbox-side curl against Slack's chat.postMessage.

    The bearer is intentionally fake — Slack responds ``invalid_auth`` if the
    request reaches it (relied on by the APPROVED test). ``session_id`` tags the
    egress so the gate resolves the session; omit it for the untagged
    fail-closed path.
    """
    pod_exec_async(
        k8s,
        pod_name,
        SANDBOX_NAMESPACE,
        _SLACK_POST_MESSAGE_URL,
        output_path,
        headers={
            "Authorization": "Bearer xoxb-fake-test-token",
            "Content-Type": "application/json",
        },
        body=json.dumps({"channel": "#general", "text": text}),
        max_time_s=max_time_s,
        proxy_session_id=str(session_id) if session_id is not None else None,
    )


def _wait_for_pending_approval(
    db_session: Session, session_id: UUID, timeout_s: float = 30
) -> ActionApproval:
    """
    Polls until a pending (``decision IS NULL``) row exists for ``session_id``.

    The proxy commits the row asynchronously, so we must observe it before
    submitting a decision.
    """
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        row = (
            db_session.query(ActionApproval)
            .filter(ActionApproval.session_id == session_id)
            .filter(ActionApproval.decision.is_(None))
            .order_by(ActionApproval.created_at.desc())
            .first()
        )
        if row is not None:
            return row
        db_session.expire_all()
        time.sleep(0.5)
    raise RuntimeError(
        f"No pending approval row appeared for session {session_id} within "
        f"{timeout_s:.1f}s"
    )


def _approval_count_for_user(db_session: Session, user_id: UUID) -> int:
    """
    Counts approvals across every session owned by ``user_id``.

    Wider than per-session so a gate bug minting under a different session_id
    still trips the assertion.
    """
    db_session.expire_all()
    return (
        db_session.query(ActionApproval)
        .join(BuildSession, ActionApproval.session_id == BuildSession.id)
        .filter(BuildSession.user_id == user_id)
        .count()
    )


def _find_proxy_pod_name(k8s: client.CoreV1Api) -> str:
    """Returns the name of one running sandbox-proxy pod.

    Assumes ``replicas == 1`` (helm chart default). If scaled higher we return
    an arbitrary ``items[0]``, and the SIGTERM-drain test would only drain that
    one replica.
    """
    pods = k8s.list_namespaced_pod(
        namespace=SANDBOX_PROXY_NAMESPACE,
        label_selector=_PROXY_COMPONENT_LABEL,
    )
    items = pods.items or []
    if not items:
        raise RuntimeError(
            f"No sandbox-proxy pods found in namespace "
            f"{SANDBOX_PROXY_NAMESPACE!r} (selector={_PROXY_COMPONENT_LABEL!r})"
        )
    return str(items[0].metadata.name)


def _find_proxy_pod_ip(k8s: client.CoreV1Api) -> str:
    """Returns the pod IP of one running sandbox-proxy pod.

    The rogue pod in test_unidentified_sandbox_403_from_non_sandbox_pod needs
    this — it can't resolve the ``sandbox-proxy`` host alias the real sandbox
    spec installs.
    """
    pods = k8s.list_namespaced_pod(
        namespace=SANDBOX_PROXY_NAMESPACE,
        label_selector=_PROXY_COMPONENT_LABEL,
    )
    for pod in pods.items or []:
        if pod.status and pod.status.pod_ip:
            return str(pod.status.pod_ip)
    raise RuntimeError(
        f"No sandbox-proxy pod with a pod_ip found in namespace "
        f"{SANDBOX_PROXY_NAMESPACE!r} (selector={_PROXY_COMPONENT_LABEL!r})"
    )


def _assert_403_error_code(body: str, expected_code: str) -> None:
    """
    Asserts a 403 body carries the expected error code, ignoring JSON
    whitespace.
    """
    normalized = body.replace(" ", "")
    assert f'"error":"{expected_code}"' in normalized, (
        f"Expected error_code={expected_code!r} in body, got: {body!r}"
    )


@pytest.fixture(scope="function")
def gated_session(
    db_session: Session,
    live_pod: tuple[UUID, UUID, str],
) -> Generator[tuple[User, UUID, str], None, None]:
    """Seeds an ACTIVE ``BuildSession`` matching ``live_pod``'s ids.

    ``live_pod`` provisions a sandbox backed by committed ``User`` + ``Sandbox``
    rows (see ``_provisioned_sandbox``), so the owner is read from the sandbox
    row rather than seeded here. ``live_pod``'s teardown deletes those rows; FK
    ``ondelete=CASCADE`` drops the related build_session / action_approval /
    notification rows, so this fixture has nothing to tear down.

    No explicit ``tenant_context`` dependency: ``k8s_manager`` (via
    ``live_pod``) already sets ``CURRENT_TENANT_ID_CONTEXTVAR`` before this body
    runs. If that behaviour is removed this fixture breaks silently.
    """
    sandbox_id, session_id, pod_name = live_pod

    sandbox = db_session.get(Sandbox, sandbox_id)
    assert sandbox is not None, "live_pod must back its sandbox with a committed row"
    user = db_session.get(User, sandbox.user_id)
    assert user is not None

    # Drop stale BuildSession rows so the seeded row is the single deterministic
    # one the gate resolves the curl's session tag against.
    db_session.query(BuildSession).filter(BuildSession.user_id == user.id).delete(
        synchronize_session=False
    )
    db_session.commit()

    row = BuildSession(
        id=session_id,
        user_id=user.id,
        name="approval-gate-test-session",
        status=BuildSessionStatus.ACTIVE,
    )
    db_session.add(row)
    db_session.commit()
    db_session.refresh(row)

    yield user, session_id, pod_name


def test_rejected_decision_returns_403_user_rejected(
    k8s_manager: object,  # noqa: ARG001 — required to construct live_pod
    k8s_client: client.CoreV1Api,
    gated_session: tuple[User, UUID, str],
    db_session: Session,
) -> None:
    """REJECTED decision → proxy writes 403 ``user_rejected`` to the sandbox."""
    user, session_id, pod_name = gated_session

    output_path = f"/tmp/curl_reject_{uuid4().hex[:8]}"
    _post_slack_via_curl(
        k8s_client,
        pod_name,
        output_path,
        text="hello from K8s CI",
        session_id=session_id,
    )

    pending = _wait_for_pending_approval(db_session, session_id)

    response = submit_decision(
        approval_id=pending.approval_id,
        body=DecisionBody(decision=ApprovalDecision.REJECTED),
        user=user,
        db_session=db_session,
    )
    assert response.decision == ApprovalDecision.REJECTED
    assert response.approval_id == pending.approval_id

    status_code, body = wait_for_pod_exec_output(
        k8s_client, pod_name, output_path, timeout_s=30
    )
    assert status_code == 403, (
        f"sandbox-side curl should see 403, got {status_code}: {body!r}"
    )
    _assert_403_error_code(body, "user_rejected")


def test_approved_decision_forwards_to_slack(
    k8s_manager: object,  # noqa: ARG001
    k8s_client: client.CoreV1Api,
    gated_session: tuple[User, UUID, str],
    db_session: Session,
) -> None:
    """APPROVED → proxy forwards to Slack.

    Slack's 200 + ``invalid_auth`` body (the fake bearer can't validate) is the
    proof the request actually reached slack.com.
    """
    user, session_id, pod_name = gated_session

    output_path = f"/tmp/curl_approve_{uuid4().hex[:8]}"
    _post_slack_via_curl(
        k8s_client, pod_name, output_path, text="forwarded", session_id=session_id
    )

    pending = _wait_for_pending_approval(db_session, session_id)

    response = submit_decision(
        approval_id=pending.approval_id,
        body=DecisionBody(decision=ApprovalDecision.APPROVED),
        user=user,
        db_session=db_session,
    )
    assert response.decision == ApprovalDecision.APPROVED

    status_code, body = wait_for_pod_exec_output(
        k8s_client, pod_name, output_path, timeout_s=45
    )
    assert status_code == 200, (
        f"Forwarded request should hit Slack and return 200 (Slack will say "
        f"invalid_auth in the body). Got {status_code}: {body!r}"
    )
    assert "invalid_auth" in body.strip(), (
        f"Slack should respond with 'invalid_auth' for the fake bearer "
        f"(proof the request actually reached slack.com): {body!r}"
    )


@pytest.mark.slow
def test_expired_on_wait_timeout(
    k8s_manager: object,  # noqa: ARG001
    k8s_client: client.CoreV1Api,
    gated_session: tuple[User, UUID, str],
    db_session: Session,
) -> None:
    """No decision → proxy claims EXPIRED after ``WAIT_TIMEOUT_S``.

    curl's --max-time must outlive the spec window so we see the proxy's 403
    rather than the client tearing down first.
    """
    user, session_id, pod_name = gated_session

    output_path = f"/tmp/curl_expire_{uuid4().hex[:8]}"
    _post_slack_via_curl(
        k8s_client,
        pod_name,
        output_path,
        text="never decided",
        max_time_s=_WAIT_TIMEOUT_S_SPEC + 60,
        session_id=session_id,
    )

    pending = _wait_for_pending_approval(db_session, session_id)

    status_code, body = wait_for_pod_exec_output(
        k8s_client, pod_name, output_path, timeout_s=_WAIT_TIMEOUT_S_SPEC + 30
    )
    assert status_code == 403, (
        f"sandbox-side curl after timeout should see 403, got {status_code}: {body!r}"
    )
    _assert_403_error_code(body, "not_authorized")

    db_session.expire_all()
    refreshed = db_session.get(ActionApproval, pending.approval_id)
    assert refreshed is not None
    assert refreshed.decision == ApprovalDecision.EXPIRED


def test_wait_timeout_constant_matches_spec() -> None:
    """``approval_cache.WAIT_TIMEOUT_S`` must equal the value tests assume."""
    assert approval_cache.WAIT_TIMEOUT_S == _WAIT_TIMEOUT_S_SPEC


def test_sigterm_drain_unblocks_parked_request(
    k8s_manager: object,  # noqa: ARG001
    k8s_client: client.CoreV1Api,
    gated_session: tuple[User, UUID, str],
    db_session: Session,
) -> None:
    """Deleting the parked proxy pod must drain → wake → EXPIRED.

    Without the drain hook the curl would hang until ``WAIT_TIMEOUT_S``; we
    assert it unblocks well inside that window.
    """
    _, session_id, pod_name = gated_session

    output_path = f"/tmp/curl_drain_{uuid4().hex[:8]}"
    _post_slack_via_curl(
        k8s_client, pod_name, output_path, text="drain me", session_id=session_id
    )

    _wait_for_pending_approval(db_session, session_id)

    # Don't wait for graceful termination — the proxy's SIGTERM drain coroutine
    # is what should fire the wakes.
    proxy_pod_name = _find_proxy_pod_name(k8s_client)
    logger.info("test deleting proxy pod %s", proxy_pod_name)
    k8s_client.delete_namespaced_pod(
        name=proxy_pod_name,
        namespace=SANDBOX_PROXY_NAMESPACE,
    )

    try:
        status_code, body = wait_for_pod_exec_output(
            k8s_client, pod_name, output_path, timeout_s=45
        )
        assert status_code == 403, (
            f"sandbox-side curl should unblock with 403 after proxy drain, "
            f"got {status_code}: {body!r}"
        )
        _assert_403_error_code(body, "not_authorized")

        db_session.expire_all()
        rows = (
            db_session.query(ActionApproval)
            .filter(ActionApproval.session_id == session_id)
            .all()
        )
        assert rows, "Expected an approval row to exist after drain."
        assert all(r.decision == ApprovalDecision.EXPIRED for r in rows), (
            f"All approval rows for the session should be EXPIRED after drain: "
            f"{[(r.approval_id, r.decision) for r in rows]}"
        )
    finally:
        # Restore proxy health before the next test runs.
        wait_for_proxy_redeploy(k8s_client, timeout_s=180)


def test_non_gated_egress_works_without_active_session(
    k8s_manager: object,  # noqa: ARG001
    k8s_client: client.CoreV1Api,
    gated_session: tuple[User, UUID, str],
    db_session: Session,
) -> None:
    """Non-matching egress (npm registry) flows through untagged.

    Session resolution only runs after the matcher fires, so non-gated traffic
    needs no session tag.
    """
    user, _, pod_name = gated_session

    # IDLE to confirm session liveness plays no part in non-gated egress.
    db_session.execute(
        update(BuildSession)
        .where(BuildSession.user_id == user.id)
        .values(status=BuildSessionStatus.IDLE)
    )
    db_session.commit()

    output_path = f"/tmp/curl_npm_{uuid4().hex[:8]}"
    pod_exec_async(
        k8s_client,
        pod_name,
        SANDBOX_NAMESPACE,
        "https://registry.npmjs.org/",
        output_path,
        method="GET",
        max_time_s=60,
    )

    status_code, _body = wait_for_pod_exec_output(
        k8s_client, pod_name, output_path, timeout_s=90
    )
    assert status_code == 200, (
        f"Non-gated egress to npm registry should return 200 even without an "
        f"active session, got {status_code}"
    )

    assert _approval_count_for_user(db_session, user.id) == 0, (
        "Non-gated egress must not mint an approval row (under ANY session id)"
    )


def test_gated_egress_without_session_tag_fails_closed(
    k8s_manager: object,  # noqa: ARG001
    k8s_client: client.CoreV1Api,
    gated_session: tuple[User, UUID, str],
    db_session: Session,
) -> None:
    """Gated request with no session tag → 403 ``no_active_session``, no row.

    Resolution is tag-based only (no most-recent-active fallback), so it fails
    closed even though an ACTIVE session exists for the user.
    """
    user, _, pod_name = gated_session

    output_path = f"/tmp/curl_nosession_{uuid4().hex[:8]}"
    _post_slack_via_curl(k8s_client, pod_name, output_path, text="no session")

    status_code, body = wait_for_pod_exec_output(
        k8s_client, pod_name, output_path, timeout_s=30
    )
    assert status_code == 403, (
        f"Gated request without a session tag should return 403, "
        f"got {status_code}: {body!r}"
    )
    _assert_403_error_code(body, "no_active_session")

    assert _approval_count_for_user(db_session, user.id) == 0, (
        "fail-closed before commit must not mint an approval row"
    )


def test_ask_with_uninvokable_app_forwards_bare(
    k8s_manager: object,  # noqa: ARG001 -- required to construct live_pod
    k8s_client: client.CoreV1Api,
    gated_session: tuple[User, UUID, str],
    db_session: Session,
) -> None:
    """ASKs on an app whose auth template can't be filled forwards bare.

    The credential gate's documented short-circuit: With no credentials to
    inject after approval, the gate skips the ASK prompt and forwards the
    request as-is rather than parking it.
    """
    user, session_id, pod_name = gated_session

    # Strip the org credential the module seed put on Slack so app_is_available
    # falls to False. _isolate_skill_tables restores the row after this test.
    slack = get_built_in_external_app(db_session, ExternalAppType.SLACK)
    assert slack is not None, "Module seed must have created the Slack row."
    slack.organization_credentials = {}  # ty: ignore[invalid-assignment]
    db_session.commit()

    output_path = f"/tmp/curl_bare_{uuid4().hex[:8]}"
    _post_slack_via_curl(
        k8s_client,
        pod_name,
        output_path,
        text="hello",
        session_id=session_id,
    )

    # Slack returns HTTP 200 with `invalid_auth` in the body for the curl's fake
    # bearer -- the 200 + body is the proof the request actually reached
    # slack.com bare (no injection from the gate).
    status_code, body = wait_for_pod_exec_output(
        k8s_client, pod_name, output_path, timeout_s=30
    )
    assert status_code == 200, (
        f"Uninvokable ASK should forward bare to Slack and Slack should 200 "
        f"with invalid_auth in the body, got {status_code}: {body!r}"
    )
    assert "invalid_auth" in body.strip(), (
        f"Bare-forwarded request should reach slack.com and get invalid_auth, "
        f"got body {body!r}"
    )
    assert _approval_count_for_user(db_session, user.id) == 0, (
        "Uninvokable ASK must not mint an approval row."
    )


def test_sse_merger_emits_approval_requested_packet(
    k8s_manager: object,  # noqa: ARG001
    k8s_client: client.CoreV1Api,
    gated_session: tuple[User, UUID, str],
    db_session: Session,
) -> None:
    """The proxy actually RPUSHes the announce onto real Redis.

    Not the full SSE path (that needs a real LLM); the merger pipeline is
    covered by ``backend/tests/unit/build/test_session_manager_merger.py``.
    """
    user, session_id, pod_name = gated_session

    output_path = f"/tmp/curl_announce_{uuid4().hex[:8]}"
    _post_slack_via_curl(
        k8s_client, pod_name, output_path, text="announce me", session_id=session_id
    )

    pending = _wait_for_pending_approval(db_session, session_id)

    cache = get_cache_backend(tenant_id=TEST_TENANT_ID)
    popped = approval_cache.pop_announcement(session_id, timeout_s=5, cache=cache)
    assert popped == pending.approval_id, (
        f"announce list should contain the parked approval id "
        f"{pending.approval_id}, got {popped}"
    )

    # Unblock the parked curl so fixture teardown doesn't have to wake the gate.
    submit_decision(
        approval_id=pending.approval_id,
        body=DecisionBody(decision=ApprovalDecision.REJECTED),
        user=user,
        db_session=db_session,
    )
    wait_for_pod_exec_output(k8s_client, pod_name, output_path, timeout_s=30)


def test_body_too_large_returns_403(
    k8s_manager: object,  # noqa: ARG001
    k8s_client: client.CoreV1Api,
    gated_session: tuple[User, UUID, str],
    db_session: Session,
) -> None:
    """Body exceeding ``PARSER_MAX_BODY_BYTES`` (1 MiB) is rejected pre-match.

    The gate rejects before the matcher runs, so no approval row is minted.
    """
    user, _, pod_name = gated_session

    output_path = f"/tmp/curl_oversize_{uuid4().hex[:8]}"
    body_path = f"/tmp/body_oversize_{uuid4().hex[:8]}.json"
    # Generate the 1.5 MiB body in-pod -- inlining it through pod_exec_async
    # would push the full payload into the apiserver's exec URL query params and
    # trip a 431 Request Header Fields Too Large at the websocket handshake.
    pod_exec(
        k8s_client,
        pod_name,
        SANDBOX_NAMESPACE,
        (
            f'printf \'{{"channel":"#general","text":"\' > {body_path} && '
            f'head -c 1572864 /dev/zero | tr "\\0" x >> {body_path} && '
            f"printf '\"}}' >> {body_path}"
        ),
    )
    pod_exec_async(
        k8s_client,
        pod_name,
        SANDBOX_NAMESPACE,
        _SLACK_POST_MESSAGE_URL,
        output_path,
        headers={
            "Authorization": "Bearer xoxb-fake-test-token",
            "Content-Type": "application/json",
        },
        body_file=body_path,
        max_time_s=60,
    )

    status_code, body = wait_for_pod_exec_output(
        k8s_client, pod_name, output_path, timeout_s=60
    )
    assert status_code == 403, (
        f"Oversize body should return 403, got {status_code}: {body!r}"
    )
    _assert_403_error_code(body, "body_too_large")

    assert _approval_count_for_user(db_session, user.id) == 0, (
        "fail-closed on oversize must not mint an approval row"
    )


def test_approval_requested_notification_is_created(
    k8s_manager: object,  # noqa: ARG001
    k8s_client: client.CoreV1Api,
    gated_session: tuple[User, UUID, str],
    db_session: Session,
) -> None:
    """The gate commits its best-effort ``APPROVAL_REQUESTED`` notification."""
    user, session_id, pod_name = gated_session

    output_path = f"/tmp/curl_notify_{uuid4().hex[:8]}"
    _post_slack_via_curl(
        k8s_client, pod_name, output_path, text="notify me", session_id=session_id
    )

    pending = _wait_for_pending_approval(db_session, session_id)

    # Poll under cluster load; the notification commits in the same transaction
    # as the approval row.
    notif: Notification | None = None
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        db_session.expire_all()
        # dismissed=False so a stale notification from an earlier crashed test
        # (same user) doesn't shadow this run's row.
        notif = (
            db_session.query(Notification)
            .filter(Notification.user_id == user.id)
            .filter(Notification.notif_type == NotificationType.APPROVAL_REQUESTED)
            .filter(Notification.dismissed.is_(False))
            .order_by(Notification.first_shown.desc())
            .first()
        )
        if notif is not None and notif.additional_data is not None:
            if notif.additional_data.get("approval_id") == str(pending.approval_id):
                break
        time.sleep(0.5)

    assert notif is not None, (
        f"Expected APPROVAL_REQUESTED notification for user {user.id}, got none."
    )
    assert notif.additional_data is not None
    assert notif.additional_data.get("approval_id") == str(pending.approval_id), (
        f"notification.additional_data.approval_id should match "
        f"{pending.approval_id}, got: {notif.additional_data!r}"
    )
    # Deep-link spec hardcoded (`/craft/v1?sessionId=<id>`) rather than
    # imported.
    assert notif.additional_data.get("link") == f"/craft/v1?sessionId={session_id}", (
        f"notification.additional_data.link should deep-link to the session, "
        f"got: {notif.additional_data!r}"
    )

    # Unblock the parked curl before fixture teardown.
    submit_decision(
        approval_id=pending.approval_id,
        body=DecisionBody(decision=ApprovalDecision.REJECTED),
        user=user,
        db_session=db_session,
    )
    wait_for_pod_exec_output(k8s_client, pod_name, output_path, timeout_s=30)


def test_list_live_excludes_aged_pending_rows(
    k8s_manager: object,  # noqa: ARG001
    k8s_client: client.CoreV1Api,
    gated_session: tuple[User, UUID, str],
    db_session: Session,
) -> None:
    """Pending rows older than ``WAIT_TIMEOUT_S`` are excluded from /live.

    Two boundary rows (5s either side of the cutoff) make an off-by-one in the
    ``created_after`` filter (``>=`` vs ``>``) fail this test.
    """
    user, session_id, pod_name = gated_session

    output_path = f"/tmp/curl_aged_{uuid4().hex[:8]}"
    _post_slack_via_curl(
        k8s_client, pod_name, output_path, text="aged out", session_id=session_id
    )

    pending = _wait_for_pending_approval(db_session, session_id)

    # Fresh row is live.
    fresh = list_live_approvals(session_id=session_id, user=user, db_session=db_session)
    assert any(item.approval_id == pending.approval_id for item in fresh.items), (
        f"fresh pending row {pending.approval_id} should be in /live, "
        f"got: {[i.approval_id for i in fresh.items]}"
    )

    # One row just inside the cutoff (live), one just outside (expired).
    now = datetime.now(timezone.utc)
    just_live_id = uuid4()
    just_expired_id = uuid4()
    slack_actions = [
        action_entry(
            "slack.messages.write",
            display_name="Post a message",
            description="Post a message to a channel or conversation.",
        )
    ]
    db_session.add(
        ActionApproval(
            approval_id=just_live_id,
            session_id=session_id,
            actions=slack_actions,
            app_name="Slack",
            payload={"boundary": "just_live"},
            created_at=now - timedelta(seconds=_WAIT_TIMEOUT_S_SPEC - 5),
        )
    )
    db_session.add(
        ActionApproval(
            approval_id=just_expired_id,
            session_id=session_id,
            actions=slack_actions,
            app_name="Slack",
            payload={"boundary": "just_expired"},
            created_at=now - timedelta(seconds=_WAIT_TIMEOUT_S_SPEC + 5),
        )
    )
    db_session.commit()
    db_session.expire_all()

    boundary = list_live_approvals(
        session_id=session_id, user=user, db_session=db_session
    )
    boundary_ids = {item.approval_id for item in boundary.items}
    assert just_live_id in boundary_ids, (
        f"Row created {_WAIT_TIMEOUT_S_SPEC - 5}s ago should be live "
        f"(cutoff edge), got: {boundary_ids}"
    )
    assert just_expired_id not in boundary_ids, (
        f"Row created {_WAIT_TIMEOUT_S_SPEC + 5}s ago should be excluded "
        f"(just past cutoff), got: {boundary_ids}"
    )

    # Backdate well past the cutoff so the parked row drops out of /live.
    aged_at = datetime.now(timezone.utc) - timedelta(seconds=_WAIT_TIMEOUT_S_SPEC + 60)
    db_session.execute(
        text("UPDATE action_approval SET created_at = :ts WHERE approval_id = :aid"),
        {"ts": aged_at, "aid": pending.approval_id},
    )
    db_session.commit()
    db_session.expire_all()

    aged = list_live_approvals(session_id=session_id, user=user, db_session=db_session)
    aged_ids = {item.approval_id for item in aged.items}
    assert pending.approval_id not in aged_ids, (
        f"aged pending row {pending.approval_id} should be excluded from /live, "
        f"got: {aged_ids}"
    )
    # Boundary expectations still hold on the second fetch.
    assert just_live_id in aged_ids
    assert just_expired_id not in aged_ids

    # Unblock the parked curl before teardown.
    submit_decision(
        approval_id=pending.approval_id,
        body=DecisionBody(decision=ApprovalDecision.REJECTED),
        user=user,
        db_session=db_session,
    )
    wait_for_pod_exec_output(k8s_client, pod_name, output_path, timeout_s=30)


@pytest.mark.slow
def test_row_missing_on_claim_returns_expired(
    k8s_manager: object,  # noqa: ARG001
    k8s_client: client.CoreV1Api,
    gated_session: tuple[User, UUID, str],
    db_session: Session,
) -> None:
    """FK cascade dropping the approval row mid-park → gate returns EXPIRED.

    Exercises the row-missing branch of ``_claim_expired_or_read_winner``:
    deleting the BuildSession cascades the action_approval row away while the
    proxy is parked, so the post-timeout claim finds nothing to UPDATE. Slow:
    waits out the full ~180s park window.
    """
    user, session_id, pod_name = gated_session

    output_path = f"/tmp/curl_rowmissing_{uuid4().hex[:8]}"
    _post_slack_via_curl(
        k8s_client,
        pod_name,
        output_path,
        text="drop me",
        max_time_s=_WAIT_TIMEOUT_S_SPEC + 60,
        session_id=session_id,
    )

    pending = _wait_for_pending_approval(db_session, session_id)
    approval_id = pending.approval_id

    # Deleting the BuildSession cascades the parked approval row away.
    db_session.query(BuildSession).filter(BuildSession.id == session_id).delete(
        synchronize_session=False
    )
    db_session.commit()

    status_code, body = wait_for_pod_exec_output(
        k8s_client, pod_name, output_path, timeout_s=_WAIT_TIMEOUT_S_SPEC + 30
    )
    assert status_code == 403, (
        f"sandbox-side curl after row-missing claim should see 403, "
        f"got {status_code}: {body!r}"
    )
    _assert_403_error_code(body, "not_authorized")

    # Row-missing and wait-timeout both return EXPIRED, so the 403 above can't
    # distinguish them — assert the row is gone to pin the row-missing branch.
    db_session.expire_all()
    assert (
        db_session.scalar(
            select(ActionApproval).where(ActionApproval.approval_id == approval_id)
        )
        is None
    ), "FK cascade from build_session should have dropped the action_approval row."

    # User survives: cascade only crossed build_session → action_approval.
    assert db_session.get(User, user.id) is not None


@pytest.mark.slow
def test_post_decision_after_proxy_claimed_expired_returns_conflict(
    k8s_manager: object,  # noqa: ARG001
    k8s_client: client.CoreV1Api,
    gated_session: tuple[User, UUID, str],
    db_session: Session,
) -> None:
    """``submit_decision`` after the proxy already claimed EXPIRED → CONFLICT.

    Exercises ``_existing_decision_response``'s CONFLICT path: the recorded
    decision (EXPIRED) differs from the requested one (REJECTED). Slow: only K8s
    coverage of the real wait-timeout claim race; waits the full ~180s.
    """
    user, session_id, pod_name = gated_session

    output_path = f"/tmp/curl_conflict_{uuid4().hex[:8]}"
    _post_slack_via_curl(
        k8s_client,
        pod_name,
        output_path,
        text="conflict me",
        max_time_s=_WAIT_TIMEOUT_S_SPEC + 60,
        session_id=session_id,
    )

    pending = _wait_for_pending_approval(db_session, session_id)

    # Wait out the park window so the proxy claims EXPIRED.
    status_code, body = wait_for_pod_exec_output(
        k8s_client, pod_name, output_path, timeout_s=_WAIT_TIMEOUT_S_SPEC + 30
    )
    assert status_code == 403, (
        f"Expected 403 after wait-timeout, got {status_code}: {body!r}"
    )
    _assert_403_error_code(body, "not_authorized")

    # Confirm the row is EXPIRED before we submit.
    db_session.expire_all()
    refreshed = db_session.get(ActionApproval, pending.approval_id)
    assert refreshed is not None
    assert refreshed.decision == ApprovalDecision.EXPIRED, (
        f"Proxy should have claimed EXPIRED, got: {refreshed.decision}"
    )

    with pytest.raises(OnyxError) as exc_info:
        submit_decision(
            approval_id=pending.approval_id,
            body=DecisionBody(decision=ApprovalDecision.REJECTED),
            user=user,
            db_session=db_session,
        )
    assert exc_info.value.error_code == OnyxErrorCode.CONFLICT, (
        f"expected CONFLICT, got {exc_info.value.error_code}"
    )


def test_unidentified_sandbox_403_from_non_sandbox_pod(
    k8s_manager: object,  # noqa: ARG001
    k8s_client: client.CoreV1Api,
    gated_session: tuple[User, UUID, str],  # noqa: ARG001 — for fixture chain
) -> None:
    """A pod in the sandbox namespace without the managed-by label is rejected.

    Such a pod isn't in the informer cache, so the gate returns 403
    ``unidentified_sandbox`` before matcher logic runs. We hand-build a minimal
    curl pod (the standard helpers would attach the managed-by label) pointed at
    the proxy's pod IP and read its logs.
    """
    rogue_pod_name = f"rogue-curl-{uuid4().hex[:8]}"
    proxy_ip = _find_proxy_pod_ip(k8s_client)
    proxy_url = f"http://{proxy_ip}:{SANDBOX_PROXY_PORT}"

    # ``-k`` (no proxy CA installed); the gate fires on identity before any
    # upstream TLS, so the response still comes from the proxy.
    curl_argv = [
        "curl",
        "-sS",
        "-k",
        "-x",
        proxy_url,
        "-X",
        "POST",
        "-H",
        "Authorization: Bearer xoxb-fake-test-token",
        "-H",
        "Content-Type: application/json",
        "--data",
        json.dumps({"channel": "#general", "text": "rogue"}),
        "--max-time",
        "30",
        "-w",
        "\nHTTP_STATUS:%{http_code}\n",
        _SLACK_POST_MESSAGE_URL,
    ]

    pod_spec = client.V1Pod(
        metadata=client.V1ObjectMeta(
            name=rogue_pod_name,
            namespace=SANDBOX_NAMESPACE,
            # No managed-by / sandbox-id labels — that's the point: the informer
            # cache won't have an entry for this pod IP.
            labels={"app": "rogue-test"},
        ),
        spec=client.V1PodSpec(
            restart_policy="Never",
            containers=[
                client.V1Container(
                    name="curl",
                    image="curlimages/curl:8.10.1",
                    command=curl_argv,
                )
            ],
        ),
    )

    k8s_client.create_namespaced_pod(namespace=SANDBOX_NAMESPACE, body=pod_spec)
    try:
        # curl exits 0 even on HTTP errors, so we expect Succeeded.
        deadline = time.monotonic() + 90
        phase = ""
        while time.monotonic() < deadline:
            pod = k8s_client.read_namespaced_pod(
                name=rogue_pod_name, namespace=SANDBOX_NAMESPACE
            )
            phase = (pod.status.phase if pod.status else "") or ""
            if phase in ("Succeeded", "Failed"):
                break
            time.sleep(2)
        assert phase in ("Succeeded", "Failed"), (
            f"Rogue pod {rogue_pod_name} did not terminate within 90s, phase={phase!r}"
        )

        logs = k8s_client.read_namespaced_pod_log(
            name=rogue_pod_name, namespace=SANDBOX_NAMESPACE
        )
        assert "HTTP_STATUS:403" in logs, (
            f"Expected 403 from gate for unidentified sandbox, got logs: {logs!r}"
        )
        _assert_403_error_code(logs, "unidentified_sandbox")
    finally:
        try:
            k8s_client.delete_namespaced_pod(
                name=rogue_pod_name,
                namespace=SANDBOX_NAMESPACE,
                grace_period_seconds=0,
            )
        except Exception as e:  # noqa: BLE001
            logger.warning(
                "best-effort cleanup of rogue pod %s failed: %s", rogue_pod_name, e
            )
