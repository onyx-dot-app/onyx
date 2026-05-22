"""Tests for the approvals router (``backend/onyx/server/features/build/approvals/api.py``).

Covers the three endpoints (``list_live_approvals``, ``list_session_approvals``,
``submit_decision``) by invoking the route functions directly with a constructed
``User`` and the test ``db_session`` — same pattern as the sibling
``permission_sync`` tests, no ``TestClient``.

The submit-decision tests pin the wake push semantics (Redis side-effect +
swallow of transient errors), and one test specifically guards against a
regression where the post-UPDATE row served back to the caller would carry
the stale identity-mapped ``decision=None`` if the ORM session were not
refreshed.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from datetime import timedelta
from datetime import timezone
from uuid import uuid4

import pytest
import redis
from sqlalchemy.orm import Session

from onyx.cache.factory import get_cache_backend
from onyx.db.enums import ApprovalDecision
from onyx.db.models import ActionApproval
from onyx.db.models import BuildSession
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.sandbox_proxy import approval_cache
from onyx.server.features.build.approvals.api import DecisionBody
from onyx.server.features.build.approvals.api import list_live_approvals
from onyx.server.features.build.approvals.api import list_session_approvals
from onyx.server.features.build.approvals.api import submit_decision
from onyx.server.features.build.db import action_approval
from tests.external_dependency_unit.constants import TEST_TENANT_ID
from tests.external_dependency_unit.craft._test_helpers import _set_created_at
from tests.external_dependency_unit.craft._test_helpers import make_user

# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #


def _stub_send_wake_noop(monkeypatch: pytest.MonkeyPatch) -> None:
    """Monkeypatch send_wake to a no-op for tests that don't care about the wake side."""
    monkeypatch.setattr(approval_cache, "send_wake", lambda *_args, **_kwargs: None)


# --------------------------------------------------------------------------- #
# Constants — separate completeness check guards the source value.
# --------------------------------------------------------------------------- #


# Spec value pinned by tests in this file. The constant in source must match —
# enforced by ``test_wait_timeout_spec`` below.
WAIT_TIMEOUT_S_SPEC = 180


def test_wait_timeout_spec() -> None:
    """Pins the wait-timeout spec value.

    Tests that depend on the wait window hardcode 180 (the spec) rather than
    importing ``approval_cache.WAIT_TIMEOUT_S``. This separate completeness
    check guards the constant: if someone changes the source value without
    updating the spec, both this test and the dependent tests will fail —
    surfacing the spec change explicitly instead of silently moving with it.
    """
    assert approval_cache.WAIT_TIMEOUT_S == WAIT_TIMEOUT_S_SPEC


# --------------------------------------------------------------------------- #
# list_live_approvals
# --------------------------------------------------------------------------- #


def test_list_live_approvals_filter_logic(
    db_session: Session,
    tenant_context: None,  # noqa: ARG001
    build_session_with_user: Callable[..., BuildSession],
) -> None:
    """Only `decision IS NULL` rows within the wait window come back.

    Seeds three rows that pin BOTH filter rules at once:
    - one fresh pending row (should be returned),
    - one decided row (filtered out by the ``decision IS NULL`` rule),
    - one stale pending row (filtered out by the wait-window rule).
    """
    user = make_user(db_session, email_prefix="live_filter")
    session = build_session_with_user(user=user)

    pending = action_approval.insert_action_approval(
        db_session,
        session_id=session.id,
        action_type="shell",
        payload={"cmd": "ls"},
    )
    decided = action_approval.insert_action_approval(
        db_session,
        session_id=session.id,
        action_type="shell",
        payload={"cmd": "rm"},
    )
    stale = action_approval.insert_action_approval(
        db_session,
        session_id=session.id,
        action_type="shell",
        payload={"cmd": "old"},
    )
    # Mark the decided row so the ``decision IS NULL`` rule excludes it.
    result = action_approval.try_record_decision(
        db_session,
        approval_id=decided.approval_id,
        decision=ApprovalDecision.APPROVED,
    )
    assert result is not None
    db_session.commit()

    # Push the stale row just past the spec cutoff. We hardcode 190
    # (= spec 180 + 10) rather than derive from the source constant — see
    # ``test_wait_timeout_spec``.
    stale_when = datetime.now(timezone.utc) - timedelta(seconds=190)
    _set_created_at(db_session, ActionApproval, stale.approval_id, stale_when)

    response = list_live_approvals(
        session_id=session.id, user=user, db_session=db_session
    )

    returned_ids = {item.approval_id for item in response.items}
    assert returned_ids == {pending.approval_id}
    only = response.items[0]
    assert only.decision is None
    assert only.is_live is True


