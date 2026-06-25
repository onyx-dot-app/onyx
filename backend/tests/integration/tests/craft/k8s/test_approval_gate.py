"""Approval-gate flow against the real proxy/Redis/SIGTERM-drain paths."""

from __future__ import annotations

import json
import time
from collections.abc import Generator
from typing import NamedTuple
from uuid import UUID
from uuid import uuid4

import httpx
import pytest
from kubernetes import client
from sqlalchemy.orm import Session

from onyx.cache.factory import get_cache_backend
from onyx.configs.constants import NotificationType
from onyx.db.enums import ApprovalDecision
from onyx.db.enums import BuildSessionStatus
from onyx.db.enums import EndpointPolicy
from onyx.db.enums import ExternalAppType
from onyx.db.models import ActionApproval
from onyx.db.models import BuildSession
from onyx.db.models import Notification
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.sandbox_proxy.approval_cache import pop_announcement
from onyx.server.features.build.configs import SANDBOX_APPROVAL_WAIT_TIMEOUT_SECONDS
from onyx.server.features.build.configs import SANDBOX_BACKEND
from onyx.server.features.build.configs import SANDBOX_NAMESPACE
from onyx.server.features.build.configs import SANDBOX_PROXY_NAMESPACE
from onyx.server.features.build.configs import SANDBOX_PROXY_PORT
from onyx.server.features.build.configs import SandboxBackend
from onyx.server.features.build.external_apps.models import ExternalAppAdminResponse
from onyx.utils.logger import setup_logger
from shared_configs.configs import POSTGRES_DEFAULT_SCHEMA_STANDARD_VALUE
from tests.integration.common_utils.constants import API_SERVER_URL
from tests.integration.common_utils.http_client import client as http_client
from tests.integration.common_utils.managers.external_app import ExternalAppManager
from tests.integration.common_utils.test_models import DATestUser
from tests.integration.tests.craft.k8s.k8s_fixtures import OwnedLivePod
from tests.integration.tests.craft.k8s.k8s_fixtures import pod_exec
from tests.integration.tests.craft.k8s.k8s_fixtures import pod_exec_async
from tests.integration.tests.craft.k8s.k8s_fixtures import wait_for_pod_exec_output
from tests.integration.tests.craft.k8s.k8s_fixtures import wait_for_proxy_redeploy

logger = setup_logger()


class GatedSession(NamedTuple):
    """Returned by the ``gated_session`` fixture."""

    api_user: DATestUser
    session_id: UUID
    pod_name: str


pytestmark = [
    pytest.mark.skipif(
        SANDBOX_BACKEND != SandboxBackend.KUBERNETES,
        reason="K8s tests require SANDBOX_BACKEND=kubernetes; run in the dedicated K8s CI job.",
    ),
    pytest.mark.craft_skill_isolation,
]

_PROXY_COMPONENT_LABEL = "app.kubernetes.io/component=sandbox-proxy"

_SLACK_POST_MESSAGE_URL = "https://slack.com/api/chat.postMessage"

# Fake token seeded by ``_seed_slack_external_app``; an unfillable template
# would short-circuit the ASK gate. Tests that strip it must restore it.
_SEEDED_SLACK_CREDENTIALS = {"access_token": "fake-test-token"}


def _upsert_slack_external_app(
    admin_user: DATestUser,
    *,
    organization_credentials: dict[str, str],
) -> tuple[int, ExternalAppAdminResponse | None]:
    existing = next(
        (
            app
            for app in ExternalAppManager.list_admin(admin_user)
            if app.app_type == ExternalAppType.SLACK
        ),
        None,
    )
    kwargs = {
        "name": "Slack",
        "description": "Slack integration for gate-flow K8s tests.",
        "app_type": ExternalAppType.SLACK,
        "upstream_url_patterns": ["https://slack\\.com/api/.*"],
        "auth_template": {"Authorization": "Bearer {access_token}"},
        "organization_credentials": organization_credentials,
        "enabled": True,
        "action_policies": {"slack.messages.write": EndpointPolicy.ASK},
    }
    if existing is None:
        created = ExternalAppManager.create(admin_user, **kwargs)
        return created.id, None

    updated = ExternalAppManager.update(admin_user, existing.id, **kwargs)
    return updated.id, existing


