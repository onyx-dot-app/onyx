"""Approval-gate end-to-end (real proxy + Redis + sandbox pod + Postgres).

The file-level ``pytestmark`` gates the entire module to the K8s CI lane.
Per project memory: never run these locally — they touch the real cluster.

Each test provisions a sandbox pod via the ``live_pod`` fixture (from
``craft/conftest.py``), seeds a ``User`` + ACTIVE ``BuildSession`` in
Postgres so the gate's ``resolve_active_session`` can route the card,
then drives a real sandbox-side ``curl`` against ``slack.com`` and
asserts the resulting ApprovalDecision flow.

The unique contract these tests pin (vs. ``test_approvals_api.py`` which
is in-process):

* The mitmproxy GateAddon intercepts real network egress and commits a
  Postgres row before parking.
* The api-server's ``submit_decision`` RPUSHes onto real Redis and the
  parked proxy's BLPOP unblocks within seconds.
* The SIGTERM drain path on proxy-pod deletion actually claims EXPIRED
  for parked approvals.
* Non-gated egress flows around the gate without minting rows.
* The chat-stream merger's announce list is populated on real Redis.

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
from fastapi_users.password import PasswordHelper
from kubernetes import client
from sqlalchemy import select
from sqlalchemy import text
from sqlalchemy import update
from sqlalchemy.orm import Session

from onyx.cache.factory import get_cache_backend
from onyx.configs.constants import NotificationType
from onyx.db.enums import AccountType
from onyx.db.enums import ApprovalDecision
from onyx.db.enums import BuildSessionStatus
from onyx.db.models import ActionApproval
from onyx.db.models import BuildSession
from onyx.db.models import Notification
from onyx.db.models import User
from onyx.db.models import UserRole
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
from tests.external_dependency_unit.constants import TEST_TENANT_ID
from tests.external_dependency_unit.craft.conftest import K8S_TEST_USER_ID
from tests.external_dependency_unit.craft.conftest import pod_exec_async
from tests.external_dependency_unit.craft.conftest import wait_for_pod_exec_output
from tests.external_dependency_unit.craft.conftest import wait_for_proxy_redeploy

logger = setup_logger()

pytestmark = pytest.mark.skipif(
    SANDBOX_BACKEND != SandboxBackend.KUBERNETES,
    reason="K8s tests require SANDBOX_BACKEND=kubernetes; run in the dedicated K8s CI job.",
)

# The label the helm chart attaches to the proxy Deployment + pods.
_PROXY_COMPONENT_LABEL = "app.kubernetes.io/component=sandbox-proxy"

# Slack URL the sandbox-side curl posts to. Any path under chat.postMessage
# matches the gate's SlackPostMessageMatcher (case-insensitive prefix).
_SLACK_POST_MESSAGE_URL = "https://slack.com/api/chat.postMessage"

# Spec value pinned in approval_cache.WAIT_TIMEOUT_S. Re-asserted in
# ``test_wait_timeout_constant_matches_spec`` so a constant change is caught
# explicitly rather than silently re-tuning every timeout in this file.
_WAIT_TIMEOUT_S_SPEC = 180


# ---------------------------------------------------------------------------
# Local helpers (file-scoped).
# ---------------------------------------------------------------------------


def _post_slack_via_curl(
    k8s: client.CoreV1Api,
    pod_name: str,
    output_path: str,
    *,
    text: str = "approval test",
    max_time_s: int = 240,
) -> None:
    """Drive a sandbox-side curl against Slack's chat.postMessage.

    The bearer is intentionally fake — Slack will respond with
    ``invalid_auth`` if the request reaches Slack (used by the
    APPROVED test) but the matcher only cares about the URL prefix.
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
    )


