"""Tests for the approvals router. Route functions are invoked directly with a
constructed ``User`` and the test ``db_session`` (no ``TestClient``)."""

from __future__ import annotations

from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from threading import Barrier
from uuid import UUID, uuid4

import pytest
import redis
from sqlalchemy import text
from sqlalchemy.orm import Session

from onyx.cache.factory import get_cache_backend
from onyx.db.enums import (
    ActionPolicy,
    ApprovalDecidedVia,
    ApprovalDecision,
    GatedAppKind,
)
from onyx.db.models import ActionApproval, BuildSession
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.external_apps.matching.engine import MatchedAction
from onyx.sandbox_proxy import approval_cache
from onyx.server.features.build.approvals.api import (
    ApprovalChoice,
    DecisionBody,
    list_live_approvals,
    list_session_approval_status,
    list_session_approvals,
    submit_decision,
)
from onyx.server.features.build.configs import SANDBOX_APPROVAL_WAIT_TIMEOUT_SECONDS
from onyx.server.features.build.db import action_approval
from onyx.server.features.build.db.action_approval import (
    get_action_approval,
    get_action_approval_for_user,
    insert_action_approval,
    try_record_decision,
)
from shared_configs.configs import POSTGRES_DEFAULT_SCHEMA_STANDARD_VALUE
from tests.common.craft.payloads import action_entry
from tests.common.craft.payloads import default_action_entries as _default_actions
from tests.external_dependency_unit.craft.db_helpers import (
    force_approval_created_at,
    make_external_app,
    make_skill,
    make_user,
)


