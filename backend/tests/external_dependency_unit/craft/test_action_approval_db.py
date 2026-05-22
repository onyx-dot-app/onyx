"""External-dependency-unit tests for the ``action_approval`` query module.

Exercises the real ORM/SQL against Postgres so schema or query regressions
(e.g. the conditional-UPDATE race arbiter, the refresh-after-UPDATE fix,
filter inclusivity) actually fail the test.
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

# ---------------------------------------------------------------------------
# Local seed helpers (no shared fixtures — each test composes what it needs).
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# insert_action_approval
# ---------------------------------------------------------------------------


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
    # created_at populated by the server default, within the call window
    # (allow a small clock skew tolerance on either side).
    assert row.created_at is not None
    skew = dt.timedelta(seconds=5)
    assert before - skew <= row.created_at <= after + skew


# ---------------------------------------------------------------------------
# try_record_decision
# ---------------------------------------------------------------------------


def test_try_record_decision_happy_path_refreshes_in_memory_row(
    db_session: Session,
    tenant_context: None,  # noqa: ARG001
    build_session_with_user: Callable[..., BuildSession],
) -> None:
    """Pins the ``db_session.refresh(row)`` fix.

    Without the refresh, the identity-mapped ORM object still shows
    ``decision=None`` even though Postgres has the new value, so this
    assertion would fail.
    """
    user = make_user(db_session)
    bs = build_session_with_user(user=user)
    row = _seed_pending(db_session, bs.id)
    assert row.decision is None  # baseline

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
    # Crucially: the SAME ORM object reference must reflect the new state.
    # If someone deletes the refresh() call, this assertion catches it.
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

    # First call wins.
    first = try_record_decision(
        db_session,
        approval_id=row.approval_id,
        decision=ApprovalDecision.APPROVED,
    )
    db_session.commit()
    assert first is not None
    assert first.decision == ApprovalDecision.APPROVED
    decided_at_initial = first.decided_at

    # Second call tries to record REJECTED on the already-decided row.
    second = try_record_decision(
        db_session,
        approval_id=row.approval_id,
        decision=ApprovalDecision.REJECTED,
    )
    db_session.commit()
    assert second is None

    # The existing APPROVED decision must be unchanged.
    fetched = get_action_approval(db_session, row.approval_id)
    assert fetched is not None
    assert fetched.decision == ApprovalDecision.APPROVED
    assert fetched.decided_at == decided_at_initial


# NOTE: A previous ``test_try_record_decision_two_sessions_only_one_wins``
# attempted to model a concurrent race using two ``get_session_with_tenant``
# blocks, but the body ran sequentially (``s1.commit()`` completed before s2
# even started its conditional UPDATE), so it didn't add coverage beyond the
# ``lost_race`` test above. It has been removed as a duplicate. The
# conditional-UPDATE arbiter is exercised by
# ``test_try_record_decision_lost_race_returns_none_and_preserves_decision``;
# the DB-level ``WHERE decision IS NULL`` guarantee makes thread interleaving
# irrelevant to the assertion.


# ---------------------------------------------------------------------------
# get_action_approval
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("case", ["known_id", "unknown_id"])
def test_get_action_approval(
    case: str,
    db_session: Session,
    tenant_context: None,  # noqa: ARG001
    build_session_with_user: Callable[..., BuildSession],
) -> None:
    """Lookup by id returns the row for ``known_id`` and ``None`` otherwise."""
    if case == "known_id":
        user = make_user(db_session)
        bs = build_session_with_user(user=user)
        row = _seed_pending(db_session, bs.id)
        fetched = get_action_approval(db_session, row.approval_id)
        assert fetched is not None
        assert fetched.approval_id == row.approval_id
    else:
        assert get_action_approval(db_session, uuid4()) is None


# ---------------------------------------------------------------------------
# get_action_approval_for_user
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("case", ["owner", "non_owner"])
def test_get_action_approval_for_user(
    case: str,
    db_session: Session,
    tenant_context: None,  # noqa: ARG001
    build_session_with_user: Callable[..., BuildSession],
) -> None:
    """Owner gets the row; non-owner gets ``None`` (callers map to NOT_FOUND
    to avoid leaking existence)."""
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


# ---------------------------------------------------------------------------
# list_session_pending_action_approvals
# ---------------------------------------------------------------------------


def test_list_session_pending_action_approvals_filters_by_created_after(
    db_session: Session,
    tenant_context: None,  # noqa: ARG001
    build_session_with_user: Callable[..., BuildSession],
) -> None:
    """``created_after`` is an inclusive lower bound on ``created_at``.

    We seed two pending rows, then force one row's ``created_at`` into
    the past (before the cutoff) via a direct UPDATE. The cutoff sits
    between the two timestamps; only the newer row should return.
    """
    user = make_user(db_session)
    bs = build_session_with_user(user=user)

    old_row = _seed_pending(db_session, bs.id, action_type="old")
    new_row = _seed_pending(db_session, bs.id, action_type="new")

    # Backdate the old row to one hour ago.
    one_hour_ago = dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=1)
    _set_created_at(db_session, ActionApproval, old_row.approval_id, one_hour_ago)

    cutoff = dt.datetime.now(dt.timezone.utc) - dt.timedelta(minutes=5)
    rows = list_session_pending_action_approvals(
        db_session, bs.id, created_after=cutoff
    )
    returned_ids = {r.approval_id for r in rows}
    assert new_row.approval_id in returned_ids
    assert old_row.approval_id not in returned_ids


# ---------------------------------------------------------------------------
# list_session_action_approvals
# ---------------------------------------------------------------------------


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
    # Sanity: APPROVED and pending rows did not leak in.
    assert approved.approval_id not in returned_ids
    assert pending.approval_id not in returned_ids


def test_list_session_action_approvals_since_until_inclusive(
    db_session: Session,
    tenant_context: None,  # noqa: ARG001
    build_session_with_user: Callable[..., BuildSession],
) -> None:
    """``since``/``until`` form a fully-inclusive interval.

    Source uses ``created_at >= since`` and ``created_at <= until``, so
    both endpoints are inclusive. We seed three rows at distinct
    timestamps and verify that a window over the middle row's exact
    timestamp returns only that row.
    """
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

    # Half-open style check: since=middle_ts (inclusive) without an upper
    # bound returns middle + late.
    rows_since = list_session_action_approvals(db_session, bs.id, since=middle_ts)
    assert {r.approval_id for r in rows_since} == {
        middle.approval_id,
        late.approval_id,
    }

    # until=middle_ts (inclusive) without a lower bound returns early + middle.
    rows_until = list_session_action_approvals(db_session, bs.id, until=middle_ts)
    assert {r.approval_id for r in rows_until} == {
        early.approval_id,
        middle.approval_id,
    }
