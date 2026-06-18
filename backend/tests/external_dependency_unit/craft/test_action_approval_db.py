"""External-dependency-unit tests for the ``action_approval`` query module.

Runs real ORM/SQL against Postgres so schema/query regressions (race arbiter,
refresh-after-UPDATE, filter inclusivity) actually fail.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Callable
from typing import Any
from uuid import UUID
from uuid import uuid4

import pytest
from sqlalchemy.orm import Session

from onyx.db.enums import ApprovalDecision
from onyx.db.enums import EndpointPolicy
from onyx.db.models import ActionApproval
from onyx.db.models import BuildSession
from onyx.server.features.build.db.action_approval import get_action_approval
from onyx.server.features.build.db.action_approval import get_action_approval_for_user
from onyx.server.features.build.db.action_approval import insert_action_approval
from onyx.server.features.build.db.action_approval import (
    list_session_pending_action_approvals,
)
from onyx.server.features.build.db.action_approval import try_record_decision
from tests.external_dependency_unit.craft._test_helpers import _set_created_at
from tests.external_dependency_unit.craft._test_helpers import action_entry
from tests.external_dependency_unit.craft._test_helpers import default_action_entries
from tests.external_dependency_unit.craft._test_helpers import make_user


def _seed_pending(
    db_session: Session,
    session_id: UUID,
    *,
    actions: list[dict[str, Any]] | None = None,
    app_name: str = "Shell",
    payload: dict[str, Any] | None = None,
) -> ActionApproval:
    """Seed a pending row via the public insert helper so the non-empty +
    strictest-first invariants are enforced on the seeded data too."""
    row = insert_action_approval(
        db_session,
        session_id=session_id,
        actions=actions if actions is not None else default_action_entries(),
        app_name=app_name,
        payload=payload if payload is not None else {"cmd": "ls"},
    )
    db_session.commit()
    db_session.refresh(row)
    return row


def test_insert_action_approval_sorts_actions_strictest_first(
    db_session: Session,
    tenant_context: None,  # noqa: ARG001
    build_session_with_user: Callable[..., BuildSession],
) -> None:
    """Every reader assumes ``actions[0]`` is strictest, so the helper
    re-sorts defensively — callers that pass a catalog-ordered list still
    end up with strictest-first on the row."""
    user = make_user(db_session)
    bs = build_session_with_user(user=user)
    laxest_first = [
        action_entry("x.read", policy=EndpointPolicy.ALWAYS),
        action_entry("x.write", policy=EndpointPolicy.ASK),
    ]
    row = insert_action_approval(
        db_session,
        session_id=bs.id,
        actions=laxest_first,
        app_name="X",
        payload={},
    )
    assert [a["policy"] for a in row.actions] == ["ASK", "ALWAYS"]


def test_insert_action_approval_rejects_empty_actions(
    db_session: Session,
    tenant_context: None,  # noqa: ARG001
    build_session_with_user: Callable[..., BuildSession],
) -> None:
    """At least one catalog action must drive a gated approval row."""
    user = make_user(db_session)
    bs = build_session_with_user(user=user)

    with pytest.raises(ValueError, match="actions must be non-empty"):
        insert_action_approval(
            db_session,
            session_id=bs.id,
            actions=[],
            app_name="Shell",
            payload={"cmd": "ls"},
        )


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

    old_row = _seed_pending(db_session, bs.id, payload={"cmd": "old"})
    new_row = _seed_pending(db_session, bs.id, payload={"cmd": "new"})

    one_hour_ago = dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=1)
    _set_created_at(db_session, ActionApproval, old_row.approval_id, one_hour_ago)

    cutoff = dt.datetime.now(dt.timezone.utc) - dt.timedelta(minutes=5)
    rows = list_session_pending_action_approvals(
        db_session, bs.id, created_after=cutoff
    )
    returned_ids = {r.approval_id for r in rows}
    assert new_row.approval_id in returned_ids
    assert old_row.approval_id not in returned_ids
