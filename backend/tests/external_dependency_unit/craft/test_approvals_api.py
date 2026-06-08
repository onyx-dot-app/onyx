"""Tests for the approvals router. Route functions are invoked directly with a
constructed ``User`` and the test ``db_session`` (no ``TestClient``)."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from datetime import timedelta
from datetime import timezone
from uuid import UUID
from uuid import uuid4

import pytest
import redis
from sqlalchemy.orm import Session

from onyx.cache.factory import get_cache_backend
from onyx.db.enums import ApprovalDecidedVia
from onyx.db.enums import ApprovalDecision
from onyx.db.enums import EndpointPolicy
from onyx.db.models import ActionApproval
from onyx.db.models import BuildSession
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.external_apps.matching.engine import MatchedAction
from onyx.sandbox_proxy import approval_cache
from onyx.server.features.build.approvals.api import DecisionBody
from onyx.server.features.build.approvals.api import list_live_approvals
from onyx.server.features.build.approvals.api import list_session_approvals
from onyx.server.features.build.approvals.api import submit_decision
from onyx.server.features.build.approvals.api import submit_session_grant
from onyx.server.features.build.db import action_approval
from tests.external_dependency_unit.constants import TEST_TENANT_ID
from tests.external_dependency_unit.craft._test_helpers import _set_created_at
from tests.external_dependency_unit.craft._test_helpers import action_entry
from tests.external_dependency_unit.craft._test_helpers import (
    default_action_entries as _default_actions,
)
from tests.external_dependency_unit.craft._test_helpers import make_external_app
from tests.external_dependency_unit.craft._test_helpers import make_skill
from tests.external_dependency_unit.craft._test_helpers import make_user


def _stub_send_wake_noop(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(approval_cache, "send_wake", lambda *_args, **_kwargs: None)


# Hardcoded spec; the completeness check below pins the source constant to it.
WAIT_TIMEOUT_S_SPEC = 180


def test_wait_timeout_spec() -> None:
    assert approval_cache.WAIT_TIMEOUT_S == WAIT_TIMEOUT_S_SPEC


# --------------------------------------------------------------------------- #
# list_live_approvals
# --------------------------------------------------------------------------- #


def test_list_live_approvals_filter_logic(
    db_session: Session,
    tenant_context: None,  # noqa: ARG001
    build_session_with_user: Callable[..., BuildSession],
) -> None:
    """Only `decision IS NULL` rows within the wait window come back."""
    user = make_user(db_session, email_prefix="live_filter")
    session = build_session_with_user(user=user)

    pending = action_approval.insert_action_approval(
        db_session,
        session_id=session.id,
        actions=_default_actions(),
        app_name="Shell",
        payload={"cmd": "ls"},
    )
    decided = action_approval.insert_action_approval(
        db_session,
        session_id=session.id,
        actions=_default_actions(),
        app_name="Shell",
        payload={"cmd": "rm"},
    )
    stale = action_approval.insert_action_approval(
        db_session,
        session_id=session.id,
        actions=_default_actions(),
        app_name="Shell",
        payload={"cmd": "old"},
    )
    result = action_approval.try_record_decision(
        db_session,
        approval_id=decided.approval_id,
        decision=ApprovalDecision.APPROVED,
    )
    assert result is not None
    db_session.commit()

    # Push the stale row just past the 180s spec cutoff (hardcoded, not derived).
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
        actions=_default_actions(),
        app_name="Shell",
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
        actions=_default_actions(),
        app_name="Shell",
        payload={"cmd": "pending"},
    )
    approved_row = action_approval.insert_action_approval(
        db_session,
        session_id=session.id,
        actions=_default_actions(),
        app_name="Shell",
        payload={"cmd": "approved"},
    )
    rejected_row = action_approval.insert_action_approval(
        db_session,
        session_id=session.id,
        actions=_default_actions(),
        app_name="Shell",
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
        actions=_default_actions(),
        app_name="Shell",
        payload={"cmd": "approved"},
    )
    rejected_row = action_approval.insert_action_approval(
        db_session,
        session_id=session.id,
        actions=_default_actions(),
        app_name="Shell",
        payload={"cmd": "rejected"},
    )
    action_approval.insert_action_approval(
        db_session,
        session_id=session.id,
        actions=_default_actions(),
        app_name="Shell",
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
    """``since`` cuts off rows before the boundary, ``until`` cuts off rows after it."""
    user = make_user(db_session, email_prefix=f"audit_{direction}")
    session = build_session_with_user(user=user)

    old_row = action_approval.insert_action_approval(
        db_session,
        session_id=session.id,
        actions=_default_actions(),
        app_name="Shell",
        payload={"cmd": "old"},
    )
    new_row = action_approval.insert_action_approval(
        db_session,
        session_id=session.id,
        actions=_default_actions(),
        app_name="Shell",
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

    Regression guard: ``try_record_decision`` does a conditional UPDATE with
    ``synchronize_session=False`` on an ``expire_on_commit=False`` session, so
    without its ``db_session.refresh(row)`` the caller would still see
    ``decision=None``. We capture the same ORM object the API refreshes and
    assert it flips from None to the new decision.
    """
    _stub_send_wake_noop(monkeypatch)

    user = make_user(db_session, email_prefix="decide_happy")
    session = build_session_with_user(user=user)
    approval = action_approval.insert_action_approval(
        db_session,
        session_id=session.id,
        actions=_default_actions(),
        app_name="Shell",
        payload={"cmd": "ls"},
    )
    db_session.commit()

    # Pre-read through the same accessor the API uses, populating the identity
    # map so we can observe the refresh propagate to this exact object.
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

    # Same in-memory object now reflects post-UPDATE state (would be None
    # if the refresh() in try_record_decision were removed).
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
        actions=_default_actions(),
        app_name="Shell",
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
        actions=_default_actions(),
        app_name="Shell",
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
    """Both missing-row and non-owner shapes return ``NOT_FOUND`` (no existence leak)."""
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
            actions=_default_actions(),
            app_name="Shell",
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
        actions=_default_actions(),
        app_name="Shell",
        payload={"cmd": "ls"},
    )
    db_session.commit()

    cache = get_cache_backend(tenant_id=TEST_TENANT_ID)
    # Pre-clean so a leftover from a prior failed run can't mask the bug.
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


