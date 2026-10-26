"""External-dependency-unit tests for GateAddon persistence and race behavior.

Run against real Postgres rows so transaction visibility and conditional
updates are tested rather than inferred from mocked session calls.
"""

from __future__ import annotations

import datetime as dt
from typing import Any
from unittest.mock import MagicMock
from uuid import UUID, uuid4

import pytest
from mitmproxy import http
from redis.exceptions import RedisError
from sqlalchemy import select
from sqlalchemy.orm import Session

from onyx.cache.factory import get_cache_backend
from onyx.configs.constants import NotificationType
from onyx.db.action_policy import get_or_create_gated_app_id
from onyx.db.engine.sql_engine import get_session_with_tenant
from onyx.db.enums import (
    ActionPolicy,
    ApprovalDecidedVia,
    ApprovalDecision,
    BuildSessionStatus,
    GatedAppKind,
    ScheduledTaskRunStatus,
    ScheduledTaskTriggerSource,
)
from onyx.db.models import (
    ActionApproval,
    BuildSession,
    GatedApp,
    MCPServer,
    Notification,
    ScheduledTask,
    ScheduledTaskActionPolicy,
    ScheduledTaskEnabledApp,
    ScheduledTaskRun,
    UserActionPolicy,
)
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.external_apps.matching.engine import (
    AllMatchedActions,
    GatedTarget,
    MatchedAction,
)
from onyx.sandbox_proxy import approval_cache
from onyx.sandbox_proxy.addons.gate import GateAddon
from onyx.sandbox_proxy.credential_injection import CredentialInjectionDispatcher
from onyx.sandbox_proxy.destination_policy import parse_destination_policy
from onyx.sandbox_proxy.request_evaluator import RequestEvaluator
from onyx.sandbox_proxy.sandbox_identity.models import ResolvedSandbox, SessionContext
from onyx.sandbox_proxy.sandbox_identity.resolution import SandboxIdentityResolver
from shared_configs.contextvars import POSTGRES_DEFAULT_SCHEMA
from tests.common.craft.payloads import action_entry
from tests.external_dependency_unit.conftest import create_test_user
from tests.external_dependency_unit.craft.db_helpers import (
    make_external_app,
    make_skill,
)


def _seed_build_session(db_session: Session) -> UUID:
    """Insert a fresh user + BuildSession (FK target for action_approval);
    return the session id."""
    user = create_test_user(db_session, "gate_claim_arbiter")
    bs = BuildSession(
        id=uuid4(),
        user_id=user.id,
        status=BuildSessionStatus.ACTIVE,
        last_activity_at=dt.datetime.now(dt.timezone.utc),
    )
    db_session.add(bs)
    db_session.commit()
    return bs.id


def _seed_action_approval(
    db_session: Session,
    *,
    session_id: UUID,
    decision: ApprovalDecision | None = None,
) -> ActionApproval:
    """Insert one action_approval row with optional pre-recorded decision."""
    row = ActionApproval(
        session_id=session_id,
        actions=[
            action_entry(
                "slack.messages.write",
                display_name="Post a message",
                description="Post a message to a channel or conversation.",
            )
        ],
        app_name="Slack",
        payload={"text": "hi"},
        decision=decision,
        decided_at=(dt.datetime.now(dt.timezone.utc) if decision is not None else None),
    )
    db_session.add(row)
    db_session.commit()
    db_session.refresh(row)
    return row


class _UnusedResolver(SandboxIdentityResolver):
    """Obvious-fail stub for the arbiter tests; none of these are called."""

    def resolve_sandbox(self, src_ip: str) -> ResolvedSandbox | None:  # noqa: ARG002
        raise AssertionError("identity.resolve_sandbox unexpectedly used")

    def resolve_session_by_id(
        self,
        session_id: UUID,  # noqa: ARG002
        user_id: UUID,  # noqa: ARG002
        tenant_id: str,  # noqa: ARG002
    ) -> UUID | None:
        raise AssertionError("identity.resolve_session_by_id unexpectedly used")


class _UnusedMatcher(RequestEvaluator):
    def evaluate(self, request: Any, tenant_id: str, user_id: UUID) -> Any:  # noqa: ARG002
        raise AssertionError("request_evaluator.evaluate unexpectedly used")