def test_list_live_approvals_non_owner_gets_not_found(
    db_session: Session,
    tenant_context: None,  # noqa: ARG001
    build_session_with_user: Callable[..., BuildSession],
) -> None:
    """Existence of a session owned by another user is not leaked."""
    owner = make_user(db_session, email_prefix="live_owner_a")
    intruder = make_user(db_session, email_prefix="live_owner_b")
    session = build_session_with_user(user=owner)
    action_approval.insert_action_approval(
        db_session,
        session_id=session.id,
        action_type="shell",
        payload={"cmd": "ls"},
    )
    db_session.commit()

    with pytest.raises(OnyxError) as exc_info:
        list_live_approvals(session_id=session.id, user=intruder, db_session=db_session)

    assert exc_info.value.error_code == OnyxErrorCode.NOT_FOUND


# --------------------------------------------------------------------------- #
# list_session_approvals
# --------------------------------------------------------------------------- #


def test_list_session_approvals_no_filter_returns_all(
    db_session: Session,
    tenant_context: None,  # noqa: ARG001
    build_session_with_user: Callable[..., BuildSession],
) -> None:
    """No filter returns every row for the session, pending included."""
    user = make_user(db_session, email_prefix="audit_all")
    session = build_session_with_user(user=user)

    pending = action_approval.insert_action_approval(
        db_session,
        session_id=session.id,
        action_type="shell",
        payload={"cmd": "pending"},
    )
    approved_row = action_approval.insert_action_approval(
        db_session,
        session_id=session.id,
        action_type="shell",
        payload={"cmd": "approved"},
    )
    rejected_row = action_approval.insert_action_approval(
        db_session,
        session_id=session.id,
        action_type="shell",
        payload={"cmd": "rejected"},
    )
    db_session.commit()

    assert (
        action_approval.try_record_decision(
            db_session,
            approval_id=approved_row.approval_id,
            decision=ApprovalDecision.APPROVED,
        )
        is not None
    )
    assert (
        action_approval.try_record_decision(
            db_session,
            approval_id=rejected_row.approval_id,
            decision=ApprovalDecision.REJECTED,
        )
        is not None
    )
    db_session.commit()

    response = list_session_approvals(
        session_id=session.id,
        decision=None,
        since=None,
        until=None,
        user=user,
        db_session=db_session,
    )

    returned_ids = {item.approval_id for item in response.items}
    assert returned_ids == {
        pending.approval_id,
        approved_row.approval_id,
        rejected_row.approval_id,
    }


def test_list_session_approvals_decision_filter(
    db_session: Session,
    tenant_context: None,  # noqa: ARG001
    build_session_with_user: Callable[..., BuildSession],
) -> None:
    """``decision=REJECTED`` returns only rejected rows."""
    user = make_user(db_session, email_prefix="audit_decision")
    session = build_session_with_user(user=user)

    approved_row = action_approval.insert_action_approval(
        db_session,
        session_id=session.id,
        action_type="shell",
        payload={"cmd": "approved"},
    )
    rejected_row = action_approval.insert_action_approval(
        db_session,
        session_id=session.id,
        action_type="shell",
        payload={"cmd": "rejected"},
    )
    action_approval.insert_action_approval(
        db_session,
        session_id=session.id,
        action_type="shell",
        payload={"cmd": "still-pending"},
    )
    db_session.commit()

    assert (
        action_approval.try_record_decision(
            db_session,
            approval_id=approved_row.approval_id,
            decision=ApprovalDecision.APPROVED,
        )
        is not None
    )
    assert (
        action_approval.try_record_decision(
            db_session,
            approval_id=rejected_row.approval_id,
            decision=ApprovalDecision.REJECTED,
        )
        is not None
    )
    db_session.commit()

    response = list_session_approvals(
        session_id=session.id,
        decision=ApprovalDecision.REJECTED,
        since=None,
        until=None,
        user=user,
        db_session=db_session,
    )

    returned_ids = [item.approval_id for item in response.items]
    assert returned_ids == [rejected_row.approval_id]
    assert response.items[0].decision == ApprovalDecision.REJECTED