def test_submit_session_grant_approves_matching_pending_rows(
    db_session: Session,
    tenant_context: None,  # noqa: ARG001
    monkeypatch: pytest.MonkeyPatch,
    build_session_with_user: Callable[..., BuildSession],
) -> None:
    user = make_user(db_session, email_prefix="session_grant")
    session = build_session_with_user(user=user)
    app = make_external_app(db_session, skill=make_skill(db_session), auth_template={})
    other_app = make_external_app(
        db_session, skill=make_skill(db_session), auth_template={}
    )
    ask_send = action_entry("slack.chat.post")
    always_read = action_entry("slack.channel.read", policy=EndpointPolicy.ALWAYS)
    ask_upload = action_entry("slack.files.upload")

    current = action_approval.insert_action_approval(
        db_session,
        session_id=session.id,
        actions=[ask_send, always_read],
        app_name="Slack",
        payload={"text": "current"},
        external_app_id=app.id,
    )
    matching = action_approval.insert_action_approval(
        db_session,
        session_id=session.id,
        actions=[ask_send],
        app_name="Slack",
        payload={"text": "matching"},
        external_app_id=app.id,
    )
    broader = action_approval.insert_action_approval(
        db_session,
        session_id=session.id,
        actions=[ask_send, ask_upload],
        app_name="Slack",
        payload={"text": "broader"},
        external_app_id=app.id,
    )
    other = action_approval.insert_action_approval(
        db_session,
        session_id=session.id,
        actions=[ask_send],
        app_name="Other",
        payload={"text": "other"},
        external_app_id=other_app.id,
    )
    db_session.commit()

    wakes: list[tuple[str, ApprovalDecision]] = []

    def _record_wake(
        approval_id: UUID, decision: ApprovalDecision, *_args: object, **_kwargs: object
    ) -> None:
        wakes.append((str(approval_id), decision))

    monkeypatch.setattr(approval_cache, "send_wake", _record_wake)

    response = submit_session_grant(
        approval_id=current.approval_id,
        user=user,
        db_session=db_session,
    )

    assert response.approval_id == current.approval_id
    assert response.decision == ApprovalDecision.APPROVED

    db_session.refresh(current)
    db_session.refresh(matching)
    db_session.refresh(broader)
    db_session.refresh(other)
    assert current.decision == ApprovalDecision.APPROVED
    assert current.decided_via == ApprovalDecidedVia.SESSION_GRANT
    assert matching.decision == ApprovalDecision.APPROVED
    assert matching.decided_via == ApprovalDecidedVia.SESSION_GRANT
    assert broader.decision is None
    assert other.decision is None
    assert wakes == [
        (str(current.approval_id), ApprovalDecision.APPROVED),
        (str(matching.approval_id), ApprovalDecision.APPROVED),
    ]

    cache = get_cache_backend(tenant_id=TEST_TENANT_ID)
    assert approval_cache.cached_session_grants_cover(
        session_id=session.id,
        external_app_id=app.id,
        action_types=["slack.chat.post"],
        cache=cache,
    )
    assert not approval_cache.cached_session_grants_cover(
        session_id=session.id,
        external_app_id=app.id,
        action_types=["slack.files.upload"],
        cache=cache,
    )


