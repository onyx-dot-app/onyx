"""External-dependency-unit tests for the ``action_approval`` query module.

Runs real ORM/SQL against Postgres so schema/query regressions (race arbiter,
refresh-after-UPDATE, filter inclusivity) actually fail.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Callable
from typing import Any
from uuid import UUID, uuid4

import pytest
from sqlalchemy import delete
from sqlalchemy.orm import Session

from onyx.db.enums import (
    ActionPolicy,
    ApprovalDecidedVia,
    ApprovalDecision,
    ExternalAppType,
    GatedAppKind,
)
from onyx.db.models import ActionApproval, BuildSession, ExternalApp
from onyx.server.features.build.db.action_approval import (
    get_action_approval,
    get_action_approval_for_user,
    insert_action_approval,
    list_session_pending_action_approvals,
    try_record_decision,
)
from tests.common.craft.payloads import action_entry, default_action_entries
from tests.external_dependency_unit.craft.db_helpers import (
    force_approval_created_at,
    make_user,
)


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
        action_entry("x.read", policy=ActionPolicy.ALWAYS),
        action_entry("x.write", policy=ActionPolicy.ASK),
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
    force_approval_created_at(db_session, old_row.approval_id, one_hour_ago)

    cutoff = dt.datetime.now(dt.timezone.utc) - dt.timedelta(minutes=5)
    rows = list_session_pending_action_approvals(
        db_session, bs.id, created_after=cutoff
    )
    returned_ids = {r.approval_id for r in rows}
    assert new_row.approval_id in returned_ids
    assert old_row.approval_id not in returned_ids


@pytest.mark.parametrize("pre_decided", [False, True])
def test_deleting_app_preserves_action_approval(
    db_session: Session,
    tenant_context: None,  # noqa: ARG001
    build_session_with_user: Callable[..., BuildSession],
    pre_decided: bool,
) -> None:
    user = make_user(db_session)
    session = build_session_with_user(user=user)
    app = ExternalApp(
        name="Audit test",
        app_type=ExternalAppType.CUSTOM,
        enabled=True,
        upstream_url_patterns=[],
        auth_template={},
        organization_credentials={},
    )
    db_session.add(app)
    db_session.flush()
    row = insert_action_approval(
        db_session,
        session_id=session.id,
        actions=default_action_entries(),
        app_name=app.name,
        payload={},
        target=(GatedAppKind.EXTERNAL_APP, app.id),
        decision=ApprovalDecision.APPROVED if pre_decided else None,
        decided_via=ApprovalDecidedVia.SESSION_GRANT if pre_decided else None,
    )
    db_session.commit()
    assert row.gated_app_id is not None
    if pre_decided:
        assert row.decision == ApprovalDecision.APPROVED
        assert row.decided_via == ApprovalDecidedVia.SESSION_GRANT
        assert row.decided_at is not None and row.decided_at.tzinfo is not None
    else:
        assert row.decision is None
        assert row.decided_via is None
        assert row.decided_at is None
    db_session.execute(delete(ExternalApp).where(ExternalApp.id == app.id))
    db_session.commit()
    db_session.refresh(row)
    assert row.gated_app_id is None
    assert row.app_name == "Audit test"
