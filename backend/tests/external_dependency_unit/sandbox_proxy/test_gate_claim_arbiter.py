"""External-dependency-unit tests for `_claim_expired_or_read_winner`.

The race arbiter is a unit-test trap: stubbing both
`try_record_decision` and `get_action_approval` only restates the
contract those functions advertise — the test would still pass even
if the conditional UPDATE accidentally became an unconditional one.
Pin the behaviour against real Postgres rows here.
"""

from __future__ import annotations

import datetime as dt
from typing import Any
from uuid import UUID
from uuid import uuid4

from sqlalchemy.orm import Session

from onyx.db.engine.sql_engine import get_session_with_tenant
from onyx.db.enums import ApprovalDecision
from onyx.db.enums import BuildSessionStatus
from onyx.db.models import ActionApproval
from onyx.db.models import BuildSession
from onyx.sandbox_proxy.addons.gate import GateAddon
from onyx.sandbox_proxy.identity import ResolvedSandbox
from shared_configs.contextvars import POSTGRES_DEFAULT_SCHEMA
from tests.external_dependency_unit.conftest import create_test_user


def _seed_build_session(db_session: Session) -> UUID:
    """Insert a fresh user + BuildSession; return the session id.

    The action_approval row uses session_id as a FK to build_session.
    """
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
        action_type="slack.post_message",
        payload={"text": "hi"},
        decision=decision,
        decided_at=(dt.datetime.now(dt.timezone.utc) if decision is not None else None),
    )
    db_session.add(row)
    db_session.commit()
    db_session.refresh(row)
    return row


class _UnusedResolver:
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


class _UnusedMatcher:
    def match(self, request: Any) -> Any:  # noqa: ARG002
        raise AssertionError("action_matcher.match unexpectedly used")


def _build_addon() -> GateAddon:
    """Build a `GateAddon` with only `db_session_factory` wired up.

    The race arbiter doesn't touch `identity`, `action_matcher`, or
    `cache_factory`, so they can be obvious-fail stubs.
    """

    def _factory_raises(tenant_id: str) -> Any:  # noqa: ARG001
        raise AssertionError("cache_factory unexpectedly used")

    return GateAddon(
        identity=_UnusedResolver(),
        action_matcher=_UnusedMatcher(),  # type: ignore[arg-type]
        db_session_factory=lambda tenant_id: get_session_with_tenant(
            tenant_id=tenant_id
        ),
        cache_factory=_factory_raises,
        proxy_instance_id="proxy-test",
    )


def test_claim_succeeds_when_pending(
    db_session: Session,
    tenant_context: None,  # noqa: ARG001
) -> None:
    """`decision IS NULL` row → conditional UPDATE wins → EXPIRED.

    Pins the terminal-write side effect: after the call, Postgres must
    show `decision=EXPIRED` AND `decided_at` populated.
    """
    bs_id = _seed_build_session(db_session)
    row = _seed_action_approval(db_session, session_id=bs_id)
    assert row.decision is None  # baseline

    addon = _build_addon()
    decision = addon._claim_expired_or_read_winner(
        row.approval_id, POSTGRES_DEFAULT_SCHEMA
    )

    assert decision == ApprovalDecision.EXPIRED

    # Refresh through a new session — the arbiter's `db.commit()`
    # should be visible to any subsequent read.
    db_session.expire(row)
    db_session.refresh(row)
    assert row.decision == ApprovalDecision.EXPIRED
    assert row.decided_at is not None


def test_claim_reads_winning_decision(
    db_session: Session,
    tenant_context: None,  # noqa: ARG001
) -> None:
    """Row already APPROVED by the API → conditional UPDATE no-ops →
    we read the existing decision and return it. The decided_at
    timestamp must be preserved (no spurious overwrite)."""
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
    """Unknown approval_id (e.g. FK cascade fired mid-flight) → treat
    as EXPIRED so the upstream call is rejected. Critically, this must
    NOT insert a new row.
    """
    unknown_id = uuid4()

    before_count = db_session.query(ActionApproval).count()

    addon = _build_addon()
    decision = addon._claim_expired_or_read_winner(unknown_id, POSTGRES_DEFAULT_SCHEMA)

    assert decision == ApprovalDecision.EXPIRED

    after_count = db_session.query(ActionApproval).count()
    assert after_count == before_count, "claim must not insert a row"

    # And there really is no row with that id.
    assert db_session.get(ActionApproval, unknown_id) is None


def test_claim_arbiter_does_not_overwrite_decided_at(
    db_session: Session,
    tenant_context: None,  # noqa: ARG001
) -> None:
    """Losing the race must not touch ``decided_at`` on the winning row.

    Pins the "lost-race-doesn't-touch-the-winner" invariant: the conditional
    UPDATE's ``WHERE decision IS NULL`` clause guarantees zero rows are
    affected when the row is already decided, so ``decided_at`` must remain
    exactly what the original winner wrote.
    """
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

    # Caller sees the existing decision, not EXPIRED.
    assert decision == ApprovalDecision.REJECTED

    # decided_at on the winning row is bit-for-bit unchanged.
    db_session.expire(row)
    db_session.refresh(row)
    assert row.decision == ApprovalDecision.REJECTED
    assert row.decided_at == decided_at_original