def test_submit_decision_swallows_transient_wake_failure(
    db_session: Session,
    tenant_context: None,  # noqa: ARG001
    monkeypatch: pytest.MonkeyPatch,
    build_session_with_user: Callable[..., BuildSession],
) -> None:
    """A failing wake push must NOT bubble out — the decision is committed regardless."""
    user = make_user(db_session, email_prefix="decide_wake_fail")
    session = build_session_with_user(user=user)
    approval = action_approval.insert_action_approval(
        db_session,
        session_id=session.id,
        actions=_default_actions(),
        app_name="Shell",
        payload={"cmd": "ls"},
    )
    db_session.commit()

    cache = get_cache_backend(tenant_id=TEST_TENANT_ID)
    # Pre-clean so the post-call assertion isn't poisoned by a leftover.
    cache.delete(approval_cache._wake_key(approval.approval_id))

    call_count = 0

    def _boom(*_args: object, **_kwargs: object) -> None:
        # redis.RedisError is in CACHE_TRANSIENT_ERRORS, which the API catches;
        # any other type would bubble out and fail the test.
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

    # Guards against a refactor that drops the call site (the swallow assertion
    # would still pass for the wrong reason).
    assert call_count == 1

    popped = cache.blpop([approval_cache._wake_key(approval.approval_id)], timeout=1)
    assert popped is None, "expected no wake entry after the push failed"

    # Verify the row is committed in Postgres, not just in-memory.
    db_session.expire_all()
    persisted = action_approval.get_action_approval(db_session, approval.approval_id)
    assert persisted is not None
    assert persisted.decision == ApprovalDecision.APPROVED


# --------------------------------------------------------------------------- #
# ApprovalView shape — multi-action round-trip through the read API
# --------------------------------------------------------------------------- #


def test_list_live_approvals_returns_multi_action_view(
    db_session: Session,
    tenant_context: None,  # noqa: ARG001
    build_session_with_user: Callable[..., BuildSession],
) -> None:
    """A row persisted with multiple matched actions surfaces all of them on
    ``ApprovalView.actions``, with each entry's policy round-tripped from the
    JSONB string back to the ``EndpointPolicy`` enum."""
    user = make_user(db_session, email_prefix="multi_action_view")
    session = build_session_with_user(user=user)

    # Strictest-first ordering is the API contract surface; ASK > ALWAYS.
    expected_actions = [
        MatchedAction(
            action_type="linear.issues.create",
            display_name="Create an issue",
            description="Create a new issue.",
            policy=EndpointPolicy.ASK,
        ),
        MatchedAction(
            action_type="linear.viewer.read",
            display_name="Read the connected user",
            description="Read the authenticated user's profile (viewer).",
            policy=EndpointPolicy.ALWAYS,
        ),
    ]
    action_approval.insert_action_approval(
        db_session,
        session_id=session.id,
        actions=[a.model_dump(mode="json") for a in expected_actions],
        app_name="Linear",
        payload={"query": "mutation { issueCreate { id } }"},
    )
    db_session.commit()

    response = list_live_approvals(
        session_id=session.id, user=user, db_session=db_session
    )
    assert len(response.items) == 1
    view = response.items[0]
    assert view.app_name == "Linear"
    assert view.payload == {"query": "mutation { issueCreate { id } }"}
    assert view.actions == expected_actions
