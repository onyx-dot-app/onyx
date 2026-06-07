"""External-dependency-unit tests for `_claim_expired_or_read_winner`.

Run against real Postgres rows: stubbing `try_record_decision` /
`get_action_approval` would pass even if the conditional UPDATE became
unconditional, so the race behaviour is pinned against the real DB.
"""

from __future__ import annotations

import datetime as dt
from typing import Any
from uuid import UUID
from uuid import uuid4

from sqlalchemy.orm import Session

from onyx.db.enums import ApprovalDecision
from onyx.db.enums import BuildSessionStatus
from onyx.db.models import ActionApproval
from onyx.db.models import BuildSession
from onyx.sandbox_proxy.addons.gate import _IdentityResolver
from onyx.sandbox_proxy.addons.gate import GateAddon
from onyx.sandbox_proxy.credential_injection import CredentialInjectionDispatcher
from onyx.sandbox_proxy.identity import ResolvedSandbox
from onyx.sandbox_proxy.request_evaluator import RequestEvaluator
from shared_configs.contextvars import POSTGRES_DEFAULT_SCHEMA
from tests.external_dependency_unit.conftest import create_test_user
from tests.external_dependency_unit.craft._test_helpers import action_entry


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


class _UnusedResolver(_IdentityResolver):
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


def _build_addon() -> GateAddon:
    """`GateAddon` for the claim arbiter; it opens its own tenant session via
    `get_session_with_tenant`, so the identity/matcher/cache deps are
    obvious-fail stubs the arbiter never touches."""

    def _factory_raises(tenant_id: str) -> Any:  # noqa: ARG001
        raise AssertionError("cache_factory unexpectedly used")

    return GateAddon(
        identity=_UnusedResolver(),
        request_evaluator=_UnusedMatcher(),
        cache_factory=_factory_raises,
        proxy_instance_id="proxy-test",
        credential_dispatcher=CredentialInjectionDispatcher([]),
    )


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