def _build_addon(cache_factory: Any | None = None) -> GateAddon:
    """`GateAddon` for DB-focused tests with unused request-path dependencies."""

    def _factory_raises(tenant_id: str) -> Any:  # noqa: ARG001
        raise AssertionError("cache_factory unexpectedly used")

    return GateAddon(
        destination_policy=parse_destination_policy(""),
        identity=_UnusedResolver(),
        request_evaluator=_UnusedMatcher(),
        cache_factory=cache_factory or _factory_raises,
        proxy_instance_id="proxy-test",
        credential_dispatcher=CredentialInjectionDispatcher([]),
    )


@pytest.mark.parametrize("announce_fails", [False, True], ids=["success", "failure"])
def test_persist_approval_row_commits_before_announce_and_notifies(
    db_session: Session,
    tenant_context: None,  # noqa: ARG001
    monkeypatch: pytest.MonkeyPatch,
    announce_fails: bool,
) -> None:
    """The approval is visible before announce, and a Redis failure does not
    undo persistence or prevent the notification side effect."""
    session_id = _seed_build_session(db_session)
    build_session = db_session.get(BuildSession, session_id)
    assert build_session is not None
    assert build_session.user_id is not None
    user_id = build_session.user_id

    skill = make_skill(db_session, author_user_id=user_id)
    external_app = make_external_app(db_session, skill=skill, auth_template={})
    db_session.commit()

    matched_actions = AllMatchedActions(
        actions=(
            MatchedAction(
                action_type="slack.messages.write",
                display_name="Post a message",
                description="Post a message to a channel or conversation.",
                policy=ActionPolicy.ASK,
            ),
        ),
        target=GatedTarget(
            kind=GatedAppKind.EXTERNAL_APP,
            id=external_app.id,
            app_name=external_app.name,
        ),
        payload={"text": "hi"},
    )
    ctx = SessionContext(
        session_id=session_id,
        user_id=user_id,
        sandbox_id=uuid4(),
        tenant_id=POSTGRES_DEFAULT_SCHEMA,
        sandbox_name="sandbox-gate-persistence",
        sandbox_ip="10.0.0.1",
    )

    announced: list[tuple[UUID, UUID]] = []
    cache = get_cache_backend(tenant_id=POSTGRES_DEFAULT_SCHEMA)
    real_announce = approval_cache.announce_approval

    def _announce(
        approval_id: UUID, announced_session_id: UUID, announcement_cache: Any
    ) -> None:
        assert announcement_cache is cache
        with get_session_with_tenant(tenant_id=POSTGRES_DEFAULT_SCHEMA) as probe:
            persisted = probe.get(ActionApproval, approval_id)
            assert persisted is not None
            assert persisted.session_id == session_id
            assert persisted.payload == matched_actions.payload
        announced.append((approval_id, announced_session_id))
        if announce_fails:
            raise RedisError("connection refused")
        real_announce(approval_id, announced_session_id, announcement_cache)

    monkeypatch.setattr(approval_cache, "announce_approval", _announce)
    addon = _build_addon(cache_factory=lambda _tenant_id: cache)

    approval_id = addon._persist_approval_row(ctx, matched_actions)

    assert announced == [(approval_id, session_id)]
    if not announce_fails:
        assert (
            approval_cache.pop_announcement(session_id, timeout_s=1, cache=cache)
            == approval_id
        )
    assert dict(addon._parked.snapshot()) == {POSTGRES_DEFAULT_SCHEMA: {approval_id}}

    db_session.expire_all()
    persisted = db_session.get(ActionApproval, approval_id)
    assert persisted is not None
    assert persisted.actions == [
        action.model_dump(mode="json") for action in matched_actions.actions
    ]
    assert persisted.app_name == external_app.name
    assert persisted.payload == matched_actions.payload

    notification = db_session.scalar(
        select(Notification).where(
            Notification.user_id == user_id,
            Notification.notif_type == NotificationType.APPROVAL_REQUESTED,
        )
    )
    assert notification is not None
    assert notification.title == "Craft is requesting approval"
    assert notification.additional_data == {
        "approval_id": str(approval_id),
        "session_id": str(session_id),
        "action_type": matched_actions.governing_action.action_type,
        "action_count": len(matched_actions.actions),
        "app_name": external_app.name,
        "link": f"/craft/v1?sessionId={session_id}",
    }


def test_claim_succeeds_when_pending(
    db_session: Session,
    tenant_context: None,  # noqa: ARG001
) -> None:
    """`decision IS NULL` row → conditional UPDATE wins → EXPIRED, with
    `decided_at` populated in Postgres."""
    bs_id = _seed_build_session(db_session)
    row = _seed_action_approval(db_session, session_id=bs_id)
    assert row.decision is None

    addon = _build_addon()
    decision = addon._claim_expired_or_read_winner(
        row.approval_id, POSTGRES_DEFAULT_SCHEMA
    )

    assert decision == ApprovalDecision.EXPIRED

    # Re-read to confirm the arbiter's commit is visible to other readers.
    db_session.expire(row)
    db_session.refresh(row)
    assert row.decision == ApprovalDecision.EXPIRED
    assert row.decided_at is not None


