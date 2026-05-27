"""External-dependency-unit tests for the ``action_approval`` query module.

Runs real ORM/SQL against Postgres so schema/query regressions (race arbiter,
refresh-after-UPDATE, filter inclusivity) actually fail.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Callable
from uuid import UUID
from uuid import uuid4

import pytest
from sqlalchemy.orm import Session

from onyx.db.enums import ApprovalDecision
from onyx.db.models import ActionApproval
from onyx.db.models import BuildSession
from onyx.server.features.build.db.action_approval import get_action_approval
from onyx.server.features.build.db.action_approval import get_action_approval_for_user
from onyx.server.features.build.db.action_approval import insert_action_approval
from onyx.server.features.build.db.action_approval import list_session_action_approvals
from onyx.server.features.build.db.action_approval import (
    list_session_pending_action_approvals,
)
from onyx.server.features.build.db.action_approval import try_record_decision
from tests.external_dependency_unit.craft._test_helpers import _set_created_at
from tests.external_dependency_unit.craft._test_helpers import make_user


def _seed_pending(
    db_session: Session,
    session_id: UUID,
    *,
    action_type: str = "shell.exec",
    payload: dict[str, object] | None = None,
) -> ActionApproval:
    row = ActionApproval(
        session_id=session_id,
        action_type=action_type,
        payload=payload if payload is not None else {"cmd": "ls"},
    )
    db_session.add(row)
    db_session.commit()
    db_session.refresh(row)
    return row


def test_insert_action_approval_returns_pending_row(
    db_session: Session,
    tenant_context: None,  # noqa: ARG001
    build_session_with_user: Callable[..., BuildSession],
) -> None:
    user = make_user(db_session)
    bs = build_session_with_user(user=user)

    payload = {"cmd": "npm install", "cwd": "/workspace"}
    before = dt.datetime.now(dt.timezone.utc)
    row = insert_action_approval(
        db_session,
        session_id=bs.id,
        action_type="shell.exec",
        payload=payload,
    )
    db_session.commit()
    after = dt.datetime.now(dt.timezone.utc)

    assert isinstance(row.approval_id, UUID)
    assert row.session_id == bs.id
    assert row.action_type == "shell.exec"
    assert row.payload == payload
    assert row.decision is None
    assert row.decided_at is None
    # Server-default created_at, within the call window (allow clock skew).
    assert row.created_at is not None
    skew = dt.timedelta(seconds=5)
    assert before - skew <= row.created_at <= after + skew


def test_try_record_decision_happy_path_refreshes_in_memory_row(
    db_session: Session,
    tenant_context: None,  # noqa: ARG001
    build_session_with_user: Callable[..., BuildSession],
) -> None:
    """Pins the ``db_session.refresh(row)`` fix.

    Without it the identity-mapped ORM object still reads ``decision=None``
    even after Postgres has the new value.
    """
    user = make_user(db_session)
    bs = build_session_with_user(user=user)
    row = _seed_pending(db_session, bs.id)
    assert row.decision is None

    returned = try_record_decision(
        db_session,
        approval_id=row.approval_id,
        decision=ApprovalDecision.REJECTED,
    )
    db_session.commit()

    assert returned is not None
    assert returned.approval_id == row.approval_id
    assert returned.decision == ApprovalDecision.REJECTED
    assert returned.decided_at is not None
    # The same ORM object reference must reflect the new state (refresh fix).
    assert row.decision == ApprovalDecision.REJECTED
    assert row.decided_at is not None


def test_try_record_decision_lost_race_returns_none_and_preserves_decision(
    db_session: Session,
    tenant_context: None,  # noqa: ARG001
    build_session_with_user: Callable[..., BuildSession],
) -> None:
    user = make_user(db_session)
    bs = build_session_with_user(user=user)
    row = _seed_pending(db_session, bs.id)

    first = try_record_decision(
        db_session,
        approval_id=row.approval_id,
        decision=ApprovalDecision.APPROVED,
    )
    db_session.commit()
    assert first is not None
    assert first.decision == ApprovalDecision.APPROVED
    decided_at_initial = first.decided_at

    # Second call loses the race against the already-decided row.
    second = try_record_decision(
        db_session,
        approval_id=row.approval_id,
        decision=ApprovalDecision.REJECTED,
    )
    db_session.commit()
    assert second is None

    fetched = get_action_approval(db_session, row.approval_id)
    assert fetched is not None
    assert fetched.decision == ApprovalDecision.APPROVED
    assert fetched.decided_at == decided_at_initial


# A two-session concurrent-race test was removed as a duplicate: its blocks ran
# sequentially, and the DB-level ``WHERE decision IS NULL`` guard makes thread
# interleaving irrelevant — the ``lost_race`` test above already covers it.


@pytest.mark.parametrize("case", ["known_id", "unknown_id"])
def test_get_action_approval(
    case: str,
    db_session: Session,
    tenant_context: None,  # noqa: ARG001
    build_session_with_user: Callable[..., BuildSession],
) -> None:
    if case == "known_id":
        user = make_user(db_session)
        bs = build_session_with_user(user=user)
        row = _seed_pending(db_session, bs.id)
        fetched = get_action_approval(db_session, row.approval_id)
        assert fetched is not None
        assert fetched.approval_id == row.approval_id
    else:
        assert get_action_approval(db_session, uuid4()) is None


@pytest.mark.parametrize("case", ["owner", "non_owner"])
def test_get_action_approval_for_user(
    case: str,
    db_session: Session,
    tenant_context: None,  # noqa: ARG001
    build_session_with_user: Callable[..., BuildSession],
) -> None:
    """Owner gets the row; non-owner gets ``None`` (not_found, no leak)."""
    owner = make_user(db_session, email_prefix="approval_owner")
    bs = build_session_with_user(user=owner)
    row = _seed_pending(db_session, bs.id)

    if case == "owner":
        fetched = get_action_approval_for_user(db_session, row.approval_id, owner.id)
        assert fetched is not None
        assert fetched.approval_id == row.approval_id
    else:
        other = make_user(db_session, email_prefix="approval_intruder")
        fetched = get_action_approval_for_user(db_session, row.approval_id, other.id)
        assert fetched is None


def test_list_session_pending_action_approvals_filters_by_created_after(
    db_session: Session,
    tenant_context: None,  # noqa: ARG001
    build_session_with_user: Callable[..., BuildSession],
) -> None:
    """``created_after`` is an inclusive lower bound; cutoff between the two rows."""
    user = make_user(db_session)
    bs = build_session_with_user(user=user)

    old_row = _seed_pending(db_session, bs.id, action_type="old")
    new_row = _seed_pending(db_session, bs.id, action_type="new")

    one_hour_ago = dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=1)
    _set_created_at(db_session, ActionApproval, old_row.approval_id, one_hour_ago)

    cutoff = dt.datetime.now(dt.timezone.utc) - dt.timedelta(minutes=5)
    rows = list_session_pending_action_approvals(
        db_session, bs.id, created_after=cutoff
    )
    returned_ids = {r.approval_id for r in rows}
    assert new_row.approval_id in returned_ids
    assert old_row.approval_id not in returned_ids


def test_list_session_action_approvals_filters_by_decision(
    db_session: Session,
    tenant_context: None,  # noqa: ARG001
    build_session_with_user: Callable[..., BuildSession],
) -> None:
    user = make_user(db_session)
    bs = build_session_with_user(user=user)

    approved = _seed_pending(db_session, bs.id, action_type="a")
    rejected = _seed_pending(db_session, bs.id, action_type="b")
    pending = _seed_pending(db_session, bs.id, action_type="c")

    try_record_decision(
        db_session,
        approval_id=approved.approval_id,
        decision=ApprovalDecision.APPROVED,
    )
    try_record_decision(
        db_session,
        approval_id=rejected.approval_id,
        decision=ApprovalDecision.REJECTED,
    )
    db_session.commit()

    rows = list_session_action_approvals(
        db_session, bs.id, decision=ApprovalDecision.REJECTED
    )
    returned_ids = {r.approval_id for r in rows}
    assert returned_ids == {rejected.approval_id}
    assert approved.approval_id not in returned_ids
    assert pending.approval_id not in returned_ids


def test_list_session_action_approvals_since_until_inclusive(
    db_session: Session,
    tenant_context: None,  # noqa: ARG001
    build_session_with_user: Callable[..., BuildSession],
) -> None:
    """``since``/``until`` form a fully-inclusive interval (>= since, <= until)."""
    user = make_user(db_session)
    bs = build_session_with_user(user=user)

    base = dt.datetime.now(dt.timezone.utc).replace(microsecond=0)
    early_ts = base - dt.timedelta(hours=2)
    middle_ts = base - dt.timedelta(hours=1)
    late_ts = base

    early = _seed_pending(db_session, bs.id, action_type="early")
    middle = _seed_pending(db_session, bs.id, action_type="middle")
    late = _seed_pending(db_session, bs.id, action_type="late")
    for row, ts in ((early, early_ts), (middle, middle_ts), (late, late_ts)):
        _set_created_at(db_session, ActionApproval, row.approval_id, ts)

    # Window covering only the middle row's exact timestamp.
    rows = list_session_action_approvals(
        db_session, bs.id, since=middle_ts, until=middle_ts
    )
    assert {r.approval_id for r in rows} == {middle.approval_id}

    # since=middle_ts (inclusive), no upper bound → middle + late.
    rows_since = list_session_action_approvals(db_session, bs.id, since=middle_ts)
    assert {r.approval_id for r in rows_since} == {
        middle.approval_id,
        late.approval_id,
    }

    # until=middle_ts (inclusive), no lower bound → early + middle.
    rows_until = list_session_action_approvals(db_session, bs.id, until=middle_ts)
    assert {r.approval_id for r in rows_until} == {
        early.approval_id,
        middle.approval_id,
    }