@pytest.mark.parametrize("direction", ["since", "until"])
def test_list_session_approvals_time_filter(
    direction: str,
    db_session: Session,
    tenant_context: None,  # noqa: ARG001
    build_session_with_user: Callable[..., BuildSession],
) -> None:
    """Time-window cuts off rows on the wrong side of the boundary.

    - ``since`` cuts off rows whose ``created_at`` is before the boundary.
    - ``until`` cuts off rows whose ``created_at`` is after the boundary.
    """
    user = make_user(db_session, email_prefix=f"audit_{direction}")
    session = build_session_with_user(user=user)

    old_row = action_approval.insert_action_approval(
        db_session,
        session_id=session.id,
        action_type="shell",
        payload={"cmd": "old"},
    )
    new_row = action_approval.insert_action_approval(
        db_session,
        session_id=session.id,
        action_type="shell",
        payload={"cmd": "new"},
    )
    db_session.commit()

    now = datetime.now(timezone.utc)
    _set_created_at(
        db_session, ActionApproval, old_row.approval_id, now - timedelta(hours=2)
    )
    _set_created_at(
        db_session, ActionApproval, new_row.approval_id, now - timedelta(minutes=5)
    )

    boundary = now - timedelta(hours=1)
    since = boundary if direction == "since" else None
    until = boundary if direction == "until" else None
    expected_id = new_row.approval_id if direction == "since" else old_row.approval_id

    response = list_session_approvals(
        session_id=session.id,
        decision=None,
        since=since,
        until=until,
        user=user,
        db_session=db_session,
    )

    returned_ids = [item.approval_id for item in response.items]
    assert returned_ids == [expected_id]


# --------------------------------------------------------------------------- #
# submit_decision
# --------------------------------------------------------------------------- #


def test_submit_decision_happy_path_returns_refreshed_row(
    db_session: Session,
    tenant_context: None,  # noqa: ARG001
    monkeypatch: pytest.MonkeyPatch,
    build_session_with_user: Callable[..., BuildSession],
) -> None:
    """The response carries the post-UPDATE decision, not the stale identity-map state.

    Regression guard: the conditional UPDATE in ``try_record_decision`` uses
    ``synchronize_session=False`` against an ``expire_on_commit=False`` session.
    Without the ``db_session.refresh(row)`` inside ``try_record_decision``,
    the row handed to the caller would still report ``decision=None`` even
    though Postgres holds the new value. To pin this explicitly we capture the
    SAME ORM object that the API will internally fetch + refresh, assert its
    pre-submit state is ``decision is None``, then assert the same object's
    ``decision`` after the call reflects the new state.
    """
    # Stub the wake push — this test doesn't care about Redis side-effects.
    _stub_send_wake_noop(monkeypatch)

    user = make_user(db_session, email_prefix="decide_happy")
    session = build_session_with_user(user=user)
    approval = action_approval.insert_action_approval(
        db_session,
        session_id=session.id,
        action_type="shell",
        payload={"cmd": "ls"},
    )
    db_session.commit()

    # Pre-read the row through the same accessor the API uses; this populates
    # the identity map with ``decision=None`` so we can observe the refresh
    # propagating to that exact object.
    current = action_approval.get_action_approval_for_user(
        db_session, approval.approval_id, user.id
    )
    assert current is not None
    assert current.decision is None
    assert current.decided_at is None

    view = submit_decision(
        approval_id=approval.approval_id,
        body=DecisionBody(decision=ApprovalDecision.REJECTED),
        user=user,
        db_session=db_session,
    )

    assert view.approval_id == approval.approval_id
    assert view.decision == ApprovalDecision.REJECTED
    assert view.decided_at is not None
    assert view.is_live is False

    # The same in-memory ORM object now reflects the post-UPDATE state because
    # ``try_record_decision`` refreshed it. If that refresh() were removed,
    # ``current.decision`` would still be ``None`` here.
    assert current.decision == ApprovalDecision.REJECTED
    assert current.decided_at is not None