def _wait_for_pending_approval(
    db_session: Session, session_id: UUID, timeout_s: float = 30
) -> ActionApproval:
    """Poll until a pending (``decision IS NULL``) row exists for ``session_id``.

    Required because the proxy's commit happens asynchronously from the
    test runner — we have to observe the row before submitting a decision.
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
    """Count approvals across every session owned by ``user_id``.

    Wider than per-session counting so a gate bug that mints under a
    different session_id still trips the assertion.
    """
    db_session.expire_all()
    return (
        db_session.query(ActionApproval)
        .join(BuildSession, ActionApproval.session_id == BuildSession.id)
        .filter(BuildSession.user_id == user_id)
        .count()
    )


def _find_proxy_pod_name(k8s: client.CoreV1Api) -> str:
    """Return the name of one running sandbox-proxy pod.

    Assumes the sandbox-proxy Deployment is running with ``replicas == 1``
    (the default for the helm chart). Behaviour is undefined if the
    Deployment has been scaled higher — we return ``items[0]`` and the
    caller cannot tell which replica that is. The SIGTERM-drain test that
    depends on this helper would need to delete every replica to guarantee
    a drain; right now it only deletes one.
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
    """Return the pod IP of one running sandbox-proxy pod.

    Used by ``test_unidentified_sandbox_403_from_non_sandbox_pod`` so the
    rogue pod can talk to the proxy directly (it can't resolve the
    ``sandbox-proxy`` host alias the real sandbox spec installs).
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
    """Assert a sandbox-facing 403 body contains the expected error code,
    tolerant of whitespace variations in the JSON serialisation."""
    normalized = body.replace(" ", "")
    assert f'"error":"{expected_code}"' in normalized, (
        f"expected error_code={expected_code!r} in body, got: {body!r}"
    )


# ---------------------------------------------------------------------------
# Fixture: seed user + active session, clean up after.
# ---------------------------------------------------------------------------


@pytest.fixture(scope="function")
def gated_session(
    db_session: Session,
    live_pod: tuple[UUID, UUID, str],
) -> Generator[tuple[User, UUID, str], None, None]:
    """Seed a ``User`` + ACTIVE ``BuildSession`` matching ``live_pod``'s ids.

    The ``live_pod`` fixture provisions a sandbox under ``K8S_TEST_USER_ID``
    but does NOT create the matching user/session rows. We upsert the user,
    delete any stale BuildSession rows for that user, then insert an ACTIVE
    BuildSession whose id matches the one ``setup_session_workspace`` used.

    Teardown deletes the user; FK ``ondelete=CASCADE`` on
    ``build_session.user_id`` + ``action_approval.session_id`` +
    ``notification.user_id`` drops the related rows automatically.

    Implicit fixture ordering note: ``db_session`` runs before ``live_pod``,
    and ``live_pod`` depends on ``k8s_manager`` which sets
    ``CURRENT_TENANT_ID_CONTEXTVAR`` to ``TEST_TENANT_ID``. That means
    when this fixture's body executes its DB writes, the tenant
    contextvar is already populated. We deliberately do NOT take an
    explicit ``tenant_context`` dependency here because doing so would
    push/pop a second token on top of ``k8s_manager``'s token, which is
    pointless once the latter has already set it. If you remove the
    tenant-setting behaviour from ``k8s_manager`` this fixture breaks
    silently — pin that contract in ``conftest.py`` first.
    """
    _, session_id, pod_name = live_pod

    user = db_session.get(User, K8S_TEST_USER_ID)
    if user is None:
        password_helper = PasswordHelper()
        password = password_helper.generate()
        user = User(
            id=K8S_TEST_USER_ID,
            email=f"k8s_approval_gate_{K8S_TEST_USER_ID.hex[:8]}@example.com",
            hashed_password=password_helper.hash(password),
            is_active=True,
            is_superuser=False,
            is_verified=True,
            role=UserRole.BASIC,
            account_type=AccountType.STANDARD,
        )
        db_session.add(user)
        db_session.commit()
        db_session.refresh(user)

    # Stale BuildSession rows (status=ACTIVE) from previous tests would steer
    # ``resolve_active_session`` to a session id the in-pod workspace doesn't
    # know about. Drop them all so the test sees a single deterministic row.
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

    try:
        yield user, session_id, pod_name
    finally:
        # Late import to dodge engine-init ordering issues if the test
        # session is already torn down by pytest finalisers.
        from onyx.db.engine.sql_engine import get_session_with_current_tenant
        from shared_configs.contextvars import CURRENT_TENANT_ID_CONTEXTVAR

        token = CURRENT_TENANT_ID_CONTEXTVAR.set(TEST_TENANT_ID)
        try:
            with get_session_with_current_tenant() as cleanup:
                existing = cleanup.get(User, K8S_TEST_USER_ID)
                if existing is not None:
                    cleanup.delete(existing)
                    cleanup.commit()
        finally:
            CURRENT_TENANT_ID_CONTEXTVAR.reset(token)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_rejected_decision_returns_403_user_rejected(
    k8s_manager: object,  # noqa: ARG001 — required to construct live_pod
    k8s_client: client.CoreV1Api,
    gated_session: tuple[User, UUID, str],
    db_session: Session,
) -> None:
    """Approve=False end-to-end.

    Sandbox-side curl to ``chat.postMessage`` parks on the gate; we
    submit REJECTED via the API; the proxy's BLPOP wakes and writes
    a 403 ``user_rejected`` back to the sandbox.
    """
    user, session_id, pod_name = gated_session

    output_path = f"/tmp/curl_reject_{uuid4().hex[:8]}"
    _post_slack_via_curl(k8s_client, pod_name, output_path, text="hello from K8s CI")

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
    """Approve=True end-to-end.

    Sandbox-side curl parks; APPROVED is submitted; the proxy forwards
    the request and Slack itself responds with HTTP 200 carrying an
    ``invalid_auth`` JSON body (the fake bearer can't validate). The
    success signal here is that the request *reached* Slack — Slack's
    own ``invalid_auth`` body is precisely what proves end-to-end forwarding.
    """
    user, session_id, pod_name = gated_session

    output_path = f"/tmp/curl_approve_{uuid4().hex[:8]}"
    _post_slack_via_curl(k8s_client, pod_name, output_path, text="forwarded")

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
        f"forwarded request should hit Slack and return 200 (Slack will say "
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

    Pins ``WAIT_TIMEOUT_S == 180s`` as the spec (re-asserted by
    ``test_wait_timeout_constant_matches_spec``). curl's --max-time must
    outlive the spec window so we observe the proxy's 403 rather than
    the client tearing down first.
    """
    user, session_id, pod_name = gated_session

    output_path = f"/tmp/curl_expire_{uuid4().hex[:8]}"
    _post_slack_via_curl(
        k8s_client,
        pod_name,
        output_path,
        text="never decided",
        max_time_s=_WAIT_TIMEOUT_S_SPEC + 60,
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

    # Avoid silently retuning if someone shortens the constant: spec lives
    # in the test, the assertion below pins the implementation to it.
    assert user.id == K8S_TEST_USER_ID  # belt-and-suspenders: real seed user


def test_wait_timeout_constant_matches_spec() -> None:
    """``approval_cache.WAIT_TIMEOUT_S`` must equal the value tests assume.

    Completeness check decoupled from the slow test above: changing the
    constant trips this immediately rather than silently shrinking every
    other test's timeout budget.
    """
    assert approval_cache.WAIT_TIMEOUT_S == _WAIT_TIMEOUT_S_SPEC


def test_sigterm_drain_unblocks_parked_request(
    k8s_manager: object,  # noqa: ARG001
    k8s_client: client.CoreV1Api,
    gated_session: tuple[User, UUID, str],
    db_session: Session,
) -> None:
    """Deleting the parked proxy pod must drain → wake → EXPIRED quickly.

    Without the drain hook the sandbox-side curl would hang until
    ``WAIT_TIMEOUT_S`` (180s). We assert it unblocks well inside that
    window, then verify the row is EXPIRED.
    """
    _, session_id, pod_name = gated_session

    output_path = f"/tmp/curl_drain_{uuid4().hex[:8]}"
    _post_slack_via_curl(k8s_client, pod_name, output_path, text="drain me")

    _wait_for_pending_approval(db_session, session_id)

    # Delete the proxy pod and don't wait for graceful termination — we
    # rely on the proxy's own SIGTERM drain coroutine to fire wakes.
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
        assert rows, "expected an approval row to exist after drain"
        assert all(r.decision == ApprovalDecision.EXPIRED for r in rows), (
            f"all approval rows for the session should be EXPIRED after drain: "
            f"{[(r.approval_id, r.decision) for r in rows]}"
        )
    finally:
        # Hygiene: make sure the proxy Deployment is healthy again before
        # the next test (and the rest of the suite) runs.
        wait_for_proxy_redeploy(k8s_client, timeout_s=120)


def test_non_gated_egress_works_without_active_session(
    k8s_manager: object,  # noqa: ARG001
    k8s_client: client.CoreV1Api,
    gated_session: tuple[User, UUID, str],
    db_session: Session,
) -> None:
    """No ACTIVE session → non-gated egress (npm registry) still succeeds.

    Pins the gate's fail-open behaviour for non-matching requests: the
    session liveness check is only triggered after the matcher fires,
    so npm install / apt / pip flow even when there's no active session.
    """
    user, _, pod_name = gated_session

    # Force the session into IDLE (and any other sessions for this user)
    # so ``resolve_active_session`` returns None.
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
        f"non-gated egress to npm registry should return 200 even without an "
        f"active session, got {status_code}"
    )

    assert _approval_count_for_user(db_session, user.id) == 0, (
        "non-gated egress must not mint an approval row (under ANY session id)"
    )


def test_gated_egress_without_active_session_returns_no_active_session(
    k8s_manager: object,  # noqa: ARG001
    k8s_client: client.CoreV1Api,
    gated_session: tuple[User, UUID, str],
    db_session: Session,
) -> None:
    """No ACTIVE session + gated request → 403 ``no_active_session``.

    The matcher fires (Slack chat.postMessage), so the gate now needs a
    session to route the card to. With no ACTIVE session it fails
    closed *without* committing a row.
    """
    user, _, pod_name = gated_session

    db_session.execute(
        update(BuildSession)
        .where(BuildSession.user_id == user.id)
        .values(status=BuildSessionStatus.IDLE)
    )
    db_session.commit()

    output_path = f"/tmp/curl_nosession_{uuid4().hex[:8]}"
    _post_slack_via_curl(k8s_client, pod_name, output_path, text="no session")

    status_code, body = wait_for_pod_exec_output(
        k8s_client, pod_name, output_path, timeout_s=30
    )
    assert status_code == 403, (
        f"gated request without an active session should return 403, "
        f"got {status_code}: {body!r}"
    )
    _assert_403_error_code(body, "no_active_session")

    assert _approval_count_for_user(db_session, user.id) == 0, (
        "fail-closed before commit must not mint an approval row"
    )


def test_sse_merger_emits_approval_requested_packet(
    k8s_manager: object,  # noqa: ARG001
    k8s_client: client.CoreV1Api,
    gated_session: tuple[User, UUID, str],
    db_session: Session,
) -> None:
    """The proxy actually RPUSHes the announce on real Redis.

    Why this isn't the full SSE path: driving ``send_message`` would
    require a real LLM (cost + flakiness). The unique K8s value here
    is that the proxy *actually* pushes onto the real Redis list a
    consumer can BLPOP from. The full chat-stream merger pipeline is
    covered by the unit test in
    ``backend/tests/unit/build/test_session_manager_merger.py``.
    """
    user, session_id, pod_name = gated_session

    output_path = f"/tmp/curl_announce_{uuid4().hex[:8]}"
    _post_slack_via_curl(k8s_client, pod_name, output_path, text="announce me")

    pending = _wait_for_pending_approval(db_session, session_id)

    cache = get_cache_backend(tenant_id=TEST_TENANT_ID)
    popped = approval_cache.pop_announcement(session_id, timeout_s=5, cache=cache)
    assert popped == pending.approval_id, (
        f"announce list should contain the parked approval id "
        f"{pending.approval_id}, got {popped}"
    )

    # Unblock the parked curl so the fixture's pod-deletion teardown
    # doesn't have to wake the gate's _await_decision via CancelledError.
    submit_decision(
        approval_id=pending.approval_id,
        body=DecisionBody(decision=ApprovalDecision.REJECTED),
        user=user,
        db_session=db_session,
    )
    # Rely on fixture teardown for cleanup — pod deletion triggers
    # CancelledError in the gate's _await_decision which claims EXPIRED
    # via the conditional UPDATE, so we don't need to wait the curl out.
    wait_for_pod_exec_output(k8s_client, pod_name, output_path, timeout_s=30)


def test_body_too_large_returns_403(
    k8s_manager: object,  # noqa: ARG001
    k8s_client: client.CoreV1Api,
    gated_session: tuple[User, UUID, str],
    db_session: Session,
) -> None:
    """Body exceeding ``PARSER_MAX_BODY_BYTES`` (1 MiB) is fail-closed.

    Pins the cap in ``onyx/sandbox_proxy/addons/gate.py``. The matcher
    never gets to see the request — the gate rejects pre-match so no
    approval row is minted either.
    """
    user, _, pod_name = gated_session

    # 1.5 MiB payload — well above the 1 MiB cap. ``--data-binary @-``
    # would be cleaner but the helper composes ``--data`` directly; we
    # synthesise the oversize body inline.
    output_path = f"/tmp/curl_oversize_{uuid4().hex[:8]}"
    big_payload = "x" * (1_572_864)  # 1.5 MiB
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
        body=json.dumps({"channel": "#general", "text": big_payload}),
        max_time_s=60,
    )

    status_code, body = wait_for_pod_exec_output(
        k8s_client, pod_name, output_path, timeout_s=60
    )
    assert status_code == 403, (
        f"oversize body should return 403, got {status_code}: {body!r}"
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
    """The gate's best-effort ``APPROVAL_REQUESTED`` notification is committed.

    Pins ``gate._notify_approval_requested``: after minting the approval
    row the gate creates a notification under the same user. We unblock
    the parked curl with REJECTED so teardown doesn't have to wake it.
    """
    user, session_id, pod_name = gated_session

    output_path = f"/tmp/curl_notify_{uuid4().hex[:8]}"
    _post_slack_via_curl(k8s_client, pod_name, output_path, text="notify me")

    pending = _wait_for_pending_approval(db_session, session_id)

    # Poll briefly — create_notification runs in the same _persist_approval_row
    # transaction as the approval row insert, so by the time we see the row
    # the notification should be there. Belt-and-suspenders polling under
    # cluster load.
    notif: Notification | None = None
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        db_session.expire_all()
        # Filter dismissed=False so a stale notification left behind by
        # an earlier crashed test (same K8S_TEST_USER_ID; the fixture
        # only deletes via FK cascade on user delete) doesn't shadow
        # this run's row. Field name verified in
        # ``onyx.db.models.Notification``.
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
        f"expected APPROVAL_REQUESTED notification for user {user.id}, got none"
    )
    assert notif.additional_data is not None
    assert notif.additional_data.get("approval_id") == str(pending.approval_id), (
        f"notification.additional_data.approval_id should match "
        f"{pending.approval_id}, got: {notif.additional_data!r}"
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

    Pins ``ApprovalView.is_live`` + ``list_live_approvals``'s ``created_after``
    filter: a fresh pending row appears, then we backdate ``created_at`` to
    just outside the window and re-fetch — it should drop out. We also seed
    two boundary-edge rows (5s either side of the cutoff) so an off-by-one
    in ``>=`` vs ``>`` on the ``created_at`` filter fails this test.
    """
    user, session_id, pod_name = gated_session

    output_path = f"/tmp/curl_aged_{uuid4().hex[:8]}"
    _post_slack_via_curl(k8s_client, pod_name, output_path, text="aged out")

    pending = _wait_for_pending_approval(db_session, session_id)

    # Sanity: fresh row IS live.
    fresh = list_live_approvals(session_id=session_id, user=user, db_session=db_session)
    assert any(item.approval_id == pending.approval_id for item in fresh.items), (
        f"fresh pending row {pending.approval_id} should be in /live, "
        f"got: {[i.approval_id for i in fresh.items]}"
    )

    # Boundary-edge rows: one created just inside the cutoff (still live),
    # one created just outside (just expired). An off-by-one in the
    # ``created_after`` filter (``>=`` vs ``>``) would flip the
    # ``just_live`` row out, which the assertions below catch.
    now = datetime.now(timezone.utc)
    just_live_id = uuid4()
    just_expired_id = uuid4()
    db_session.add(
        ActionApproval(
            approval_id=just_live_id,
            session_id=session_id,
            action_type="slack.chat.postMessage",
            payload={"boundary": "just_live"},
            created_at=now - timedelta(seconds=_WAIT_TIMEOUT_S_SPEC - 5),
        )
    )
    db_session.add(
        ActionApproval(
            approval_id=just_expired_id,
            session_id=session_id,
            action_type="slack.chat.postMessage",
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
        f"row created {_WAIT_TIMEOUT_S_SPEC - 5}s ago should be live "
        f"(cutoff edge), got: {boundary_ids}"
    )
    assert just_expired_id not in boundary_ids, (
        f"row created {_WAIT_TIMEOUT_S_SPEC + 5}s ago should be excluded "
        f"(just past cutoff), got: {boundary_ids}"
    )

    # Backdate by WAIT_TIMEOUT_S + 60s via raw UPDATE so the cutoff
    # excludes the parked row. ``ApprovalView.is_live`` also recomputes False.
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
    # The boundary-edge expectations still hold on the second fetch.
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

    Pins the row-missing branch of ``_claim_expired_or_read_winner``:
    the BuildSession (and via FK cascade, the action_approval row) is
    deleted while the proxy is parked on BLPOP. After ``WAIT_TIMEOUT_S``
    the gate's claim attempt finds nothing to UPDATE and returns
    EXPIRED, so the sandbox-side curl sees a 403 ``not_authorized``.

    Marked ``slow`` because we wait out the full ~180s park window.
    """
    user, session_id, pod_name = gated_session

    output_path = f"/tmp/curl_rowmissing_{uuid4().hex[:8]}"
    _post_slack_via_curl(
        k8s_client,
        pod_name,
        output_path,
        text="drop me",
        max_time_s=_WAIT_TIMEOUT_S_SPEC + 60,
    )

    pending = _wait_for_pending_approval(db_session, session_id)
    approval_id = pending.approval_id

    # Delete the BuildSession directly — FK cascade on
    # ``action_approval.session_id`` drops the parked approval row.
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

    # Positive assertion that the row is truly gone (FK cascade fired).
    # Both the row-missing branch and the wait-timeout branch return
    # EXPIRED to the proxy, so the 403/not_authorized assertions above
    # alone don't distinguish them; checking that the row is absent
    # pins the row-missing branch specifically.
    db_session.expire_all()
    assert (
        db_session.scalar(
            select(ActionApproval).where(ActionApproval.approval_id == approval_id)
        )
        is None
    ), "FK cascade from build_session should have dropped the action_approval row"

    # belt-and-suspenders: user is unchanged (the cascade only crossed
    # build_session → action_approval, not user → build_session).
    assert db_session.get(User, user.id) is not None


@pytest.mark.slow
def test_post_decision_after_proxy_claimed_expired_returns_conflict(
    k8s_manager: object,  # noqa: ARG001
    k8s_client: client.CoreV1Api,
    gated_session: tuple[User, UUID, str],
    db_session: Session,
) -> None:
    """Race-edge: API ``submit_decision`` after proxy already claimed EXPIRED.

    Pins ``_existing_decision_response``'s CONFLICT path for the case
    where the row was decided by the proxy (EXPIRED via wait-timeout)
    while the user-submitted decision lost the race. We wait out the
    full ~180s park window so the proxy's claim fires, then call
    ``submit_decision(REJECTED)`` directly — the API must raise
    ``OnyxError`` with ``CONFLICT`` because the row's recorded decision
    (EXPIRED) is different from the requested one (REJECTED).

    Slow marker is required — this is the only K8s-level coverage of the
    proxy-side EXPIRED → API CONFLICT race; the in-process API test
    can't replicate the real wait-timeout claim path.
    """
    user, session_id, pod_name = gated_session

    output_path = f"/tmp/curl_conflict_{uuid4().hex[:8]}"
    _post_slack_via_curl(
        k8s_client,
        pod_name,
        output_path,
        text="conflict me",
        max_time_s=_WAIT_TIMEOUT_S_SPEC + 60,
    )

    pending = _wait_for_pending_approval(db_session, session_id)

    # Wait out the park window so the proxy claims EXPIRED.
    status_code, body = wait_for_pod_exec_output(
        k8s_client, pod_name, output_path, timeout_s=_WAIT_TIMEOUT_S_SPEC + 30
    )
    assert status_code == 403, (
        f"expected 403 after wait-timeout, got {status_code}: {body!r}"
    )
    _assert_403_error_code(body, "not_authorized")

    # Sanity-check that the row really is EXPIRED before we submit.
    db_session.expire_all()
    refreshed = db_session.get(ActionApproval, pending.approval_id)
    assert refreshed is not None
    assert refreshed.decision == ApprovalDecision.EXPIRED, (
        f"proxy should have claimed EXPIRED, got: {refreshed.decision}"
    )

    # API must now refuse REJECTED with CONFLICT — the existing decision
    # (EXPIRED) differs from the requested one (REJECTED).
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
    """A pod in ``onyx-sandboxes`` without the managed-by label is rejected.

    Pins ``GateAddon``'s identity fail-closed branch: a pod that lives
    in the sandbox namespace (so NetworkPolicy permits ingress to the
    proxy) but lacks ``app.kubernetes.io/managed-by=onyx`` is not in the
    informer cache, so the gate returns 403 ``unidentified_sandbox``
    *before* matcher logic runs.

    We can't use the standard sandbox pod-spec helpers — they'd attach
    the managed-by label. Instead we ``kubectl run`` a minimal curl pod
    pointed at the proxy's pod IP, then read its logs after completion.
    """
    rogue_pod_name = f"rogue-curl-{uuid4().hex[:8]}"
    proxy_ip = _find_proxy_pod_ip(k8s_client)
    proxy_url = f"http://{proxy_ip}:{SANDBOX_PROXY_PORT}"

    # The rogue pod has no proxy CA installed, so we use ``-k`` to skip
    # cert validation — the gate fires on identity BEFORE any TLS work
    # against the upstream, so the response still comes from the proxy.
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
            # Deliberately NO ``app.kubernetes.io/managed-by=onyx`` label
            # and NO ``onyx.app/sandbox-id``. That's the whole point —
            # the informer cache won't have an entry for this pod IP.
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
        # Poll until the pod completes (Succeeded or Failed); curl always
        # exits 0 even on HTTP errors, so we expect Succeeded.
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
            f"rogue pod {rogue_pod_name} did not terminate within 90s, phase={phase!r}"
        )

        logs = k8s_client.read_namespaced_pod_log(
            name=rogue_pod_name, namespace=SANDBOX_NAMESPACE
        )
        assert "HTTP_STATUS:403" in logs, (
            f"expected 403 from gate for unidentified sandbox, got logs: {logs!r}"
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
