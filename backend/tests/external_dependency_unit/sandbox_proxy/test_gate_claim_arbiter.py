"""External-dependency-unit tests for GateAddon persistence and race behavior.

Run against real Postgres rows so transaction visibility and conditional
updates are tested rather than inferred from mocked session calls.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Generator
from typing import Any
from unittest.mock import MagicMock
from uuid import UUID, uuid4

import pytest
from mitmproxy import http
from redis.exceptions import RedisError
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from onyx.cache.factory import get_cache_backend
from onyx.configs.constants import NotificationType
from onyx.db.engine.sql_engine import get_session_with_tenant
from onyx.db.enums import (
    ActionPolicy,
    ApprovalDecidedVia,
    ApprovalDecision,
    BuildSessionStatus,
    IntegrationActionPolicyValue,
    IntegrationKind,
    PluginInstallationPolicy,
)
from onyx.db.models import (
    ActionApproval,
    BuildSession,
    Integration,
    Notification,
    Skill,
)
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
    app_integration_id,
    make_external_app,
    make_skill,
)
from tests.external_dependency_unit.integration_helpers import (
    delete_integrations,
    give_access,
    make_mcp_integration,
    set_policy,
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
    def evaluate(
        self,
        request: Any,  # noqa: ARG002
        tenant_id: str,  # noqa: ARG002
        user_id: UUID,  # noqa: ARG002
    ) -> Any:
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
    skill_ids: list[UUID],
    integration_ids: list[int],
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
    skill_ids.append(skill.id)
    integration_ids.append(app_integration_id(db_session, external_app))

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
            integration_id=app_integration_id(db_session, external_app),
            kind=IntegrationKind.API,
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
    assert persisted.integration_id == app_integration_id(db_session, external_app)

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


@pytest.fixture
def skill_ids(
    db_session: Session,
    tenant_context: None,  # noqa: ARG001
) -> Generator[list[UUID], None, None]:
    """Deletes the skills after the integrations that hold them."""
    created: list[UUID] = []
    try:
        yield created
    finally:
        db_session.rollback()
        db_session.execute(delete(Skill).where(Skill.id.in_(created)))
        db_session.commit()


@pytest.fixture
def integration_ids(
    db_session: Session,
    tenant_context: None,  # noqa: ARG001
) -> Generator[list[int], None, None]:
    created: list[int] = []
    try:
        yield created
    finally:
        delete_integrations(db_session, created)


def _session_ctx(db_session: Session) -> SessionContext:
    session_id = _seed_build_session(db_session)
    session = db_session.get(BuildSession, session_id)
    assert session is not None and session.user_id is not None
    return SessionContext(
        session_id=session_id,
        user_id=session.user_id,
        sandbox_id=uuid4(),
        tenant_id=POSTGRES_DEFAULT_SCHEMA,
        sandbox_name="sandbox-permissions",
        sandbox_ip="10.0.0.1",
    )


def _recognized(integration: Integration, *actions: MatchedAction) -> AllMatchedActions:
    return AllMatchedActions(
        target=GatedTarget(
            integration_id=integration.id,
            kind=integration.kind,
            app_name=integration.name,
        ),
        actions=actions,
    )


def _action(action_type: str, policy: ActionPolicy = ActionPolicy.ASK) -> MatchedAction:
    return MatchedAction(
        action_type=action_type,
        display_name=action_type,
        description=action_type,
        policy=policy,
    )


def _published(db_session: Session, integration: Integration) -> None:
    give_access(
        db_session,
        [integration],
        published=True,
        installation_policy=PluginInstallationPolicy.DEFAULT,
    )


@pytest.mark.parametrize(
    "source", [ApprovalDecidedVia.USER, ApprovalDecidedVia.SESSION_GRANT]
)
def test_woken_request_rechecks_persisted_approval_scope(
    db_session: Session,
    integration_ids: list[int],
    monkeypatch: pytest.MonkeyPatch,
    source: ApprovalDecidedVia,
) -> None:
    """A session-approved pending batch cannot gain another action during its wait."""
    integration, _ = make_mcp_integration(
        db_session,
        server_url=f"https://{uuid4().hex[:8]}.example.com/mcp",
        name="Batch MCP",
        tools=("send", "read"),
        read_only={"read": True},
    )
    integration_ids.append(integration.id)
    _published(db_session, integration)
    ctx = _session_ctx(db_session)
    recognized = _recognized(
        integration, _action("send"), _action("read", ActionPolicy.ALWAYS)
    )
    approval = ActionApproval(
        session_id=ctx.session_id,
        integration_id=integration.id,
        actions=[action.model_dump(mode="json") for action in recognized.actions],
        app_name=integration.name,
        payload={},
        decision=ApprovalDecision.APPROVED,
        decided_via=source,
    )
    db_session.add(approval)
    db_session.commit()
    addon = _build_addon(
        cache_factory=lambda tenant: get_cache_backend(tenant_id=tenant)
    )
    initial_actions = addon._resolve_request_policies(ctx, recognized)
    set_policy(db_session, integration.id, "read", IntegrationActionPolicyValue.ASK)
    monkeypatch.setattr(addon._request_evaluator, "evaluate", lambda *_args: recognized)
    flow = MagicMock(spec=http.HTTPFlow)
    flow.request = MagicMock()
    flow.response = None
    allowed = addon._recheck_approval(flow, ctx, initial_actions, approval.approval_id)
    if source is ApprovalDecidedVia.SESSION_GRANT:
        assert allowed is None
        assert flow.response is not None
        assert flow.response.status_code == 403
        assert flow.response.json()["error"] == "not_authorized"
    else:
        assert allowed is not None
        assert flow.response is None