def test_claim_reads_winning_decision(
    db_session: Session,
    tenant_context: None,  # noqa: ARG001
) -> None:
    """Row already APPROVED → conditional UPDATE no-ops → existing decision is
    read back with `decided_at` preserved."""
    bs_id = _seed_build_session(db_session)
    row = _seed_action_approval(
        db_session, session_id=bs_id, decision=ApprovalDecision.APPROVED
    )
    decided_at_initial = row.decided_at

    addon = _build_addon()
    decision = addon._claim_expired_or_read_winner(
        row.approval_id, POSTGRES_DEFAULT_SCHEMA
    )

    assert decision == ApprovalDecision.APPROVED

    db_session.expire(row)
    db_session.refresh(row)
    assert row.decision == ApprovalDecision.APPROVED
    assert row.decided_at == decided_at_initial


def test_claim_returns_expired_when_row_missing(
    db_session: Session,
    tenant_context: None,  # noqa: ARG001
) -> None:
    """Unknown approval_id → treat as EXPIRED (reject upstream) without
    inserting a row."""
    unknown_id = uuid4()

    before_count = db_session.query(ActionApproval).count()

    addon = _build_addon()
    decision = addon._claim_expired_or_read_winner(unknown_id, POSTGRES_DEFAULT_SCHEMA)

    assert decision == ApprovalDecision.EXPIRED

    after_count = db_session.query(ActionApproval).count()
    assert after_count == before_count, "claim must not insert a row"

    assert db_session.get(ActionApproval, unknown_id) is None


def test_claim_arbiter_does_not_overwrite_decided_at(
    db_session: Session,
    tenant_context: None,  # noqa: ARG001
) -> None:
    """Losing the race must not touch ``decided_at`` on the winning row: the
    ``WHERE decision IS NULL`` clause affects zero rows when already decided."""
    bs_id = _seed_build_session(db_session)
    row = _seed_action_approval(
        db_session, session_id=bs_id, decision=ApprovalDecision.REJECTED
    )
    decided_at_original = row.decided_at
    assert decided_at_original is not None

    addon = _build_addon()
    decision = addon._claim_expired_or_read_winner(
        row.approval_id, POSTGRES_DEFAULT_SCHEMA
    )

    assert decision == ApprovalDecision.REJECTED

    db_session.expire(row)
    db_session.refresh(row)
    assert row.decision == ApprovalDecision.REJECTED
    assert row.decided_at == decided_at_original


def test_gate_reads_task_settings_and_rejects_finished_run(
    db_session: Session,
    tenant_context: None,  # noqa: ARG001
) -> None:
    session_id = _seed_build_session(db_session)
    session = db_session.get(BuildSession, session_id)
    assert session is not None and session.user_id is not None
    app = make_external_app(db_session, skill=make_skill(db_session), auth_template={})
    gated_app_id = get_or_create_gated_app_id(
        db_session, GatedAppKind.EXTERNAL_APP, app.id
    )
    task = ScheduledTask(
        user_id=session.user_id,
        name="Report",
        prompt="Create a report",
        cron_expression="0 9 * * *",
        editor_mode="advanced",
    )
    db_session.add(task)
    db_session.flush()
    run = ScheduledTaskRun(
        task_id=task.id,
        session_id=session_id,
        status=ScheduledTaskRunStatus.RUNNING,
        trigger_source=ScheduledTaskTriggerSource.SCHEDULED,
    )
    task_policy = ScheduledTaskActionPolicy(
        scheduled_task_id=task.id,
        gated_app_id=gated_app_id,
        action_id="send_message",
        policy=ActionPolicy.ALWAYS,
    )
    db_session.add_all(
        [
            run,
            ScheduledTaskEnabledApp(
                scheduled_task_id=task.id, gated_app_id=gated_app_id
            ),
            task_policy,
            UserActionPolicy(
                user_id=session.user_id,
                gated_app_id=gated_app_id,
                action_id="send_message",
                policy=ActionPolicy.DENY,
            ),
        ]
    )
    db_session.commit()
    ctx = SessionContext(
        session_id=session_id,
        user_id=session.user_id,
        sandbox_id=uuid4(),
        tenant_id=POSTGRES_DEFAULT_SCHEMA,
        sandbox_name="sandbox-permissions",
        sandbox_ip="10.0.0.1",
    )
    recognized = AllMatchedActions(
        target=GatedTarget(
            kind=GatedAppKind.EXTERNAL_APP, id=app.id, app_name=app.name
        ),
        actions=(
            MatchedAction(
                action_type="send_message",
                display_name="Send message",
                description="Send a message",
                policy=ActionPolicy.ASK,
            ),
        ),
    )
    addon = _build_addon()
    active_ctx, resolved = addon._resolve_request_policies(ctx, recognized)
    assert active_ctx.scheduled_context == (run.id, task.id)
    assert resolved.governing_action.policy is ActionPolicy.ALWAYS

    task_policy.policy = ActionPolicy.ASK
    db_session.commit()
    _, resolved = addon._resolve_request_policies(ctx, recognized)
    assert resolved.governing_action.policy is ActionPolicy.ASK

    run.status = ScheduledTaskRunStatus.SUCCEEDED
    db_session.commit()
    with pytest.raises(
        OnyxError, match="Scheduled execution is no longer active"
    ) as exc:
        addon._resolve_request_policies(ctx, recognized)
    assert exc.value.error_code is OnyxErrorCode.INSUFFICIENT_PERMISSIONS