def _action_policies_for_restore(
    app: ExternalAppAdminResponse,
) -> dict[str, EndpointPolicy]:
    return {action.action_id: action.state for action in app.actions}


@pytest.fixture(scope="module", autouse=True)
def _seed_slack_external_app(
    k8s_admin_user: DATestUser,
) -> Generator[None, None, None]:
    """Seed an enabled Slack ``external_app`` so the matcher claims ``chat.postMessage``."""
    app_id, previous = _upsert_slack_external_app(
        k8s_admin_user,
        organization_credentials=_SEEDED_SLACK_CREDENTIALS,
    )
    try:
        yield
    finally:
        if previous is None:
            ExternalAppManager.delete(k8s_admin_user, app_id)
        else:
            ExternalAppManager.update(
                k8s_admin_user,
                previous.id,
                name=previous.name,
                description=previous.description,
                app_type=previous.app_type,
                upstream_url_patterns=previous.upstream_url_patterns,
                auth_template=previous.auth_template,
                organization_credentials=previous.organization_credentials,
                enabled=previous.enabled,
                action_policies=_action_policies_for_restore(previous),
            )


def _post_slack_via_curl(
    k8s: client.CoreV1Api,
    pod_name: str,
    output_path: str,
    *,
    text: str = "approval test",
    max_time_s: int = 240,
    session_id: UUID | None = None,
) -> None:
    """Drive a sandbox-side curl against Slack's chat.postMessage.

    The bearer is intentionally fake — Slack responds ``invalid_auth`` if the
    request reaches it. ``session_id`` tags the egress; omit it for the untagged
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
    """Poll until a pending (``decision IS NULL``) row exists for ``session_id``."""
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
    """Count approvals across every session owned by ``user_id``."""
    db_session.expire_all()
    return (
        db_session.query(ActionApproval)
        .join(BuildSession, ActionApproval.session_id == BuildSession.id)
        .filter(BuildSession.user_id == user_id)
        .count()
    )


def _find_proxy_pod_name(k8s: client.CoreV1Api) -> str:
    """Return the name of one running sandbox-proxy pod (assumes ``replicas == 1``)."""
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

    The rogue pod can't resolve the ``sandbox-proxy`` host alias, so it needs the IP.
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
    normalized = body.replace(" ", "")
    assert f'"error":"{expected_code}"' in normalized, (
        f"Expected error_code={expected_code!r} in body, got: {body!r}"
    )


def _submit_decision_response(
    api_user: DATestUser,
    approval_id: UUID,
    decision: ApprovalDecision,
) -> httpx.Response:
    return http_client.post(
        f"{API_SERVER_URL}/build/approvals/{approval_id}/decision",
        json={"decision": decision.value},
        headers=api_user.headers,
        cookies=api_user.cookies,
    )


def _submit_decision(
    api_user: DATestUser,
    approval_id: UUID,
    decision: ApprovalDecision,
) -> dict[str, object]:
    response = _submit_decision_response(api_user, approval_id, decision)
    response.raise_for_status()
    body = response.json()
    assert isinstance(body, dict)
    return body


@pytest.fixture(scope="function")
def gated_session(
    db_session: Session,
    owned_live_pod: OwnedLivePod,
) -> Generator[GatedSession, None, None]:
    """Resolve the API-created active ``BuildSession`` backing ``owned_live_pod``.

    ``owned_live_pod`` (via ``k8s_manager``) already sets ``CURRENT_TENANT_ID_CONTEXTVAR``.
    """
    api_user, _sandbox_id, session_id, pod_name = owned_live_pod

    row = db_session.get(BuildSession, session_id)
    assert row is not None
    assert row.user_id == UUID(api_user.id)
    assert row.status == BuildSessionStatus.ACTIVE

    yield GatedSession(
        api_user=api_user,
        session_id=session_id,
        pod_name=pod_name,
    )


def test_rejected_decision_returns_403_user_rejected(
    k8s_manager: object,  # noqa: ARG001 — required to construct owned_live_pod
    k8s_client: client.CoreV1Api,
    gated_session: GatedSession,
    db_session: Session,
) -> None:
    api_user, session_id, pod_name = gated_session

    output_path = f"/tmp/curl_reject_{uuid4().hex[:8]}"
    _post_slack_via_curl(
        k8s_client,
        pod_name,
        output_path,
        text="hello from K8s CI",
        session_id=session_id,
    )

    pending = _wait_for_pending_approval(db_session, session_id)

    response = _submit_decision(
        api_user,
        pending.approval_id,
        ApprovalDecision.REJECTED,
    )
    assert response["decision"] == ApprovalDecision.REJECTED.value
    assert response["approval_id"] == str(pending.approval_id)

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
    gated_session: GatedSession,
    db_session: Session,
) -> None:
    api_user, session_id, pod_name = gated_session

    output_path = f"/tmp/curl_approve_{uuid4().hex[:8]}"
    _post_slack_via_curl(
        k8s_client, pod_name, output_path, text="forwarded", session_id=session_id
    )

    pending = _wait_for_pending_approval(db_session, session_id)

    response = _submit_decision(
        api_user,
        pending.approval_id,
        ApprovalDecision.APPROVED,
    )
    assert response["decision"] == ApprovalDecision.APPROVED.value

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
    gated_session: GatedSession,
    db_session: Session,
) -> None:
    """No decision → proxy claims EXPIRED after the wait timeout.

    curl's --max-time must outlive the spec window so we see the proxy's 403.
    """
    _api_user, session_id, pod_name = gated_session

    output_path = f"/tmp/curl_expire_{uuid4().hex[:8]}"
    _post_slack_via_curl(
        k8s_client,
        pod_name,
        output_path,
        text="never decided",
        max_time_s=SANDBOX_APPROVAL_WAIT_TIMEOUT_SECONDS + 60,
        session_id=session_id,
    )

    pending = _wait_for_pending_approval(db_session, session_id)

    status_code, body = wait_for_pod_exec_output(
        k8s_client,
        pod_name,
        output_path,
        timeout_s=SANDBOX_APPROVAL_WAIT_TIMEOUT_SECONDS + 30,
    )
    assert status_code == 403, (
        f"sandbox-side curl after timeout should see 403, got {status_code}: {body!r}"
    )
    _assert_403_error_code(body, "not_authorized")

    db_session.expire_all()
    refreshed = db_session.get(ActionApproval, pending.approval_id)
    assert refreshed is not None
    assert refreshed.decision == ApprovalDecision.EXPIRED


def test_sigterm_drain_unblocks_parked_request(
    k8s_manager: object,  # noqa: ARG001
    k8s_client: client.CoreV1Api,
    gated_session: GatedSession,
    db_session: Session,
) -> None:
    """Deleting the parked proxy pod must drain → wake → EXPIRED (well inside the wait timeout)."""
    _, session_id, pod_name = gated_session

    output_path = f"/tmp/curl_drain_{uuid4().hex[:8]}"
    _post_slack_via_curl(
        k8s_client, pod_name, output_path, text="drain me", session_id=session_id
    )

    _wait_for_pending_approval(db_session, session_id)

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
        wait_for_proxy_redeploy(k8s_client, timeout_s=180)


def test_non_gated_egress_works_without_active_session(
    k8s_manager: object,  # noqa: ARG001
    k8s_client: client.CoreV1Api,
    gated_session: GatedSession,
    db_session: Session,
) -> None:
    """Non-matching egress (npm registry) flows through untagged."""
    api_user, _, pod_name = gated_session
    user_id = UUID(api_user.id)

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

    assert _approval_count_for_user(db_session, user_id) == 0, (
        "Non-gated egress must not mint an approval row (under ANY session id)"
    )


def test_gated_egress_without_session_tag_fails_closed(
    k8s_manager: object,  # noqa: ARG001
    k8s_client: client.CoreV1Api,
    gated_session: GatedSession,
    db_session: Session,
) -> None:
    """Gated request with no session tag → 403 ``no_active_session``, no row.

    Resolution is tag-based only — no most-recent-active fallback.
    """
    api_user, _, pod_name = gated_session
    user_id = UUID(api_user.id)

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

    assert _approval_count_for_user(db_session, user_id) == 0, (
        "fail-closed before commit must not mint an approval row"
    )


def test_ask_with_uninvokable_app_forwards_bare(
    k8s_manager: object,  # noqa: ARG001 -- required to construct owned_live_pod
    k8s_client: client.CoreV1Api,
    k8s_admin_user: DATestUser,
    gated_session: GatedSession,
    db_session: Session,
) -> None:
    api_user, session_id, pod_name = gated_session
    user_id = UUID(api_user.id)

    # Strip the seeded org credential so app_is_available falls to False, and
    # restore it in finally — sibling tests in this module share the seeded
    # Slack row and need a fillable credential for the ASK gate to park.
    _upsert_slack_external_app(
        k8s_admin_user,
        organization_credentials={},
    )
    try:
        output_path = f"/tmp/curl_bare_{uuid4().hex[:8]}"
        _post_slack_via_curl(
            k8s_client,
            pod_name,
            output_path,
            text="hello",
            session_id=session_id,
        )

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
        assert _approval_count_for_user(db_session, user_id) == 0, (
            "Uninvokable ASK must not mint an approval row."
        )
    finally:
        _upsert_slack_external_app(
            k8s_admin_user,
            organization_credentials=_SEEDED_SLACK_CREDENTIALS,
        )


def test_sse_merger_emits_approval_requested_packet(
    k8s_manager: object,  # noqa: ARG001
    k8s_client: client.CoreV1Api,
    gated_session: GatedSession,
    db_session: Session,
) -> None:
    """The proxy RPUSHes the announce onto real Redis (not the full SSE path)."""
    api_user, session_id, pod_name = gated_session

    output_path = f"/tmp/curl_announce_{uuid4().hex[:8]}"
    _post_slack_via_curl(
        k8s_client, pod_name, output_path, text="announce me", session_id=session_id
    )

    pending = _wait_for_pending_approval(db_session, session_id)

    cache = get_cache_backend(tenant_id=POSTGRES_DEFAULT_SCHEMA_STANDARD_VALUE)
    popped = pop_announcement(session_id, timeout_s=5, cache=cache)
    assert popped == pending.approval_id, (
        f"announce list should contain the parked approval id "
        f"{pending.approval_id}, got {popped}"
    )

    _submit_decision(
        api_user,
        pending.approval_id,
        ApprovalDecision.REJECTED,
    )
    wait_for_pod_exec_output(k8s_client, pod_name, output_path, timeout_s=30)


def test_body_too_large_returns_403(
    k8s_manager: object,  # noqa: ARG001
    k8s_client: client.CoreV1Api,
    gated_session: GatedSession,
    db_session: Session,
) -> None:
    """Body exceeding ``PARSER_MAX_BODY_BYTES`` (32 MiB) is rejected pre-match.

    The gate rejects before the matcher runs, so no approval row is minted.
    """
    api_user, _, pod_name = gated_session
    user_id = UUID(api_user.id)

    output_path = f"/tmp/curl_oversize_{uuid4().hex[:8]}"
    body_path = f"/tmp/body_oversize_{uuid4().hex[:8]}.json"
    # Generate the body in-pod; inlining it would trip a 431 at the exec websocket handshake.
    pod_exec(
        k8s_client,
        pod_name,
        SANDBOX_NAMESPACE,
        (
            f'printf \'{{"channel":"#general","text":"\' > {body_path} && '
            f'head -c 34603008 /dev/zero | tr "\\0" x >> {body_path} && '
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

    assert _approval_count_for_user(db_session, user_id) == 0, (
        "fail-closed on oversize must not mint an approval row"
    )


def test_approval_requested_notification_is_created(
    k8s_manager: object,  # noqa: ARG001
    k8s_client: client.CoreV1Api,
    gated_session: GatedSession,
    db_session: Session,
) -> None:
    api_user, session_id, pod_name = gated_session
    user_id = UUID(api_user.id)

    output_path = f"/tmp/curl_notify_{uuid4().hex[:8]}"
    _post_slack_via_curl(
        k8s_client, pod_name, output_path, text="notify me", session_id=session_id
    )

    pending = _wait_for_pending_approval(db_session, session_id)

    notif: Notification | None = None
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        db_session.expire_all()
        # dismissed=False so a stale notification from an earlier test doesn't shadow this row.
        notif = (
            db_session.query(Notification)
            .filter(Notification.user_id == user_id)
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
        f"Expected APPROVAL_REQUESTED notification for user {user_id}, got none."
    )
    assert notif.additional_data is not None
    assert notif.additional_data.get("approval_id") == str(pending.approval_id), (
        f"notification.additional_data.approval_id should match "
        f"{pending.approval_id}, got: {notif.additional_data!r}"
    )
    assert notif.additional_data.get("link") == f"/craft/v1?sessionId={session_id}", (
        f"notification.additional_data.link should deep-link to the session, "
        f"got: {notif.additional_data!r}"
    )

    _submit_decision(
        api_user,
        pending.approval_id,
        ApprovalDecision.REJECTED,
    )
    wait_for_pod_exec_output(k8s_client, pod_name, output_path, timeout_s=30)


@pytest.mark.slow
def test_post_decision_after_proxy_claimed_expired_returns_conflict(
    k8s_manager: object,  # noqa: ARG001
    k8s_client: client.CoreV1Api,
    gated_session: GatedSession,
    db_session: Session,
) -> None:
    api_user, session_id, pod_name = gated_session

    output_path = f"/tmp/curl_conflict_{uuid4().hex[:8]}"
    _post_slack_via_curl(
        k8s_client,
        pod_name,
        output_path,
        text="conflict me",
        max_time_s=SANDBOX_APPROVAL_WAIT_TIMEOUT_SECONDS + 60,
        session_id=session_id,
    )

    pending = _wait_for_pending_approval(db_session, session_id)

    status_code, body = wait_for_pod_exec_output(
        k8s_client,
        pod_name,
        output_path,
        timeout_s=SANDBOX_APPROVAL_WAIT_TIMEOUT_SECONDS + 30,
    )
    assert status_code == 403, (
        f"Expected 403 after wait-timeout, got {status_code}: {body!r}"
    )
    _assert_403_error_code(body, "not_authorized")

    db_session.expire_all()
    refreshed = db_session.get(ActionApproval, pending.approval_id)
    assert refreshed is not None
    assert refreshed.decision == ApprovalDecision.EXPIRED, (
        f"Proxy should have claimed EXPIRED, got: {refreshed.decision}"
    )

    response = _submit_decision_response(
        api_user,
        pending.approval_id,
        ApprovalDecision.REJECTED,
    )
    assert response.status_code == 409
    assert response.json()["error_code"] == OnyxErrorCode.CONFLICT.code, (
        f"expected CONFLICT, got {response.text}"
    )


def test_unidentified_sandbox_403_from_non_sandbox_pod(
    k8s_manager: object,  # noqa: ARG001
    k8s_client: client.CoreV1Api,
    gated_session: GatedSession,  # noqa: ARG001 — for fixture chain
) -> None:
    """A pod in the sandbox namespace without the managed-by label → 403 ``unidentified_sandbox``.

    Such a pod isn't in the informer cache, so the gate rejects before matcher logic.
    """
    rogue_pod_name = f"rogue-curl-{uuid4().hex[:8]}"
    proxy_ip = _find_proxy_pod_ip(k8s_client)
    proxy_url = f"http://{proxy_ip}:{SANDBOX_PROXY_PORT}"

    # -k: no proxy CA; the gate fires on identity before any upstream TLS.
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
            # No managed-by / sandbox-id labels — the informer cache won't know this pod IP.
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
        # curl exits 0 even on HTTP errors.
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