def test_submit_decision_same_decision_retry_is_idempotent(
    db_session: Session,
    tenant_context: None,  # noqa: ARG001
    monkeypatch: pytest.MonkeyPatch,
    build_session_with_user: Callable[..., BuildSession],
) -> None:
    """A repeat call with the same decision returns the same view (no CONFLICT)."""
    _stub_send_wake_noop(monkeypatch)

    user = make_user(db_session, email_prefix="decide_retry")
    session = build_session_with_user(user=user)
    approval = action_approval.insert_action_approval(
        db_session,
        session_id=session.id,
        action_type="shell",
        payload={"cmd": "ls"},
    )
    db_session.commit()

    first = submit_decision(
        approval_id=approval.approval_id,
        body=DecisionBody(decision=ApprovalDecision.REJECTED),
        user=user,
        db_session=db_session,
    )
    second = submit_decision(
        approval_id=approval.approval_id,
        body=DecisionBody(decision=ApprovalDecision.REJECTED),
        user=user,
        db_session=db_session,
    )

    assert first.decision == ApprovalDecision.REJECTED
    assert second.decision == ApprovalDecision.REJECTED
    assert second.approval_id == first.approval_id
    assert second.decided_at == first.decided_at


def test_submit_decision_different_decision_raises_conflict(
    db_session: Session,
    tenant_context: None,  # noqa: ARG001
    monkeypatch: pytest.MonkeyPatch,
    build_session_with_user: Callable[..., BuildSession],
) -> None:
    """A second call with a different decision raises ``CONFLICT``."""
    _stub_send_wake_noop(monkeypatch)

    user = make_user(db_session, email_prefix="decide_conflict")
    session = build_session_with_user(user=user)
    approval = action_approval.insert_action_approval(
        db_session,
        session_id=session.id,
        action_type="shell",
        payload={"cmd": "ls"},
    )
    db_session.commit()

    submit_decision(
        approval_id=approval.approval_id,
        body=DecisionBody(decision=ApprovalDecision.REJECTED),
        user=user,
        db_session=db_session,
    )

    with pytest.raises(OnyxError) as exc_info:
        submit_decision(
            approval_id=approval.approval_id,
            body=DecisionBody(decision=ApprovalDecision.APPROVED),
            user=user,
            db_session=db_session,
        )

    assert exc_info.value.error_code == OnyxErrorCode.CONFLICT


@pytest.mark.parametrize("case", ["missing", "non_owner"])
def test_submit_decision_not_found(
    case: str,
    db_session: Session,
    tenant_context: None,  # noqa: ARG001
    build_session_with_user: Callable[..., BuildSession],
) -> None:
    """Both missing-row and non-owner shapes return ``NOT_FOUND``.

    The ``non_owner`` case proves existence isn't leaked — a non-owning user
    must get exactly the same ``NOT_FOUND`` response shape as a totally
    random UUID, so the API can't be used as an existence oracle.
    """
    if case == "missing":
        user = make_user(db_session, email_prefix="decide_missing")
        target_id = uuid4()
    else:
        owner = make_user(db_session, email_prefix="decide_owner")
        user = make_user(db_session, email_prefix="decide_intruder")
        session = build_session_with_user(user=owner)
        approval = action_approval.insert_action_approval(
            db_session,
            session_id=session.id,
            action_type="shell",
            payload={"cmd": "ls"},
        )
        db_session.commit()
        target_id = approval.approval_id

    with pytest.raises(OnyxError) as exc_info:
        submit_decision(
            approval_id=target_id,
            body=DecisionBody(decision=ApprovalDecision.APPROVED),
            user=user,
            db_session=db_session,
        )

    assert exc_info.value.error_code == OnyxErrorCode.NOT_FOUND