@pytest.mark.parametrize(
    "source", [ApprovalDecidedVia.USER, ApprovalDecidedVia.SESSION_GRANT]
)
def test_woken_request_rechecks_persisted_approval_scope(
    db_session: Session,
    tenant_context: None,  # noqa: ARG001
    monkeypatch: pytest.MonkeyPatch,
    source: ApprovalDecidedVia,
) -> None:
    """A session-approved pending batch cannot gain another action during its wait."""
    session_id = _seed_build_session(db_session)
    session = db_session.get(BuildSession, session_id)
    assert session is not None and session.user_id is not None
    app = make_external_app(db_session, skill=make_skill(db_session), auth_template={})
    gated_app_id = get_or_create_gated_app_id(
        db_session, GatedAppKind.EXTERNAL_APP, app.id
    )
    recognized = AllMatchedActions(
        target=GatedTarget(
            kind=GatedAppKind.EXTERNAL_APP, id=app.id, app_name=app.name
        ),
        actions=(
            MatchedAction(
                action_type="send",
                display_name="Send",
                description="Send",
                policy=ActionPolicy.ASK,
            ),
            MatchedAction(
                action_type="read",
                display_name="Read",
                description="Read",
                policy=ActionPolicy.ALWAYS,
            ),
        ),
    )
    approval = ActionApproval(
        session_id=session_id,
        gated_app_id=gated_app_id,
        actions=[action.model_dump(mode="json") for action in recognized.actions],
        app_name=app.name,
        payload={},
        decision=ApprovalDecision.APPROVED,
        decided_via=source,
    )
    db_session.add(approval)
    db_session.commit()
    ctx = SessionContext(
        session_id=session_id,
        user_id=session.user_id,
        sandbox_id=uuid4(),
        tenant_id=POSTGRES_DEFAULT_SCHEMA,
        sandbox_name="sandbox-persisted-scope",
        sandbox_ip="10.0.0.1",
    )
    addon = _build_addon(
        cache_factory=lambda tenant: get_cache_backend(tenant_id=tenant)
    )
    initial_ctx, initial_actions = addon._resolve_request_policies(ctx, recognized)
    db_session.add(
        UserActionPolicy(
            user_id=session.user_id,
            gated_app_id=gated_app_id,
            action_id="read",
            policy=ActionPolicy.ASK,
        )
    )
    db_session.commit()
    monkeypatch.setattr(addon._request_evaluator, "evaluate", lambda *_args: recognized)
    flow = MagicMock(spec=http.HTTPFlow)
    flow.request = MagicMock()
    flow.response = None
    allowed = addon._recheck_approval(
        flow, initial_ctx, initial_actions, approval.approval_id
    )
    if source is ApprovalDecidedVia.SESSION_GRANT:
        assert allowed is None
        assert flow.response is not None
        assert flow.response.status_code == 403
        assert flow.response.json()["error"] == "not_authorized"
    else:
        assert allowed is not None
        assert flow.response is None