def _stub_send_wake_noop(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(approval_cache, "send_wake", lambda *_args, **_kwargs: None)


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

    pending = insert_action_approval(
        db_session,
        session_id=session.id,
        actions=_default_actions(),
        app_name="Shell",
        payload={"cmd": "ls"},
    )
    decided = insert_action_approval(
        db_session,
        session_id=session.id,
        actions=_default_actions(),
        app_name="Shell",
        payload={"cmd": "rm"},
    )
    stale = insert_action_approval(
        db_session,
        session_id=session.id,
        actions=_default_actions(),
        app_name="Shell",
        payload={"cmd": "old"},
    )
    result = try_record_decision(
        db_session,
        approval_id=decided.approval_id,
        decision=ApprovalDecision.APPROVED,
    )
    assert result is not None
    db_session.commit()

    stale_when = datetime.now(timezone.utc) - timedelta(
        seconds=SANDBOX_APPROVAL_WAIT_TIMEOUT_SECONDS + 10
    )
    force_approval_created_at(db_session, stale.approval_id, stale_when)

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
    insert_action_approval(
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
    approval = insert_action_approval(
        db_session,
        session_id=session.id,
        actions=_default_actions(),
        app_name="Shell",
        payload={"cmd": "ls"},
    )
    db_session.commit()

    # Pre-read through the same accessor the API uses, populating the identity
    # map so we can observe the refresh propagate to this exact object.
    current = get_action_approval_for_user(db_session, approval.approval_id, user.id)
    assert current is not None
    assert current.decision is None
    assert current.decided_at is None

    view = submit_decision(
        approval_id=approval.approval_id,
        body=DecisionBody(decision=ApprovalChoice.REJECT),
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
    approval = insert_action_approval(
        db_session,
        session_id=session.id,
        actions=_default_actions(),
        app_name="Shell",
        payload={"cmd": "ls"},
    )
    db_session.commit()

    first = submit_decision(
        approval_id=approval.approval_id,
        body=DecisionBody(decision=ApprovalChoice.REJECT),
        user=user,
        db_session=db_session,
    )
    second = submit_decision(
        approval_id=approval.approval_id,
        body=DecisionBody(decision=ApprovalChoice.REJECT),
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
    approval = insert_action_approval(
        db_session,
        session_id=session.id,
        actions=_default_actions(),
        app_name="Shell",
        payload={"cmd": "ls"},
    )
    db_session.commit()

    submit_decision(
        approval_id=approval.approval_id,
        body=DecisionBody(decision=ApprovalChoice.REJECT),
        user=user,
        db_session=db_session,
    )

    with pytest.raises(OnyxError) as exc_info:
        submit_decision(
            approval_id=approval.approval_id,
            body=DecisionBody(decision=ApprovalChoice.APPROVE_ONCE),
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
        approval = insert_action_approval(
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
            body=DecisionBody(decision=ApprovalChoice.APPROVE_ONCE),
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
    approval = insert_action_approval(
        db_session,
        session_id=session.id,
        actions=_default_actions(),
        app_name="Shell",
        payload={"cmd": "ls"},
    )
    db_session.commit()

    cache = get_cache_backend(tenant_id=POSTGRES_DEFAULT_SCHEMA_STANDARD_VALUE)
    # Pre-clean so a leftover from a prior failed run can't mask the bug.
    cache.delete(approval_cache._wake_key(approval.approval_id))

    view = submit_decision(
        approval_id=approval.approval_id,
        body=DecisionBody(decision=ApprovalChoice.APPROVE_ONCE),
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
    always_read = action_entry("slack.channel.read", policy=ActionPolicy.ALWAYS)
    ask_upload = action_entry("slack.files.upload")

    current = insert_action_approval(
        db_session,
        session_id=session.id,
        actions=[ask_send, always_read],
        app_name="Slack",
        payload={"text": "current"},
        target=(GatedAppKind.EXTERNAL_APP, app.id),
    )
    matching = insert_action_approval(
        db_session,
        session_id=session.id,
        actions=[ask_send],
        app_name="Slack",
        payload={"text": "matching"},
        target=(GatedAppKind.EXTERNAL_APP, app.id),
    )
    broader = insert_action_approval(
        db_session,
        session_id=session.id,
        actions=[ask_send, ask_upload],
        app_name="Slack",
        payload={"text": "broader"},
        target=(GatedAppKind.EXTERNAL_APP, app.id),
    )
    other = insert_action_approval(
        db_session,
        session_id=session.id,
        actions=[ask_send],
        app_name="Other",
        payload={"text": "other"},
        target=(GatedAppKind.EXTERNAL_APP, other_app.id),
    )
    db_session.commit()

    wakes: list[tuple[str, ApprovalDecision]] = []

    def _record_wake(
        approval_id: UUID, decision: ApprovalDecision, *_args: object, **_kwargs: object
    ) -> None:
        wakes.append((str(approval_id), decision))

    monkeypatch.setattr(approval_cache, "send_wake", _record_wake)
    read_grants = action_approval.list_session_grant_action_approvals
    grant_reads = 0

    def read_grants_once(
        db_session: Session, session_id: UUID, *, gated_app_id: int | None
    ) -> list[ActionApproval]:
        nonlocal grant_reads
        grant_reads += 1
        if grant_reads > 1:
            raise RuntimeError("Database unavailable after the decision commits")
        return read_grants(db_session, session_id, gated_app_id=gated_app_id)

    monkeypatch.setattr(
        action_approval, "list_session_grant_action_approvals", read_grants_once
    )

    response = submit_decision(
        body=DecisionBody(decision=ApprovalChoice.APPROVE_SESSION),
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

    cache = get_cache_backend(tenant_id=POSTGRES_DEFAULT_SCHEMA_STANDARD_VALUE)
    assert approval_cache.cached_session_grants_cover(
        session_id=session.id,
        kind=GatedAppKind.EXTERNAL_APP,
        target_id=app.id,
        action_types=["slack.chat.post"],
        cache=cache,
    )
    assert not approval_cache.cached_session_grants_cover(
        session_id=session.id,
        kind=GatedAppKind.EXTERNAL_APP,
        target_id=app.id,
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
    approval = insert_action_approval(
        db_session,
        session_id=session.id,
        actions=_default_actions(),
        app_name="Shell",
        payload={"cmd": "ls"},
    )
    db_session.commit()

    cache = get_cache_backend(tenant_id=POSTGRES_DEFAULT_SCHEMA_STANDARD_VALUE)
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
        body=DecisionBody(decision=ApprovalChoice.APPROVE_ONCE),
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
    persisted = get_action_approval(db_session, approval.approval_id)
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
    JSONB string back to the ``ActionPolicy`` enum."""
    user = make_user(db_session, email_prefix="multi_action_view")
    session = build_session_with_user(user=user)

    # Strictest-first ordering is the API contract surface; ASK > ALWAYS.
    expected_actions = [
        MatchedAction(
            action_type="linear.issues.create",
            display_name="Create an issue",
            description="Create a new issue.",
            policy=ActionPolicy.ASK,
        ),
        MatchedAction(
            action_type="linear.viewer.read",
            display_name="Read the connected user",
            description="Read the authenticated user's profile (viewer).",
            policy=ActionPolicy.ALWAYS,
        ),
    ]
    insert_action_approval(
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


@pytest.mark.parametrize("choice", ["approve_once", "approve_session", "reject"])
def test_all_decisions_reject_stale_requests(
    choice: str,
    db_session: Session,
    tenant_context: None,  # noqa: ARG001
    monkeypatch: pytest.MonkeyPatch,
    build_session_with_user: Callable[..., BuildSession],
) -> None:
    _stub_send_wake_noop(monkeypatch)
    user = make_user(db_session, email_prefix="stale_decision")
    session = build_session_with_user(user=user)
    row = insert_action_approval(
        db_session,
        session_id=session.id,
        actions=_default_actions(),
        app_name="Slack",
        payload={},
    )
    db_session.commit()
    force_approval_created_at(
        db_session,
        row.approval_id,
        datetime.now(timezone.utc)
        - timedelta(seconds=SANDBOX_APPROVAL_WAIT_TIMEOUT_SECONDS + 10),
    )
    with pytest.raises(OnyxError) as exc:
        submit_decision(
            row.approval_id,
            DecisionBody.model_validate({"decision": choice}),
            user,
            db_session,
        )
    assert exc.value.error_code == OnyxErrorCode.CONFLICT
    db_session.refresh(row)
    assert row.decision is None


def test_session_decision_retry_cannot_change_scope(
    db_session: Session,
    tenant_context: None,  # noqa: ARG001
    monkeypatch: pytest.MonkeyPatch,
    build_session_with_user: Callable[..., BuildSession],
) -> None:
    _stub_send_wake_noop(monkeypatch)
    user = make_user(db_session, email_prefix="decision_scope")
    session = build_session_with_user(user=user)
    app = make_external_app(db_session, skill=make_skill(db_session), auth_template={})
    row = insert_action_approval(
        db_session,
        session_id=session.id,
        actions=_default_actions(),
        app_name="Slack",
        payload={},
        target=(GatedAppKind.EXTERNAL_APP, app.id),
    )
    db_session.commit()
    body = DecisionBody(decision=ApprovalChoice.APPROVE_SESSION)
    first = submit_decision(row.approval_id, body, user, db_session)
    retry = submit_decision(row.approval_id, body, user, db_session)
    assert retry.decision == first.decision == ApprovalDecision.APPROVED
    with pytest.raises(OnyxError) as exc:
        submit_decision(
            row.approval_id,
            DecisionBody(decision=ApprovalChoice.APPROVE_ONCE),
            user,
            db_session,
        )
    assert exc.value.error_code == OnyxErrorCode.CONFLICT


def test_approve_once_cannot_be_upgraded_by_retry(
    db_session: Session,
    tenant_context: None,  # noqa: ARG001
    monkeypatch: pytest.MonkeyPatch,
    build_session_with_user: Callable[..., BuildSession],
) -> None:
    _stub_send_wake_noop(monkeypatch)
    user = make_user(db_session, email_prefix="decision_once")
    session = build_session_with_user(user=user)
    row = insert_action_approval(
        db_session,
        session_id=session.id,
        actions=_default_actions(),
        app_name="Slack",
        payload={},
    )
    db_session.commit()
    submit_decision(
        row.approval_id,
        DecisionBody(decision=ApprovalChoice.APPROVE_ONCE),
        user,
        db_session,
    )
    with pytest.raises(OnyxError) as exc:
        submit_decision(
            row.approval_id,
            DecisionBody(decision=ApprovalChoice.APPROVE_SESSION),
            user,
            db_session,
        )
    assert exc.value.error_code == OnyxErrorCode.CONFLICT
    db_session.refresh(row)
    assert row.decided_via == ApprovalDecidedVia.USER


def test_history_retains_expired_requests_and_checks_owner(
    db_session: Session,
    tenant_context: None,  # noqa: ARG001
    build_session_with_user: Callable[..., BuildSession],
) -> None:
    owner = make_user(db_session, email_prefix="history_owner")
    other = make_user(db_session, email_prefix="history_other")
    session = build_session_with_user(user=owner)
    row = insert_action_approval(
        db_session,
        session_id=session.id,
        actions=_default_actions(),
        app_name="Slack",
        payload={},
    )
    try_record_decision(
        db_session, approval_id=row.approval_id, decision=ApprovalDecision.EXPIRED
    )
    db_session.commit()
    assert list_live_approvals(session.id, owner, db_session).items == []
    history = list_session_approvals(session.id, owner, db_session)
    assert [item.decision for item in history.items] == [ApprovalDecision.EXPIRED]
    assert not history.items[0].is_live
    with pytest.raises(OnyxError) as exc:
        list_session_approvals(session.id, other, db_session)
    assert exc.value.error_code == OnyxErrorCode.NOT_FOUND


def test_unknown_external_action_can_only_be_approved_once(
    db_session: Session,
    tenant_context: None,  # noqa: ARG001
    monkeypatch: pytest.MonkeyPatch,
    build_session_with_user: Callable[..., BuildSession],
) -> None:
    _stub_send_wake_noop(monkeypatch)
    user = make_user(db_session, email_prefix="unknown_action")
    session = build_session_with_user(user=user)
    app = make_external_app(db_session, skill=make_skill(db_session), auth_template={})
    row = insert_action_approval(
        db_session,
        session_id=session.id,
        actions=[action_entry("unspecified")],
        app_name="Custom",
        payload={},
        target=(GatedAppKind.EXTERNAL_APP, app.id),
    )
    db_session.commit()
    view = list_session_approvals(session.id, user, db_session).items[0]
    assert not view.can_approve_for_session
    with pytest.raises(OnyxError) as exc:
        submit_decision(
            row.approval_id,
            DecisionBody(decision=ApprovalChoice.APPROVE_SESSION),
            user,
            db_session,
        )
    assert exc.value.error_code == OnyxErrorCode.INVALID_INPUT
    result = submit_decision(
        row.approval_id,
        DecisionBody(decision=ApprovalChoice.APPROVE_ONCE),
        user,
        db_session,
    )
    assert result.decision == ApprovalDecision.APPROVED


def test_history_keeps_all_live_requests_when_outcomes_exceed_limit(
    db_session: Session,
    tenant_context: None,  # noqa: ARG001
    build_session_with_user: Callable[..., BuildSession],
) -> None:
    owner = make_user(db_session, email_prefix="busy_history")
    session = build_session_with_user(user=owner)
    pending = insert_action_approval(
        db_session,
        session_id=session.id,
        actions=_default_actions(),
        app_name="Slack",
        payload={},
    )
    for _ in range(51):
        insert_action_approval(
            db_session,
            session_id=session.id,
            actions=_default_actions(),
            app_name="Slack",
            payload={},
            decision=ApprovalDecision.REJECTED,
        )
    db_session.commit()

    history = list_session_approvals(session.id, owner, db_session)
    assert len(history.items) == 51
    assert [item.approval_id for item in history.items if item.is_live] == [
        pending.approval_id
    ]


def test_concurrent_session_approvals_do_not_deadlock(
    db_session: Session,
    tenant_context: None,  # noqa: ARG001
    monkeypatch: pytest.MonkeyPatch,
    build_session_with_user: Callable[..., BuildSession],
) -> None:
    from onyx.db.models import User
    from onyx.server.features.build.db import action_approval
    from shared_configs.contextvars import CURRENT_TENANT_ID_CONTEXTVAR

    user = make_user(db_session, email_prefix="concurrent_grants")
    session = build_session_with_user(user=user)
    app = make_external_app(db_session, skill=make_skill(db_session), auth_template={})
    ids = [
        insert_action_approval(
            db_session,
            session_id=session.id,
            actions=[action_entry("slack.chat.post")],
            app_name="Slack",
            payload={},
            target=(GatedAppKind.EXTERNAL_APP, app.id),
        ).approval_id
        for _ in range(2)
    ]
    user_id = user.id
    db_session.commit()
    barrier = Barrier(2)
    original = action_approval.get_action_approval_for_user

    def synchronized_read(
        db: Session, approval_id: UUID, user_id: UUID, *, lock_session: bool = False
    ) -> ActionApproval | None:
        barrier.wait(timeout=10)
        return original(db, approval_id, user_id, lock_session=lock_session)

    monkeypatch.setattr(
        action_approval, "get_action_approval_for_user", synchronized_read
    )
    _stub_send_wake_noop(monkeypatch)
    engine = db_session.get_bind()

    def approve(approval_id: UUID) -> ApprovalDecision | None:
        token = CURRENT_TENANT_ID_CONTEXTVAR.set(POSTGRES_DEFAULT_SCHEMA_STANDARD_VALUE)
        try:
            with Session(engine) as db:
                db.execute(text("SET LOCAL lock_timeout = '5s'"))
                caller = db.get(User, user_id)
                assert caller is not None
                return submit_decision(
                    approval_id=approval_id,
                    body=DecisionBody(decision=ApprovalChoice.APPROVE_SESSION),
                    user=caller,
                    db_session=db,
                ).decision
        finally:
            CURRENT_TENANT_ID_CONTEXTVAR.reset(token)

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(approve, ids))
    assert results == [ApprovalDecision.APPROVED, ApprovalDecision.APPROVED]


def test_status_poll_omits_payloads_and_reports_expiry(
    db_session: Session,
    tenant_context: None,  # noqa: ARG001
    build_session_with_user: Callable[..., BuildSession],
) -> None:
    from sqlalchemy import inspect

    from onyx.server.features.build.db.action_approval import (
        list_session_action_approvals,
    )

    owner = make_user(db_session, email_prefix="status_owner")
    other = make_user(db_session, email_prefix="status_other")
    session = build_session_with_user(user=owner)
    row = insert_action_approval(
        db_session,
        session_id=session.id,
        actions=_default_actions(),
        app_name="Slack",
        payload={"large": "x" * 100_000},
    )
    db_session.commit()
    approval_id = row.approval_id
    db_session.expunge(row)
    cutoff = datetime.now(timezone.utc) - timedelta(seconds=180)
    rows = list_session_action_approvals(
        db_session, session.id, created_after=cutoff, status_only=True
    )
    assert "payload" in inspect(rows[0]).unloaded
    assert "actions" in inspect(rows[0]).unloaded
    status = list_session_approval_status(session.id, owner, db_session)
    assert status[0].model_dump() == {
        "approval_id": approval_id,
        "decision": None,
        "is_live": True,
    }
    rows[0].created_at = cutoff - timedelta(seconds=1)
    db_session.commit()
    assert not list_session_approval_status(session.id, owner, db_session)[0].is_live
    with pytest.raises(OnyxError) as exc:
        list_session_approval_status(session.id, other, db_session)
    assert exc.value.error_code == OnyxErrorCode.NOT_FOUND