def test_submit_decision_pushes_wake_on_redis(
    db_session: Session,
    tenant_context: None,  # noqa: ARG001
    build_session_with_user: Callable[..., BuildSession],
) -> None:
    """Successful decisions push the decision value onto ``approval:wake:{id}``."""
    user = make_user(db_session, email_prefix="decide_wake")
    session = build_session_with_user(user=user)
    approval = action_approval.insert_action_approval(
        db_session,
        session_id=session.id,
        action_type="shell",
        payload={"cmd": "ls"},
    )
    db_session.commit()

    cache = get_cache_backend(tenant_id=TEST_TENANT_ID)
    # Pre-clean the key — a leftover from a prior failed run would mask the bug.
    cache.delete(approval_cache._wake_key(approval.approval_id))

    view = submit_decision(
        approval_id=approval.approval_id,
        body=DecisionBody(decision=ApprovalDecision.APPROVED),
        user=user,
        db_session=db_session,
    )
    assert view.decision == ApprovalDecision.APPROVED

    popped = cache.blpop([approval_cache._wake_key(approval.approval_id)], timeout=1)
    assert popped is not None, "expected a wake entry on Redis after submit_decision"
    _key, value = popped
    decoded = value.decode() if isinstance(value, bytes) else value
    assert decoded == ApprovalDecision.APPROVED.value


def test_submit_decision_swallows_transient_wake_failure(
    db_session: Session,
    tenant_context: None,  # noqa: ARG001
    monkeypatch: pytest.MonkeyPatch,
    build_session_with_user: Callable[..., BuildSession],
) -> None:
    """A failing wake push must NOT bubble out — the decision is committed regardless.

    We pin three things:

    1. The wake-push attempt actually happens (counter increments to 1).
    2. The ``redis.RedisError`` (a member of ``CACHE_TRANSIENT_ERRORS``) is
       swallowed and does not abort the response.
    3. Because the push failed, the cache key has no entry — the proxy will
       fall back to the wait timeout.
    """
    user = make_user(db_session, email_prefix="decide_wake_fail")
    session = build_session_with_user(user=user)
    approval = action_approval.insert_action_approval(
        db_session,
        session_id=session.id,
        action_type="shell",
        payload={"cmd": "ls"},
    )
    db_session.commit()

    cache = get_cache_backend(tenant_id=TEST_TENANT_ID)
    # Pre-clean so the post-call assertion below isn't poisoned by a leftover.
    cache.delete(approval_cache._wake_key(approval.approval_id))

    call_count = 0

    def _boom(*_args: object, **_kwargs: object) -> None:
        # ``redis.RedisError`` is in ``CACHE_TRANSIENT_ERRORS`` — the API
        # catches that tuple specifically. Any other exception type would
        # (correctly) bubble out and fail the test.
        nonlocal call_count
        call_count += 1
        raise redis.RedisError("simulated transient cache outage")

    monkeypatch.setattr(approval_cache, "send_wake", _boom)

    view = submit_decision(
        approval_id=approval.approval_id,
        body=DecisionBody(decision=ApprovalDecision.APPROVED),
        user=user,
        db_session=db_session,
    )

    assert view.decision == ApprovalDecision.APPROVED
    assert view.decided_at is not None

    # The wake push was attempted exactly once. Pinning the counter guards
    # against a future refactor that silently drops the call site (in which
    # case the swallow assertion above would still pass for the wrong reason).
    assert call_count == 1

    # And because that single attempt raised, nothing landed on the wake key.
    popped = cache.blpop([approval_cache._wake_key(approval.approval_id)], timeout=1)
    assert popped is None, "expected no wake entry after the push failed"

    # Verify the row is committed in Postgres (not just hanging in-memory).
    db_session.expire_all()
    persisted = action_approval.get_action_approval(db_session, approval.approval_id)
    assert persisted is not None
    assert persisted.decision == ApprovalDecision.APPROVED