@pytest.mark.parametrize("kind", [GatedAppKind.EXTERNAL_APP, GatedAppKind.MCP_SERVER])
@pytest.mark.parametrize("users_manage", [True, False])
@pytest.mark.parametrize(
    "source", [None, ApprovalDecidedVia.USER, ApprovalDecidedVia.SESSION_GRANT]
)
def test_disabling_task_app_blocks_all_approval_paths(
    db_session: Session,
    tenant_context: None,  # noqa: ARG001
    monkeypatch: pytest.MonkeyPatch,
    kind: GatedAppKind,
    users_manage: bool,
    source: ApprovalDecidedVia | None,
) -> None:
    session_id = _seed_build_session(db_session)
    session = db_session.get(BuildSession, session_id)
    assert session is not None and session.user_id is not None
    if kind is GatedAppKind.EXTERNAL_APP:
        target = make_external_app(
            db_session, skill=make_skill(db_session), auth_template={}
        )
    else:
        target = MCPServer(
            name="Task MCP",
            owner="admin@example.com",
            server_url="https://example.com/mcp",
            available_in_craft=True,
        )
        db_session.add(target)
        db_session.flush()
    gated_app_id = get_or_create_gated_app_id(db_session, kind, target.id)
    gated_app = db_session.get(GatedApp, gated_app_id)
    assert gated_app is not None
    gated_app.users_can_manage_policies = users_manage
    task = ScheduledTask(
        user_id=session.user_id,
        name="Report",
        prompt="Report",
        cron_expression="0 9 * * *",
        editor_mode="advanced",
    )
    db_session.add(task)
    db_session.flush()
    membership = ScheduledTaskEnabledApp(
        scheduled_task_id=task.id, gated_app_id=gated_app_id
    )
    policy = ActionPolicy.ALWAYS if source is None else ActionPolicy.ASK
    db_session.add_all(
        [
            membership,
            ScheduledTaskRun(
                task_id=task.id,
                session_id=session_id,
                status=ScheduledTaskRunStatus.RUNNING,
                trigger_source=ScheduledTaskTriggerSource.SCHEDULED,
            ),
            ScheduledTaskActionPolicy(
                scheduled_task_id=task.id,
                gated_app_id=gated_app_id,
                action_id="send",
                policy=policy,
            ),
        ]
    )
    db_session.commit()
    ctx = SessionContext(
        session_id=session_id,
        user_id=session.user_id,
        sandbox_id=uuid4(),
        tenant_id=POSTGRES_DEFAULT_SCHEMA,
        sandbox_name="task-app-disable",
        sandbox_ip="10.0.0.1",
    )
    recognized = AllMatchedActions(
        target=GatedTarget(kind=kind, id=target.id, app_name=target.name),
        actions=(
            MatchedAction(
                action_type="send",
                display_name="Send",
                description="Send",
                policy=policy,
            ),
        ),
    )
    addon = _build_addon()
    active_ctx, initial_actions = addon._resolve_request_policies(ctx, recognized)
    assert initial_actions.governing_action.policy is policy
    assert addon._task_can_use_app(ctx, recognized.target)
    approval = None
    if source is not None:
        approval = ActionApproval(
            session_id=session_id,
            gated_app_id=gated_app_id,
            actions=[a.model_dump(mode="json") for a in recognized.actions],
            app_name=target.name,
            payload={},
            decision=ApprovalDecision.APPROVED,
            decided_via=source,
        )
        db_session.add(approval)
    db_session.delete(membership)
    db_session.commit()

    _, disabled = addon._resolve_request_policies(ctx, recognized)
    assert disabled.governing_action.policy is ActionPolicy.DENY
    assert not addon._task_can_use_app(ctx, recognized.target)
    unknown = AllMatchedActions(
        target=recognized.target,
        actions=(
            MatchedAction(
                action_type="unspecified"
                if kind is GatedAppKind.EXTERNAL_APP
                else "new_tool",
                display_name="Unknown",
                description="Unknown",
                policy=ActionPolicy.ASK,
            ),
        ),
    )
    _, unknown_disabled = addon._resolve_request_policies(ctx, unknown)
    assert unknown_disabled.governing_action.policy is ActionPolicy.DENY
    if approval is not None:
        monkeypatch.setattr(
            addon._request_evaluator, "evaluate", lambda *_args: recognized
        )
        flow = MagicMock(spec=http.HTTPFlow)
        flow.request = MagicMock()
        flow.response = None
        assert (
            addon._recheck_approval(
                flow, active_ctx, initial_actions, approval.approval_id
            )
            is None
        )
        assert flow.response is not None
        assert flow.response.status_code == 403
        assert flow.response.json()["error"] == "policy_denied"
